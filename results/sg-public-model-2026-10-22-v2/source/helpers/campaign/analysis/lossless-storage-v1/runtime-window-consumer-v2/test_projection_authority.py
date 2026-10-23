"""Metadata-only invocation-prefix checks; never executes consumer/phase code."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

B=Path(__file__).resolve().parent
R=B.parents[2]
COMMAND=B/'OWNER_WINDOW_PROJECT_CONTINUATION_COMMAND_V2.txt'
text=COMMAND.read_text();PROGRAM=text.split("<<'PY'\n",1)[1].split('\nPY\n',1)[0]
PREFIX=PROGRAM.split('original_source=',1)[0]
def ref(path):
    data=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}

class ProjectionAuthority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old=B.with_name('runtime-window-consumer-v1');qpath=old/'OWNER_REQUEST_ATTEMPT02.json'
        q=json.loads(qpath.read_text())
        cls.fixture={'schema':'sg-runtime8-window-projection-reader-continuation-v1','status':'INDEPENDENTLY_ACCEPTED','scope':'WINDOW_PROJECTION_ONLY',
            'windows':[w['window']for w in q['windows']],'original_owner_request':ref(qpath),'original_projection_helper':q['projection_helper'],
            'original_consumer_source':q['consumer_source'],'replacement_projection_helper':ref(R/'analysis/project_runtime8_frontier_v2.py'),
            'qualified_linear_reader':ref(B/'consumer.py'),'qualified_reader_acceptance':ref(R.parent/'campaign-v2-audit-20261021/RUNTIME_WINDOW_CONSUMER_LINEAR_READER_INDEPENDENT_QUALIFICATION_V2.json'),
            'original_storage_admission':ref(old/'STORAGE_ADMISSION.json'),'source_delta_only_array_rows':True,'reader_exact_value_equivalence':True}
    def run_prefix(self,mutate=None,window='weekday-evening-20261020',wrong_sha=False):
        value=copy.deepcopy(self.fixture)
        if mutate:mutate(value)
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'continuation.json';path.write_text(json.dumps(value))
            args=['owner-command',str(path),'0'*64 if wrong_sha else ref(path)['sha256'],window]
            with mock.patch.object(sys,'argv',args):exec(compile(PREFIX,str(COMMAND),'exec'),{})
    def test_original_contract_metadata_prefix_passes(self):self.run_prefix()
    def test_no_consumer_or_phase_in_validated_prefix(self):
        self.assertNotIn('exec(',PREFIX);self.assertNotIn('subprocess.run',PREFIX);self.assertNotIn('load_storage',PREFIX)
    def test_wrong_continuation_digest_rejected(self):
        with self.assertRaises(AssertionError):self.run_prefix(wrong_sha=True)
    def test_wrong_scope_or_status_or_schema_rejected(self):
        for key,value in [('scope','COMBINE'),('status','PASS'),('schema','other')]:
            with self.subTest(key=key),self.assertRaises(AssertionError):self.run_prefix(lambda q:q.update({key:value}))
    def test_wrong_window_or_incomplete_full_four_authority_rejected(self):
        with self.assertRaises(AssertionError):self.run_prefix(window='not-original')
        with self.assertRaises(AssertionError):self.run_prefix(lambda q:q.update(windows=q['windows'][:3]))
    def test_wrong_original_request_rejected(self):
        with self.assertRaises(AssertionError):self.run_prefix(lambda q:q['original_owner_request'].update(sha256='0'*64))
    def test_wrong_admission_binding_rejected(self):
        with self.assertRaises(AssertionError):self.run_prefix(lambda q:q['original_storage_admission'].update(sha256='0'*64))
    def test_wrong_old_helper_or_consumer_binding_rejected(self):
        for key in ('original_projection_helper','original_consumer_source'):
            with self.subTest(key=key),self.assertRaises(AssertionError):self.run_prefix(lambda q:q[key].update(sha256='0'*64))
    def test_wrong_replacement_or_reader_identity_rejected(self):
        for key in ('replacement_projection_helper','qualified_linear_reader','qualified_reader_acceptance'):
            with self.subTest(key=key),self.assertRaises(AssertionError):self.run_prefix(lambda q:q[key].update(sha256='0'*64))
    def test_missing_reader_only_equivalence_authority_rejected(self):
        for key in ('source_delta_only_array_rows','reader_exact_value_equivalence'):
            with self.subTest(key=key),self.assertRaises(AssertionError):self.run_prefix(lambda q:q.update({key:False}))

if __name__=='__main__':unittest.main()
