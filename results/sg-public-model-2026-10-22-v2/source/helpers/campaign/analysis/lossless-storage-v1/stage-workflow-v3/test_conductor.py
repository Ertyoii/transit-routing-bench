"""Pure synthetic conductor control-flow tests; no process launches."""
import contextlib
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import conductor as c

class ConductorTests(unittest.TestCase):
    def run_script(self,reports,outcomes):
        calls=[]
        def preserve(s,index):
            calls.append(('preserve',index))
            if isinstance(reports.get(index),BaseException):
                raise reports[index]
            return {'status':'synthetic-storage-complete','terminal_stage_success':reports[index]}
        def launch(s,index):
            calls.append(('launch',index))
            if isinstance(outcomes.get(index),BaseException):
                raise outcomes[index]
            return {'returncode':outcomes[index]}
        return calls,preserve,launch
    def test_storage_failure_never_launches(self):
        calls,preserve,launch=self.run_script({0:OSError('synthetic archive failure')},{})
        with self.assertRaises(OSError):
            c.conduct(None,0,preserve=preserve,launch=launch)
        self.assertEqual(calls,[('preserve',0)])
    def test_terminal_failure_never_launches(self):
        calls,preserve,launch=self.run_script({0:False},{})
        with self.assertRaisesRegex(RuntimeError,'no next launch'):
            c.conduct(None,0,preserve=preserve,launch=launch)
        self.assertEqual(calls,[('preserve',0)])
    def test_launch_exception_is_not_retried(self):
        calls,preserve,launch=self.run_script({0:True},{1:OSError('synthetic launch failure')})
        with self.assertRaises(OSError):
            c.conduct(None,0,preserve=preserve,launch=launch)
        self.assertEqual(calls,[('preserve',0),('launch',1)])
    def test_nonzero_preserves_terminal_bytes_then_stops(self):
        calls,preserve,launch=self.run_script({0:True,1:False},{1:1})
        with self.assertRaisesRegex(RuntimeError,'nonzero'):
            c.conduct(None,0,preserve=preserve,launch=launch)
        self.assertEqual(calls,[('preserve',0),('launch',1),('preserve',1)])
    def test_next_stage_occurs_only_after_prior_storage(self):
        calls,preserve,launch=self.run_script({0:True,1:True,2:False},{1:0,2:0})
        with self.assertRaises(RuntimeError):
            c.conduct(None,0,preserve=preserve,launch=launch)
        self.assertEqual(calls,[('preserve',0),('launch',1),('preserve',1),('launch',2),('preserve',2)])
    def test_no_extra_stage_after_seven(self):
        calls,preserve,launch=self.run_script({7:True},{})
        class Storage:
            quiet=staticmethod(lambda _:contextlib.nullcontext())
            write_doc=mock.Mock()
        with mock.patch.object(c.w,'identity',return_value={'sha256':'synthetic'}):
            c.conduct(Storage,7,preserve=preserve,launch=launch)
        self.assertEqual(calls,[('preserve',7)])
        self.assertEqual(Storage.write_doc.call_count,1)

if __name__=='__main__':
    unittest.main(verbosity=2)
