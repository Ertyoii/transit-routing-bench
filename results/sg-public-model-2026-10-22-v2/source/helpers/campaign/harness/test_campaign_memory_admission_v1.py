"""Synthetic-only fixtures. Never execute a router, constructor or search."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import run_campaign_memory_admission_v1 as admission

LIMITS = ('Limit                     Soft Limit           Hard Limit           Units\n'
          'Max resident set          unlimited            unlimited            bytes\n'
          'Max address space         unlimited            unlimited            bytes\n')


def snapshot(available=8_000_000_000):
    return {'files': {'/proc/meminfo': f'MemTotal:       16000000 kB\nMemAvailable:   {available // 1024} kB\n',
                      '/proc/self/limits': LIMITS}, 'cgroup_pairs': []}


class MemoryAdmissionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = admission.load_base()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='admission-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base.STOP = None
        self.plan_path = self.root / 'plan.json'

    def spec(self, name='one'):
        binding = admission.plan_binding()
        return {'id': name, 'argv': ['/usr/bin/true', '-rss-safety-stop', '5500000000'],
                'cwd': str(self.root), 'timeout_s': 2, 'rss_safety_stop_bytes': 5_500_000_000,
                'inputs': [binding['wrapper']['path'], binding['base_runner']['path']]}

    def owner(self, runs=None, mode='diagnostic', **extra):
        plan = {'evaluation_mode': mode, 'memory_admission': admission.plan_binding(),
                'runs': runs if runs is not None else [self.spec()], **extra}
        self.plan_path.write_text(json.dumps(plan))
        return admission.AdmissionWrapper(self.base, self.plan_path)

    def offer(self, owner, spec=None, index=0, registry=None, expected_final=None):
        spec = spec if spec is not None else owner.plan['runs'][index]
        run_dir = self.root / spec['id']
        run_dir.mkdir()
        status = {'started_utc': 'synthetic', 'plan_sha256': 'synthetic', 'completed_runs': []}
        return owner.run_one(spec, run_dir, self.root, {'GOMAXPROCS': '4', 'PATH': '/usr/bin:/bin'}, '0-3', status,
                             self.root / 'status.json', index, .1, registry, expected_final=expected_final)

    def test_exact_immutable_base_required_before_import(self):
        bad = self.root / 'wrong-base.py'
        bad.write_text('raise AssertionError("must never import unapproved source")\n')
        with patch.object(admission, 'BASE_PATH', bad):
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                admission.load_base()

    def test_default_and_explicit_smaller_envelope(self):
        spec = self.spec()
        declared = admission.envelope(spec, self.base.campaign_gate)
        self.assertEqual(declared['min_mem_available_bytes'], 6_500_000_000)
        spec['memory_admission'] = {'sampled_group_rss_stop_bytes': 1_000_000_000,
                                    'min_mem_available_bytes': 2_000_000_000}
        spec['rss_safety_stop_bytes'] = 1_000_000_000
        spec['argv'][-1] = '1000000000'
        self.assertEqual(admission.envelope(spec, self.base.campaign_gate)['min_mem_available_bytes'], 2_000_000_000)

    def test_boolean_nonpositive_and_impossible_thresholds_rejected(self):
        for value in (True, False, 0, -1, 5_500_000_000.0, '5500000000', 2**63):
            with self.subTest(value=value):
                spec = self.spec()
                spec['memory_admission'] = {'sampled_group_rss_stop_bytes': value,
                                            'min_mem_available_bytes': 6_500_000_000}
                with self.assertRaises(ValueError):
                    admission.envelope(spec, self.base.campaign_gate)
        declared = admission.envelope(self.spec(), self.base.campaign_gate)
        with self.assertRaisesRegex(ValueError, 'exceeds observed MemTotal'):
            admission.check_memory(snapshot(), dict(declared, min_mem_available_bytes=20_000_000_000))

    def test_driver_supervisor_and_reserve_conflicts(self):
        for changes in ({'rss_safety_stop_bytes': 7_000_000_000},
                        {'argv': ['/usr/bin/true', '-rss-safety-stop=7000000000']},
                        {'argv': ['/usr/bin/true', '-rss-safety-stop', '5500000000', '--rss-safety-stop=5500000000']},
                        {'memory_admission': {'sampled_group_rss_stop_bytes': 5_500_000_000,
                                              'min_mem_available_bytes': 5_500_000_001}}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    admission.envelope(dict(self.spec(), **changes), self.base.campaign_gate)

    def test_unavailable_limits_are_explicit_unknown_not_inferred(self):
        observed = snapshot()
        observed['files'].update({'/visible/memory.max': {'unavailable': 'PermissionError: denied'},
                                  '/visible/memory.current': {'unavailable': 'FileNotFoundError: absent'}})
        observed['cgroup_pairs'] = [{'version': 2, 'limit': '/visible/memory.max', 'current': '/visible/memory.current'}]
        checked = admission.check_memory(observed, admission.envelope(self.spec(), self.base.campaign_gate))
        self.assertEqual(checked['exposed_cgroup_headroom'], [])
        self.assertIn('unavailable', observed['files']['/visible/memory.max'])

    def test_malformed_and_insufficient_exposed_limits_reject(self):
        declared = admission.envelope(self.spec(), self.base.campaign_gate)
        for limit, current in (('nonsense', '1'), ('0', '0'), ('8000000000', '-1'),
                               ('8000000000', {'unavailable': 'denied'}), ('8000000000', '2000000000')):
            observed = snapshot()
            observed['files'].update({'/visible/memory.max': limit, '/visible/memory.current': current})
            observed['cgroup_pairs'] = [{'version': 2, 'limit': '/visible/memory.max', 'current': '/visible/memory.current'}]
            with self.subTest(limit=limit, current=current), self.assertRaises(ValueError):
                admission.check_memory(observed, declared)
        observed = snapshot()
        observed['files']['/proc/self/limits'] = 'Limit\nMax address space broken\n'
        with self.assertRaisesRegex(ValueError, 'malformed /proc/self/limits'):
            admission.check_memory(observed, declared)

    def test_mount_membership_mapping_does_not_escape_or_infer_hidden_ancestors(self):
        files = {'/proc/self/cgroup': '0::/jobs/one\n',
                 '/proc/self/mountinfo': '1 0 0:1 /jobs /visible rw - cgroup2 cgroup rw\n'}
        directories, notes = admission.cgroup_directories(files)
        self.assertIn(('/visible/one', 2), directories)
        self.assertIn(('/visible', 2), directories)
        self.assertNotIn(('/jobs', 2), directories)
        self.assertEqual(notes, [])
        files['/proc/self/cgroup'] = '0::/../../hidden\n'
        directories, notes = admission.cgroup_directories(files)
        self.assertNotIn(('/hidden', 2), directories)
        self.assertTrue(notes)

    def test_rejection_is_hash_bound_before_prepare_and_no_subprocess(self):
        owner = self.owner()
        owner.original_run_one = Mock(side_effect=AssertionError('base run_one must not execute'))
        with patch.object(admission, 'memory_snapshot', return_value=snapshot(4_000_000_000)), \
             patch.object(self.base, 'prepare_run') as prepare, \
             patch.object(self.base.subprocess, 'Popen') as popen:
            with self.assertRaises(admission.AdmissionRejected):
                self.offer(owner)
        owner.original_run_one.assert_not_called()
        prepare.assert_not_called()
        popen.assert_not_called()
        record = json.loads((self.root / 'one/memory-admission.json').read_text())
        digest = record.pop('record_sha256')
        self.assertEqual(digest, admission.canonical_hash(record))
        self.assertEqual(record['decision'], 'rejected')
        result = json.loads((self.root / 'one/result.json').read_text())
        self.assertFalse(result['ok'])
        self.assertFalse(result['execution_performed'])
        self.assertIsNone(result['returncode'])
        self.assertIsNone(result['launch_to_first_available_answer_ns'])
        self.assertEqual(result['outcome'], 'prelaunch_memory_admission_rejected')

    def test_admitted_path_passes_every_base_argument_and_context_unchanged(self):
        owner = self.owner()
        registry, final_context = object(), object()
        sentinel = {'id': 'one', 'ok': True, 'returncode': 0, 'timed_out': False, 'elapsed_wall_s': .01,
                    'launch_to_first_available_answer_ns': None, 'host_before': {'same': True}}
        def exact_base(*args, **kwargs):
            self.assertTrue((self.root / 'one/memory-admission.json').is_file())
            self.assertIs(args[0], owner.plan['runs'][0])
            self.assertEqual(args[3], {'GOMAXPROCS': '4', 'PATH': '/usr/bin:/bin'})
            self.assertEqual(args[4], '0-3')
            self.assertEqual(args[7:9], (0, .1))
            self.assertIs(args[9], registry)
            self.assertIs(kwargs['expected_final'], final_context)
            return copy.deepcopy(sentinel)
        owner.original_run_one = Mock(side_effect=exact_base)
        with patch.object(admission, 'memory_snapshot', return_value=snapshot()):
            result = self.offer(owner, registry=registry, expected_final=final_context)
        self.assertEqual({k: result[k] for k in sentinel}, sentinel)
        owner.original_run_one.assert_called_once()
        self.assertEqual(result['memory_admission'], admission.identity(self.root / 'one/memory-admission.json'))

    def test_actual_base_csa_guard_is_preserved_on_admitted_path(self):
        spec = self.spec()
        spec['argv'] += ['-algorithm', 'CSA']
        owner = self.owner([spec])
        with patch.object(admission, 'memory_snapshot', return_value=snapshot()), \
             patch.object(self.base.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(ValueError, 'CSA-family'):
                self.offer(owner)
        popen.assert_not_called()
        self.assertEqual(json.loads((self.root / 'one/memory-admission.json').read_text())['decision'], 'admitted')

    def test_base_loop_stops_on_rejection_even_with_continue_and_preserves_order(self):
        owner = self.owner([self.spec('prior'), self.spec('rejected'), self.spec('later')], continue_on_failure=True)
        setup = self.root / 'setup'
        setup.mkdir()
        campaign = self.root / 'campaign'
        registry = {'synthetic_registry': True}
        owner.original_run_one = Mock(return_value={'id': 'prior', 'ok': True, 'returncode': 0,
                                                    'timed_out': False, 'elapsed_wall_s': .01})
        args = SimpleNamespace(plan=str(self.plan_path), out=str(campaign), cpus='0-3', sample_s=.1,
                               continue_on_failure=True, seal=None, seal_sha256=None)
        with patch.object(self.base, 'run_one', owner.run_one), \
             patch.object(self.base, 'LEGACY_SETUP', setup), \
             patch.object(self.base.signal, 'signal'), \
             patch.object(self.base.os, 'sched_getaffinity', return_value={0, 1, 2, 3, 4}), \
             patch.object(self.base.os, 'sched_setaffinity'), \
             patch.object(self.base, 'campaign_environment', return_value={}), \
             patch.object(self.base.campaign_gate, 'load_registry', return_value=registry) as load_registry, \
             patch.object(self.base.campaign_gate, 'reject_execution_claims'), \
             patch.object(admission, 'memory_snapshot', side_effect=[snapshot(), snapshot(4_000_000_000)]), \
             patch.object(self.base.subprocess, 'Popen') as popen:
            with self.assertRaises(admission.AdmissionRejected) as raised:
                self.base.run(args)
            self.assertEqual(owner.finalize_rejection(raised.exception), 1)
        status = json.loads((campaign / 'status.json').read_text())
        self.assertEqual(status['state'], 'prelaunch_memory_admission_rejected')
        self.assertFalse(status['ok'])
        self.assertEqual([item['id'] for item in status['completed_runs']], ['prior'])
        self.assertEqual([item['id'] for item in status['rejected_offers']], ['rejected'])
        self.assertEqual([item['id'] for item in status['unstarted_offers']], ['later'])
        self.assertFalse((campaign / 'later').exists())
        owner.original_run_one.assert_called_once()
        self.assertIs(owner.original_run_one.call_args.args[9], registry)
        load_registry.assert_called_once()
        popen.assert_not_called()

    def test_missing_input_or_changed_policy_fails_before_any_offer(self):
        owner = self.owner()
        changed = copy.deepcopy(owner.plan)
        changed['memory_admission']['policy']['reserve_bytes'] = 1
        with self.assertRaisesRegex(ValueError, 'exact wrapper'):
            admission.validate_plan(changed)
        changed = copy.deepcopy(owner.plan)
        changed['runs'][0]['inputs'] = []
        with self.assertRaisesRegex(ValueError, 'Every run inputs'):
            admission.validate_plan(changed)

    def test_unchanged_base_final_seal_binds_wrapper_base_and_entire_policy(self):
        # A copied wrapper is a disposable file fixture, never an edit to real source.
        wrapper_copy = self.root / 'wrapper-fixture.py'
        wrapper_copy.write_bytes(admission.WRAPPER_PATH.read_bytes())
        dataset = self.root / 'dataset.json'
        dataset.write_text('{}\n')
        queries = self.root / 'queries.json'
        queries.write_text('[]\n')
        registry_file = self.root / 'registry.json'
        registry_file.write_text('{}\n')
        registry = {'file': admission.identity(registry_file), 'payload': {}}
        dataset_sha = admission.identity(dataset)['sha256']
        def classify(inputs, *_args, **_kwargs):
            return {'bound_inputs': inputs, 'workloads': [{'registered': True, 'classification': 'test',
                                                         'dataset_sha256': dataset_sha}]}
        with patch.object(admission, 'WRAPPER_PATH', wrapper_copy):
            spec = self.spec()
            spec['argv'] += ['-dataset', str(dataset), '-queries', str(queries)]
            owner = self.owner([spec], mode='final_evaluation')
            seal_path = self.root / 'seal.json'
            with patch.object(self.base.campaign_gate, 'load_registry', return_value=registry), \
                 patch.object(self.base.campaign_gate, 'classify', side_effect=classify), \
                 patch.object(self.base.campaign_gate, 'module_root', return_value=None), \
                 patch.object(self.base, 'source_identity', return_value={'go_source_hash_sha256': 'synthetic'}), \
                 patch.object(self.base.campaign_gate, 'source_tree_snapshot', return_value={'root': str(self.root), 'manifest_sha256': 'synthetic'}), \
                 patch.object(self.base.campaign_gate, 'qualification_binding', return_value={}), \
                 patch.object(self.base.subprocess, 'Popen') as popen:
                seal_ref = self.base.create_seal(self.plan_path, seal_path)
                frozen = json.loads(seal_path.read_text())['snapshot']
                self.assertEqual(frozen['entire_evaluation_plan']['memory_admission'], owner.binding)
                inputs = frozen['finalists_and_runs'][0]['inputs']
                self.assertIn(admission.identity(wrapper_copy), inputs)
                self.assertIn(admission.identity(admission.BASE_PATH), inputs)
                self.base.verify_seal(self.plan_path, seal_ref)
                wrapper_copy.write_bytes(wrapper_copy.read_bytes() + b'\n# changed fixture\n')
                with self.assertRaisesRegex(ValueError, 'no longer matches'):
                    self.base.verify_seal(self.plan_path, seal_ref)
                with self.assertRaisesRegex(ValueError, 'exact wrapper'):
                    admission.validate_plan(owner.plan)
            popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
