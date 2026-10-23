"""Focused synthetic test SOURCE. NOT EXECUTED during native measurement.

Imports only the new inert candidate when later explicitly run in a quiet slot.
No original model, native workload, pass, archive or evaluator is a fixture.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    'finite_result_candidate_tested', Path(__file__).with_name('finite_result_analysis_v1.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def make_plan(variants=24, algorithms=11):
    runs = []
    for block in (0, 1):
        for window in m.WINDOWS:
            for index in range(variants):
                variant = 'finite20-lean-k3' if index == 0 and variants == 12 else 'variant-%02d' % index
                runs.append({'id': 'b%d-%s-%s' % (block, window, variant),
                    'block': block, 'window': window, 'variant_id': variant,
                    'argv': ['/synthetic/familybench', '-algorithm', 'algorithm-%02d' % (index % algorithms),
                             '-dataset', '/synthetic/model.json', '-queries', '/synthetic/work.json',
                             '-preference-scenarios', '/synthetic/config.json',
                             '-quality', '-display-k', '-1', '-out-dir', '{run_dir}/artifact'],
                    'env': {'GOGC': '100'}, 'cwd': '/synthetic/source'})
    return {'evaluation_mode': 'diagnostic', 'purpose': 'synthetic only',
            'workload_registry': {'path': 'registry.json', 'sha256': 'a' * 64, 'bytes': 3},
            'runs': runs}


class FakeLineage:
    def group(self, algorithm, family=None):
        expected = 'family-' + algorithm
        if family != expected:
            raise ValueError('family differs')
        return ('lineage-' + algorithm,)


def seed_fixture(*, excluded_unique=False, one_unknown=False):
    plan = make_plan()
    rows = []
    for run in plan['runs']:
        algorithm = m.flag(run['argv'], '-algorithm')
        for number in range(60):
            complete = not (one_unknown and not rows)
            rows.append({'run': run['id'], 'variant_id': run['variant_id'],
                'window': run['window'], 'algorithm': algorithm, 'family': 'family-' + algorithm,
                'dataset_sha256': 'model-' + run['window'],
                'query': {'id': run['window'] + ':q%d' % number, 'departure': 1, 'latest_arrival': 2},
                'stratum': 'synthetic', 'native_complete': complete,
                'independent_complete': complete,
                'independent_status': 'complete' if complete else 'unknown'})
    window = m.WINDOWS[0]
    donor0 = 'b0-%s-variant-00' % window
    donor11 = 'b0-%s-variant-11' % window  # same original algorithm as variant00
    members = [{'dataset_sha256': 'model-' + window, 'query_id': window + ':q0',
        'identity': '[{"kind":"walk","ref":"walk0"}]',
        'feature': {'identity': 'replay-walk0', 'metrics': {'walking_seconds': 1},
                    'duration_seconds': 1, 'route_stop_walk_pattern': 'walk0'},
        'journey': {'legs': [{'kind': 'walk', 'ref': 'walk0'}]},
        'donor_runs': [donor0, donor11], 'donor_families': ['family-algorithm-00']}]
    if excluded_unique:
        extra = copy.deepcopy(members[0])
        extra.update(identity='unique-excluded', donor_runs=['b0-%s-variant-12' % window],
                     donor_families=['family-algorithm-01'])
        members.append(extra)
    manifest = {'schema': 'sg-selector-replay-manifest-v1', 'candidate_rows': 11520,
                'authoritative_errors': 0, 'authoritative_native_counterexamples': 0}
    ids = m.stable_variant_ids(plan, ['variant-%02d' % i for i in range(11)])
    return plan, ids, manifest, rows, members


class ViewTests(unittest.TestCase):
    def test_exact_stable_view_and_original_unchanged(self):
        parent = make_plan(); before = copy.deepcopy(parent)
        ids = [run['id'] for run in parent['runs'] if run['window'] == m.WINDOWS[0]][:3]
        derived = m.derive_window_plan(parent, ids, '/synthetic/original',
                                       '/synthetic/original/registry.json', 'a' * 64)
        self.assertEqual(parent, before)
        self.assertEqual(derived['runs'], [run for run in parent['runs'] if run['id'] in ids])
        self.assertEqual(derived['workload_registry']['path'], '/synthetic/original/registry.json')
        m.check_view_equivalence(parent, derived, ids, '/synthetic/original',
                                 '/synthetic/original/registry.json', 'a' * 64)

    def test_reordered_duplicate_and_unknown_ids_fail(self):
        parent = make_plan(); ids = [run['id'] for run in parent['runs']][:2]
        for selection in (ids[::-1], ids + ids[:1], ['not-offered']):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                m.derive_window_plan(parent, selection, '/synthetic/original',
                                     '/synthetic/original/registry.json', 'a' * 64)

    def test_mutated_environment_or_extra_top_level_fails(self):
        parent = make_plan(); ids = [parent['runs'][0]['id']]
        for change in ('env', 'extra'):
            derived = m.derive_window_plan(parent, ids, '/synthetic/original',
                                           '/synthetic/registry.json', 'a' * 64)
            if change == 'env':
                derived['runs'][0]['env']['GOGC'] = '200'
            else:
                derived['unapproved_success'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                m.check_view_equivalence(parent, derived, ids, '/synthetic/original',
                                         '/synthetic/registry.json', 'a' * 64)

    def test_frozen_two_block_controls_and_all_eleven_contracts(self):
        plan, ids, manifest, rows, members = seed_fixture(one_unknown=True)
        result, ledger = m.seed_union_check(plan, ids, manifest, rows, members, FakeLineage())
        self.assertFalse(result['differences'])
        self.assertEqual(result['retained_control_processes'], 88)
        self.assertEqual(len(ledger), 11520)
        self.assertEqual(result['original_unknown_offers'], 1)
        self.assertEqual(len(result['provenance_map'][0]['original_donor_runs']), 2)
        self.assertEqual(len(result['provenance_map'][0]['retained_actual_control_runs']), 1)

    def test_missing_unique_raw_or_final_donation_blocks(self):
        plan, ids, manifest, rows, members = seed_fixture(excluded_unique=True)
        result, ledger = m.seed_union_check(plan, ids, manifest, rows, members, FakeLineage())
        self.assertEqual(result['status'], 'BLOCKED_DONOR_UNION_DISCREPANCY')
        self.assertEqual(len(ledger), 11520)
        self.assertEqual(result['differences'][0]['fields'], ['missing_identity'])

    def test_feature_family_and_lineage_differences_are_not_equal_cost_parity(self):
        original = {('m', 'q', 'id'): {'feature': {'duration_seconds': 1},
                    'journey': {'legs': []}, 'families': ['one'], 'lineages': [('a',)]}}
        for field, value in (('feature', {'duration_seconds': 2}),
                             ('families', ['two']), ('lineages', [('b',)]),
                             ('journey', {'legs': [{'ref': 'changed'}]})):
            retained = copy.deepcopy(original); retained[('m', 'q', 'id')][field] = value
            result = m.compare_donor_unions(original, retained)
            self.assertEqual(result['differences'][0]['fields'], [field])

    def test_missing_offer_duplicate_offer_and_same_family_contract_drop_fail(self):
        plan, ids, manifest, rows, members = seed_fixture()
        for altered_rows in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                m.seed_union_check(plan, ids, manifest, altered_rows, members, FakeLineage())
        dropped = [rid for rid in ids if 'variant-10' not in rid]
        with self.assertRaises(ValueError):
            m.seed_union_check(plan, dropped, manifest, rows, members, FakeLineage())


class SourceBTests(unittest.TestCase):
    def fixture(self):
        plan = make_plan(variants=12, algorithms=1)
        ids = m.stable_variant_ids(plan, ['finite20-lean-k3'])
        checks = []
        for baseline in (run for run in plan['runs'] if run['id'] in ids):
            for candidate in plan['runs']:
                if (candidate['window'], candidate['block']) != (baseline['window'], baseline['block']) or candidate == baseline:
                    continue
                checks.append({'baseline': baseline['id'], 'candidate': candidate['id'],
                    'window': baseline['window'], 'block': baseline['block'],
                    'status': 'exact', 'offered': 60, 'differences': [],
                    'incomplete_query_ids': [], 'incomplete_outcome_differences': []})
        coverage = dict(runs=96, offered=5760, completed=5760, validation_errors=0,
                        native_counterexamples=0, projection_native_parity={'exact': 88})
        return plan, coverage, {'checks': checks}, ids

    def test_accepted_exact88_covers_all_original96(self):
        m.check_source_B_reduction(*self.fixture())

    def test_incomplete_pair_and_wrong_window_cannot_justify_reduction(self):
        for mutation in ('status', 'window', 'duplicate'):
            plan, coverage, parity, ids = self.fixture()
            if mutation == 'status':
                parity['checks'][0]['status'] = 'unknown'
            elif mutation == 'window':
                parity['checks'][0]['window'] = m.WINDOWS[3]
            else:
                parity['checks'][1] = copy.deepcopy(parity['checks'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                m.check_source_B_reduction(plan, coverage, parity, ids)


class FileAndGateTests(unittest.TestCase):
    def test_bound_json_and_no_changed_file_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic.json'; path.write_text('{"answer":1}\n')
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            io = m.BoundIO()
            self.assertEqual(io.read_ref({'path': str(path), 'sha256': expected}), {'answer': 1})
            path.write_text('{"answer":2}\n')
            with self.assertRaises(ValueError):
                io.read_path(path)

    def test_duplicate_json_key_nonfinite_and_relative_path_fail(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(ValueError):
                m.strict_json(text)
        for path in ('relative/file.json', '/synthetic/../escape'):
            with self.assertRaises(ValueError):
                m.absolute(path)

    def fake_gate(self, *, expired=False, source_changed=False):
        args = SimpleNamespace(quiet_window_open=True, mode='cap-window',
            binding='/synthetic/binding.json', binding_sha256='a' * 64,
            out='/synthetic/output')
        binding = {'schema': 'finite-analysis-input-binding-v1', 'status': 'INDEPENDENTLY_ACCEPTED',
            'modes': ['cap-window'], 'out': args.out, 'source_qualification': {'key': 'qualification'},
            'owner_release': {'key': 'release'}}
        qualification = {'schema': 'finite-analysis-source-qualification-v1',
            'status': 'INDEPENDENTLY_ACCEPTED', 'modes': ['cap-window'],
            'source_sha256': 'b' * 64 if source_changed else 'c' * 64}
        expires = datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)
        release = {'schema': 'finite-analysis-owner-release-v1', 'status': 'OWNER_RELEASED',
                   'modes': ['cap-window'], 'expires_utc': expires.isoformat()}
        io = SimpleNamespace(read_ref=lambda ref: {'qualification': qualification, 'release': release}.get(ref.get('key'), binding),
                             file_ref=lambda path: {'sha256': 'c' * 64})
        return args, io

    def test_explicit_current_release_and_source_binding_required(self):
        args, io = self.fake_gate()
        self.assertEqual(m.gate_operation(args, io)[0]['out'], args.out)
        for changes in ({'expired': True}, {'source_changed': True}):
            args, io = self.fake_gate(**changes)
            with self.assertRaises(ValueError):
                m.gate_operation(args, io)
        args, io = self.fake_gate(); args.quiet_window_open = False
        with self.assertRaises(ValueError):
            m.gate_operation(args, io)

    def test_resource_floor_and_current_cgroup_headroom_fail_before_limits(self):
        admission = {'schema': 'finite-analysis-resource-admission-v1',
            'status': 'INDEPENDENTLY_ACCEPTED', 'mode': 'cap-window',
            'required_free_bytes': 3_100_000_000, 'min_mem_available_bytes': 100,
            'min_cgroup_headroom_bytes': 100, 'address_space_bytes': 4 * 1024**3,
            'cpu_seconds': 300, 'wall_seconds': 600}
        io = SimpleNamespace(read_ref=lambda ref: admission)
        binding = {'resource_admission': {}}
        snapshot = {'disk_free_bytes': 3_200_000_000, 'mem_available_bytes': 200,
                    'exposed_cgroup_headroom': [{'headroom_bytes': 50}]}
        with mock.patch.object(m, 'resource_snapshot', return_value=snapshot), \
             mock.patch.object(m.resource, 'setrlimit') as limits, \
             mock.patch.object(m.signal, 'alarm'):
            with self.assertRaises(ValueError):
                m.resource_gate('cap-window', binding, io)
            limits.assert_not_called()
            admission['required_free_bytes'] = 3_000_000_000
            with self.assertRaises(ValueError):
                m.resource_gate('cap-window', binding, io)
            limits.assert_not_called()


if __name__ == '__main__':
    unittest.main()
