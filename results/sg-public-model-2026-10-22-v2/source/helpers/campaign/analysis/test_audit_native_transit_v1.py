#!/usr/bin/env python3
"""Synthetic-only qualification. Never run across a measurement barrier."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).with_name('audit_native_transit_v1.py')
SPEC = importlib.util.spec_from_file_location('native_transit_audit_tests', PATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def fixture():
    stops = [{'id': x, 'accessible': 'yes'} for x in ('a', 'b', 'c', 'd', 'e', 'f', 'z')]
    walks = [{'id': ref, 'from': a, 'to': b, 'duration': duration, 'accessible': 'yes'}
             for ref, a, b, duration in [('ab', 'a', 'b', 2), ('bc', 'b', 'c', 3), ('de', 'd', 'e', 2), ('fz', 'f', 'z', 2), ('az', 'a', 'z', 6)]]
    rides = [{'id': ref, 'trip_id': trip, 'from': a, 'to': b, 'departure': dep, 'arrival': arr,
              'sequence': 0, 'pickup': True, 'dropoff': True}
             for ref, trip, a, b, dep, arr in [('r1', 't1', 'c', 'd', 20, 25), ('r2', 't2', 'e', 'f', 30, 35)]]
    dataset = {'schema_version': '0.2', 'id': 'synthetic', 'time_zone': 'UTC', 'service_date': '2026-10-20',
               'stops': stops, 'footpaths': walks, 'trips': [{'id': t, 'accessible': 'yes'} for t in ('t1', 't2')], 'connections': rides}
    q = {'id': 'q', 'origin': 'a', 'destination': 'z', 'departure': 10, 'latest_arrival': 40,
         'transfer_buffer': 0, 'max_walk_seconds': 20, 'max_boardings': 2, 'max_legs': 20,
         'accessible_only': False, 'walking_limits': {'access_seconds': 5, 'transfer_seconds': 2, 'egress_seconds': 2, 'direct_seconds': 6}}
    journey = {'legs': [{'kind': 'walk', 'ref': 'ab', 'departure': 15, 'arrival': 17},
                        {'kind': 'walk', 'ref': 'bc', 'departure': 17, 'arrival': 20},
                        {'kind': 'ride', 'ref': 'r1', 'departure': 20, 'arrival': 25},
                        {'kind': 'walk', 'ref': 'de', 'departure': 25, 'arrival': 27},
                        {'kind': 'ride', 'ref': 'r2', 'departure': 30, 'arrival': 35},
                        {'kind': 'walk', 'ref': 'fz', 'departure': 35, 'arrival': 37}]}
    return m.legacy.Checker(dataset), {'base': q, 'ready_window_end_inclusive': 20}, journey


def profile_row(checker, profile, journey, bound=15, direct=None):
    journey = m.independent_reanchor(checker, journey, bound)
    checked = checker.check(m.point_query(profile['base'], bound), journey)
    raw = {'latest_ready': bound, 'arrival': checked['metrics']['arrival'], 'boardings': checked['metrics']['boardings'], 'journey': journey}
    final = {'latest_ready': bound, 'validated': {k: checked[k] for k in ('journey', 'identity', 'metrics')}}
    row = {'query': copy.deepcopy(profile), 'raw': {'query': copy.deepcopy(profile), 'transit_points': [raw], 'complete': True},
           'final_points': [final], 'complete': True}
    if direct is not None:
        row['raw']['direct_walking'] = direct
        row['final_direct'] = checker.check(profile['base'], direct['journey_at_window_start'])
    row['every_integer_ready_time'] = m.materializations(checker, profile, [raw], direct)[0]
    return row


class NativeTransitAuditTests(unittest.TestCase):
    def test_initial_contiguous_walk_sum_not_only_first_leg(self):
        checker, profile, journey = fixture()
        self.assertEqual(m.initial_walk_duration(checker, journey), 5)
        self.assertEqual(m.independently_eligible_end(checker, profile, journey), 15)
        result = m.audit_profile(checker, profile_row(checker, profile, journey))
        self.assertEqual(result['readiness_observations'], 11)
        self.assertEqual(result['physical_extension_counterexamples'], [])

    def test_earlier_latest_ready_valid_but_extension_can_falsify_grid(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey, 12)
        result = m.audit_profile(checker, row)
        self.assertEqual(result['conservative_point_boundary_count'], 1)
        self.assertEqual([x['ready'] for x in result['physical_extension_counterexamples']], [13, 14, 15])

    def test_earlier_boundary_can_be_redundant_without_counterexample(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey, 12)
        later = profile_row(checker, profile, journey, 15)
        row['raw']['transit_points'].extend(later['raw']['transit_points'])
        row['final_points'].extend(later['final_points'])
        row['every_integer_ready_time'] = later['every_integer_ready_time']
        self.assertEqual(m.audit_profile(checker, row)['physical_extension_counterexamples'], [])

    def test_too_late_latest_ready_is_invalid(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['raw']['transit_points'][0]['latest_ready'] = 16
        row['final_points'][0]['latest_ready'] = 16
        with self.assertRaises(ValueError):
            m.audit_profile(checker, row)

    def test_reanchor_preserves_every_middle_ride_and_egress_event(self):
        checker, profile, journey = fixture()
        shifted = m.independent_reanchor(checker, journey, 10)
        self.assertEqual(shifted['legs'][2:], journey['legs'][2:])
        self.assertEqual(shifted['legs'][0]['departure'], 10)
        self.assertEqual(shifted['legs'][1]['arrival'], 15)
        checker.check(profile['base'], shifted)
        shifted['legs'][3]['departure'] -= 5
        shifted['legs'][3]['arrival'] -= 5
        with self.assertRaises(ValueError):
            checker.check(profile['base'], shifted)

    def test_wrong_ride_event_rejected(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['raw']['transit_points'][0]['journey']['legs'][2]['departure'] += 1
        with self.assertRaises(ValueError):
            m.audit_profile(checker, row)

    def test_missing_readiness_and_wrong_boarding_cap_rejected(self):
        checker, profile, journey = fixture()
        for mutation in ('missing', 'cap'):
            row = profile_row(checker, profile, journey)
            if mutation == 'missing':
                row['every_integer_ready_time'].pop()
            else:
                row['every_integer_ready_time'][0]['arrival_under_boarding_caps'][1] = 37
            with self.assertRaises(ValueError):
                m.audit_profile(checker, row)

    def test_wrong_query_or_complete_rejected(self):
        checker, profile, journey = fixture()
        for mutation in ('query', 'complete'):
            row = profile_row(checker, profile, journey)
            if mutation == 'query':
                row['raw']['query']['base']['latest_arrival'] += 1
            else:
                row['raw']['complete'] = False
            with self.assertRaises(ValueError):
                m.audit_profile(checker, row)

    def test_direct_affine_fixed_horizon_expiry_and_duration(self):
        checker, profile, _ = fixture()
        profile['base']['latest_arrival'] = 18
        profile['ready_window_end_inclusive'] = 18
        direct = {'duration': 6, 'journey_at_window_start': {'legs': [{'kind': 'walk', 'ref': 'az', 'departure': 10, 'arrival': 16}]}}
        grid = m.materializations(checker, profile, [], direct)[0]
        self.assertEqual(grid[2]['arrival_under_boarding_caps'], [18, 18, 18])
        self.assertEqual(grid[3]['arrival_under_boarding_caps'], [m.INFINITY] * 3)
        bad = copy.deepcopy(direct); bad['duration'] = 5
        with self.assertRaisesRegex(ValueError, 'duration'):
            m.materializations(checker, profile, [], bad)
        bad = copy.deepcopy(direct); bad['journey_at_window_start']['legs'] = []
        with self.assertRaises(ValueError):
            m.materializations(checker, profile, [], bad)

    def test_raw_final_point_metadata_and_journey_claim_checked(self):
        checker, profile, journey = fixture()
        for mutation in ('arrival', 'boardings', 'metrics', 'identity'):
            row = profile_row(checker, profile, journey)
            if mutation in ('arrival', 'boardings'):
                row['raw']['transit_points'][0][mutation] += 1
            elif mutation == 'metrics':
                row['final_points'][0]['validated']['metrics']['arrival'] += 1
            else:
                row['final_points'][0]['validated']['identity'] = '[]'
            with self.assertRaises(ValueError):
                m.audit_profile(checker, row)

    def test_bool_boardings_is_not_integer_one(self):
        checker, profile, journey = fixture()
        profile['base']['destination'] = 'd'
        journey['legs'] = journey['legs'][:3]
        row = profile_row(checker, profile, journey)
        row['raw']['transit_points'][0]['boardings'] = True
        with self.assertRaisesRegex(ValueError, 'strict integers'):
            m.audit_profile(checker, row)

    def test_donation_rechecks_base_not_late_start_metrics_and_preserves_partial(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['complete'] = False
        row['error'] = 'synthetic incomplete'
        donations, failures = m.base_donations(checker, row, 'profilebench')
        self.assertFalse(failures)
        checked, provenance = donations['final'][0]
        self.assertEqual(checked['duration_seconds'], 27)
        self.assertEqual(checked['journey']['legs'][0]['departure'], 10)
        self.assertEqual(checked['journey']['legs'][2:], journey['legs'][2:])
        self.assertEqual(provenance['source_ready'], 15)
        self.assertEqual(provenance['transformed_initial_leg_count'], 2)
        self.assertEqual(provenance['source_point_index'], 0)
        self.assertNotIn('complete', checked)

    def test_donation_wrong_raw_query_fails_closed(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['raw']['query']['base']['id'] = 'somebody-else'
        with self.assertRaises(ValueError):
            m.base_donations(checker, row, 'profilebench')

    def test_malformed_source_occurrence_does_not_erase_valid_siblings(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        good = copy.deepcopy(row['raw']['transit_points'][0])
        row['raw']['transit_points'] += [{}, good]
        donations, failures = m.base_donations(checker, row, 'profilebench')
        self.assertEqual(len(donations['raw']), 2)
        self.assertEqual([x[1]['source_point_index'] for x in donations['raw']], [0, 2])
        self.assertEqual(len(donations['final']), 1)
        self.assertEqual(len(failures), 1)

    def test_malformed_stage_container_does_not_erase_valid_other_stage(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['raw']['transit_points'] = None
        donations, failures = m.base_donations(checker, row, 'profilebench')
        self.assertEqual(len(donations['raw']), 0)
        self.assertEqual(len(donations['final']), 1)
        self.assertEqual(len(failures), 1)

    def test_malformed_initial_source_anchor_is_not_silently_repaired(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['final_points'] = copy.deepcopy(row['final_points'])
        row['raw']['transit_points'][0]['journey']['legs'][0]['departure'] += 1
        donations, failures = m.base_donations(checker, row, 'profilebench')
        self.assertEqual(len(donations['raw']), 0)
        self.assertEqual(len(donations['final']), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn('source initial walking prefix', failures[0]['error'])

    def test_full_recipient_caps_are_rechecked(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['query']['base']['walking_limits']['access_seconds'] = 4
        row['raw']['query'] = copy.deepcopy(row['query'])
        donations, failures = m.base_donations(checker, row, 'profilebench')
        self.assertEqual(donations, {'raw': [], 'final': []})
        self.assertEqual(len(failures), 2)

    def test_tad_single_witness_not_frontier(self):
        checker, profile, journey = fixture()
        journey = m.independent_reanchor(checker, journey, 10)
        row = {'query': profile['base'], 'raw': [journey, journey], 'final': []}
        with self.assertRaisesRegex(ValueError, 'one earliest'):
            m.audit_point(checker, row, 'tadbench')

    def test_empty_unknown_and_beating_complete_scalar_are_not_quality_wins(self):
        checker, profile, journey = fixture()
        checked = checker.check(profile['base'], m.independent_reanchor(checker, journey, 10))
        weight = {'transfer_seconds': 0, 'extra_walk_weight': 0}
        unknown = {'complete': False, 'found': True, 'weight': weight}
        empty = {'complete': True, 'found': False, 'weight': weight}
        complete = {'complete': True, 'found': True, 'weight': weight, 'score_seconds': 28}
        self.assertEqual(m.comparison([checked], unknown)['status'], 'unknown_original_scalar_slot')
        self.assertEqual(m.comparison([], empty)['status'], 'agree_complete_empty')
        self.assertTrue(m.comparison([checked], empty)['status'].startswith('contradiction'))
        self.assertTrue(m.comparison([checked], complete)['status'].startswith('contradiction'))

    def test_exact_query_byte_slices_bind_original_whitespace(self):
        workload = {'items': [{'query': {'id': 'q', 'origin': 'a', 'departure': 10}, 'stratum': 'test'}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'q.json'
            path.write_text(json.dumps(workload, indent=3))
            fragment = m.query_fragments(path, workload)['q']
            self.assertEqual(json.loads(fragment), workload['items'][0]['query'])
            self.assertIn('\n', fragment)
            self.assertNotEqual(fragment, m.canonical(workload['items'][0]['query']))

    def test_wrong_pass_digest_and_wrong_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp)
            payload = {'algorithm': 'tad', 'repetition': 0, 'warmup': False, 'records': []}
            path = artifact / 'p.json'; path.write_text(json.dumps(payload))
            summary = {'passes': [{'algorithm': 'tad', 'repetition': 0, 'warmup': False, 'file': path.name, 'sha256': '0' * 64}]}
            with self.assertRaisesRegex(ValueError, 'digest'):
                m.bound_ordinary_pass(summary, artifact, 'tad', {})
        prov = {key: 'a' * 64 for key in ('build_source_sha256', 'runtime_tree_sha256', 'routing_source_sha256', 'executable_sha256')}
        prov.update(source_binding='embedded_build_source', runtime_matches_build=True)
        summary = {'dataset_sha256': 'd', 'workload_sha256': 'w', 'provenance': prov}
        command = {'binary': {'sha256': 'a' * 64}}
        role = {'go_source_hash_sha256': 'b' * 64, 'routing_file_list_sha256': 'a' * 64}
        with self.assertRaisesRegex(ValueError, 'binding'):
            m.inv.validate_manifest(summary, command, role, 'tadbench', 'tad', 'd', 'w')

    def test_bad_grid_is_row_failure_not_whole_pass_binding_failure(self):
        checker, profile, journey = fixture()
        row = profile_row(checker, profile, journey)
        row['stratum'] = 'synthetic'
        row['every_integer_ready_time'].pop()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp)
            payload = {'algorithm': 'range_raptor', 'repetition': 0, 'warmup': False, 'records': [row]}
            path = artifact / 'p.json'; path.write_text(json.dumps(payload))
            descriptor = {'algorithm': 'range_raptor', 'repetition': 0, 'warmup': False, 'file': path.name, 'sha256': m.digest(path)}
            selected, discarded = m.bound_ordinary_pass({'passes': [descriptor]}, artifact, 'range_raptor', {})
            self.assertIsNotNone(selected)
            self.assertFalse(discarded)
            rows, indices, failures = m.bind_offered_rows(selected[1], {'q': {'query': profile, 'stratum': 'synthetic'}})
            self.assertEqual(indices['q'], 0)
            self.assertFalse(failures)
            with self.assertRaises(ValueError):
                m.audit_profile(checker, rows['q'])
            donations, failures = m.base_donations(checker, rows['q'], 'profilebench')
            self.assertEqual(len(donations['raw']), 1)
            self.assertFalse(failures)

    def test_duplicate_and_wrong_full_query_leave_unrelated_rows_intact(self):
        _, profile, _ = fixture()
        a = {'query': profile, 'stratum': 'synthetic'}
        b = copy.deepcopy(a); b['query']['base']['id'] = 'other'
        wrong = copy.deepcopy(a); wrong['query']['base']['max_walk_seconds'] -= 1
        expected = {'q': a, 'other': b}
        rows, indices, failures = m.bind_offered_rows({'records': [a, wrong, copy.deepcopy(a), b]}, expected)
        self.assertEqual(set(rows), {'other'})
        self.assertEqual(indices, {'other': 3})
        self.assertEqual(len(failures), 2)

    def test_malformed_same_id_duplicate_invalidates_both_orders(self):
        _, profile, _ = fixture()
        good = {'query': profile, 'stratum': 'synthetic'}
        bad = copy.deepcopy(good); bad['query']['base']['max_boardings'] = 0
        unrelated = copy.deepcopy(good); unrelated['query']['base']['id'] = 'other'
        expected = {'q': good, 'other': unrelated}
        for pair in ([good, bad], [bad, good]):
            rows, indices, failures = m.bind_offered_rows({'records': [*pair, unrelated]}, expected)
            self.assertEqual(set(rows), {'other'})
            self.assertEqual(indices, {'other': 2})
            self.assertTrue(failures)


if __name__ == '__main__':
    unittest.main()
