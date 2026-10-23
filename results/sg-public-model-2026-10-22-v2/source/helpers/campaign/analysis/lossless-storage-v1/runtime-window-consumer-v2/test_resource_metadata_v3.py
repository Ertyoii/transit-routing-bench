import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

P=Path(__file__).with_name('RESOURCE_METADATA_COMMAND_DRAFT_V3.py')
S=importlib.util.spec_from_file_location('resource_metadata_v3_fixture',P)
M=importlib.util.module_from_spec(S);S.loader.exec_module(M)

class ResourceMetadata(unittest.TestCase):
    def test_canonical_audited_hash_required(self):
        self.assertEqual(M.canonical_sha('a'*64),'a'*64)
        for value in ('a'*63,'A'*64,'g'*64,' '+('a'*64)):
            with self.assertRaises(RuntimeError):M.canonical_sha(value)
    def test_raw_and_model_content_forbidden_before_open(self):
        for path in (M.R/'data-workload/models/no.json',Path('/tmp/summary.json'),Path('/tmp/sparse-full-preparation.json'),Path('/tmp/METRICS_BY_RUN.json')):
            with self.assertRaises(RuntimeError):M.ref(path)
    def test_retention_requires_explicit_audited_hashes(self):
        args=types.SimpleNamespace(acceptance_sha=None,compact_retention_sha=None)
        with self.assertRaises(RuntimeError):M.retention(args,{}, {},{})
    def test_prior_count_and_changed_bytes_rejected(self):
        with self.assertRaises(RuntimeError):M.prior_files({}, {},M.WINDOWS[1],[])
        with tempfile.TemporaryDirectory()as directory:
            base=Path(directory);data=base/'data';data.write_text('original');expected=M.ref(data)
            receipt=base/'retention.json';owner={'fixture':True}
            receipt.write_text(json.dumps({'schema':'sg-runtime8-window-resource-retention-v1','window':M.WINDOWS[0],'owner_request':owner,'retained_file_refs':[expected,expected]}))
            q={'resource_envelope':{'per_window_resource_retention_receipt_paths':{M.WINDOWS[0]:str(receipt)}}};sha=M.ref(receipt)['sha256']
            values=M.prior_files(q,owner,M.WINDOWS[1],[sha]);self.assertEqual(len(values),2)
            data.write_text('changed')
            with self.assertRaises(RuntimeError):M.prior_files(q,owner,M.WINDOWS[1],[sha])
    def run_gate(self,free):
        with tempfile.TemporaryDirectory()as directory:
            base=Path(directory);destination=base/'gate.json';window=M.WINDOWS[2]
            q={'windows':[{'window':window,'required_free_bytes':3011171248}],'bundle_root':str(base/'bundle'),
               'resource_envelope':{'per_window_resource_gate_receipt_paths':{window:str(destination)}}}
            args=types.SimpleNamespace(window=window,phase='prebuild',prebuild_sha=None)
            old=Path.read_text
            def text(path,*a,**kw):return 'MemAvailable: 8000000 kB\n'if str(path)=='/proc/meminfo'else old(path,*a,**kw)
            with mock.patch.object(M.shutil,'disk_usage',return_value=types.SimpleNamespace(free=free)),mock.patch.object(Path,'read_text',text),contextlib.redirect_stdout(io.StringIO()):
                rc=M.gate(args,q,{'fixture':True},{})
            saved=json.loads(destination.read_text());self.assertEqual(saved['required_free_bytes'],3011171248)
            self.assertTrue(saved['full_original_required_free_gate_preserved']);self.assertTrue(saved['no_restored_raw_subtraction_or_compression_waiver'])
            return rc,saved
    def test_prebuild_pass_exact_full_requirement(self):
        rc,value=self.run_gate(3011171248);self.assertEqual(rc,0);self.assertTrue(value['gate_pass'])
    def test_failed_gate_preserved_without_threshold_waiver(self):
        rc,value=self.run_gate(3011171247);self.assertEqual(rc,42);self.assertFalse(value['gate_pass'])
    def test_preevaluate_requires_explicit_prebuild_hash(self):
        with tempfile.TemporaryDirectory()as directory:
            base=Path(directory);window=M.WINDOWS[2]
            q={'windows':[{'window':window,'required_free_bytes':3011171248}],
               'resource_envelope':{'per_window_resource_gate_receipt_paths':{window:str(base/'gate.json')}}}
            args=types.SimpleNamespace(window=window,phase='preevaluate',prebuild_sha=None)
            with self.assertRaises(RuntimeError):M.gate(args,q,{'fixture':True},{})

if __name__=='__main__':unittest.main()
