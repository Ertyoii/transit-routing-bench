import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import order
import run_campaign as runner

class V2RunnerTest(unittest.TestCase):
    def test_balanced_order_preserves_every_cell(self):
        cells=[{'id':str(i)} for i in range(15)]
        value=order.balanced_order(cells,217,2)
        a,b=value['order'][:15],value['order'][15:]
        self.assertEqual([x['cell']['id'] for x in a],list(reversed([x['cell']['id'] for x in b])))
        self.assertEqual(len({x['cell']['id'] for x in a}),15)
        self.assertEqual(value,order.balanced_order(cells,217,2))

    def test_first_answer_supervisor_event(self):
        with tempfile.TemporaryDirectory(prefix='v2-runner-') as folder:
            root=Path(folder); run=root/'one';run.mkdir()
            spec={'id':'synthetic','argv':['/usr/bin/python3','-u','-c','import json,time;time.sleep(.02);print(json.dumps({"event":"first_available_answer","actual_answer_written":True}),flush=True)'],'cwd':str(root),'timeout_s':2}
            metadata={'id':'synthetic','argv':spec['argv'],'sources_before':[],'workload_gate':{}}
            status={'started_utc':'now','plan_sha256':'none'}
            with patch.object(runner,'prepare_run',return_value=(metadata,spec['argv'],root,{},[],2)), patch.object(runner,'competing_go_processes',return_value=[]):
                value=runner.run_one(spec,run,root,{},'0-3',status,root/'status.json',0,.05)
            self.assertTrue(value['ok'])
            self.assertEqual(len(value['first_available_answer_events']),1)
            self.assertGreater(value['launch_to_first_available_answer_ns'],20_000_000)
            self.assertLess(value['launch_to_first_available_answer_ns'],1_500_000_000)
            self.assertIn('/proc/loadavg',value['host_before'])
            self.assertIn('first_available_answer',(run/'stdout.log').read_text())

    def test_absent_event_stays_unknown(self):
        with tempfile.TemporaryDirectory(prefix='v2-runner-') as folder:
            root=Path(folder);run=root/'one';run.mkdir()
            spec={'id':'synthetic','argv':['/usr/bin/true'],'cwd':str(root),'timeout_s':2}
            metadata={'id':'synthetic','argv':spec['argv'],'sources_before':[],'workload_gate':{}}
            status={'started_utc':'now','plan_sha256':'none'}
            with patch.object(runner,'prepare_run',return_value=(metadata,spec['argv'],root,{},[],2)),patch.object(runner,'competing_go_processes',return_value=[]):
                value=runner.run_one(spec,run,root,{},'0-3',status,root/'status.json',0,.05)
            self.assertTrue(value['ok']);self.assertIsNone(value['launch_to_first_available_answer_ns'])

if __name__=='__main__':unittest.main()
