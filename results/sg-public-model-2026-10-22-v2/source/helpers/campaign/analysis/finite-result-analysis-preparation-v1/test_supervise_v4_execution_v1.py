"""Focused synthetic SOURCE fixtures. No real evaluator/model/helper inputs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('finite_sampled_guard_candidate',
    Path(__file__).with_name('supervise_v4_execution_v1.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class GuardTests(unittest.TestCase):
    def fixture(self,command='exit 0'):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);(root/'v4').mkdir()
        shell=root/'child.sh';shell.write_text('#!/bin/bash\n'+command+'\n')
        request=dict(scope=dict(mode='cap-window',out=str(root)),required_free_bytes=1500000000,
            metrics_gzip_inputs=[dict(path='v4/METRICS_BY_RUN.json',upper_bytes=10)],
            output_upper_bytes={'v4/METRICS_BY_RUN.json':10},live_guard_requirements=dict(
                metrics_budget_bytes=10,all_other_new_bytes=400000000,min_free_bytes=1000000000))
        return root,shell,request

    def run_fixture(self,fixture):
        root,shell,request=fixture
        return m.run(request,dict(path='/tmp/request',sha256='a'*64),str(shell),
            dict(path=str(shell),sha256='b'*64),sample_period=.01,grace=.05,
            read_mem=lambda:7000000000,read_free=lambda root:3000000000)

    def test_success_records_exact_command_and_preserves_evidence(self):
        fixture=self.fixture();result=self.run_fixture(fixture)
        self.assertEqual(result['returncode'],0)
        self.assertTrue(result['sampled_envelope_completed_without_observed_breach'])
        self.assertTrue((fixture[0]/'EVALUATION_INTENT.json').exists())
        self.assertFalse(result['quality_or_reader_or_output_acceptance'])

    def test_metrics_threshold_terminates_and_preserves_partial(self):
        fixture=self.fixture("printf '12345678901' > v4/METRICS_BY_RUN.json; sleep 1")
        fixture[1].write_text('#!/bin/bash\ncd '+str(fixture[0])+"\nprintf '12345678901' > v4/METRICS_BY_RUN.json; sleep 1\n")
        result=self.run_fixture(fixture)
        self.assertEqual(result['breach'],'metrics_budget_exceeded')
        self.assertEqual((fixture[0]/'v4/METRICS_BY_RUN.json').stat().st_size,11)
        self.assertFalse(result['automatic_retry_permitted'])

    def test_failed_child_is_not_accepted(self):
        result=self.run_fixture(self.fixture('exit 7'))
        self.assertEqual(result['returncode'],7)
        self.assertFalse(result['sampled_envelope_completed_without_observed_breach'])

    def test_create_only_intent_prevents_retry(self):
        fixture=self.fixture();self.run_fixture(fixture)
        with self.assertRaises(ValueError):self.run_fixture(fixture)

    def test_symlink_source_tree_is_never_traversed(self):
        fixture=self.fixture();outside=fixture[0]/'outside';outside.mkdir()
        (outside/'large').write_bytes(b'x'*100)
        (fixture[0]/'source').symlink_to(outside,target_is_directory=True)
        sample=m.window_bytes(fixture[0],'v4/METRICS_BY_RUN.json')
        self.assertEqual(sample['symlinks_not_followed'],1)
        self.assertEqual(sample['other_new_regular_bytes'],fixture[1].stat().st_size+100)

    def test_pure_threshold_and_reserve_semantics(self):
        sample=dict(metrics_bytes=10,other_new_regular_bytes=400000000,free_bytes=1000000000)
        self.assertIsNone(m.violation(sample,10,400000000,1000000000))
        sample['free_bytes']-=1
        self.assertEqual(m.violation(sample,10,400000000,1000000000),'free_disk_below_original_reserve')
