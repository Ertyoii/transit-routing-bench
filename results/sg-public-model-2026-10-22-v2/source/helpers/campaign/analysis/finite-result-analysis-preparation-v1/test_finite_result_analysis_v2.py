"""Synthetic SOURCE fixtures only. No operation, lock, helper or real input."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('finite_budget_candidate_v2',
    Path(__file__).absolute().with_name('finite_result_analysis_v2.py'))
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class NumericAuthorityTests(unittest.TestCase):
    def fixture(self, mode='cap-window'):
        window = candidate.core.WINDOWS[0]
        outputs = ({'v4-output/'+name: 17 for name in candidate.V4_FILES} if mode == 'cap-window'
                   else {'NATIVE_ROWS.jsonl': 100, 'REPORT.json': 20})
        if mode == 'cap-window': outputs['REPORT.json'] = 20
        metrics = ([{'path': 'v4-output/METRICS_BY_RUN.json', 'upper_bytes': 17}]
                   if mode == 'cap-window' else [])
        gzip = 17 + 17//100 + 1048576 if metrics else 0
        request = dict(schema='finite-analysis-numeric-operation-request-v2',
            status='SOURCE_DERIVED_BOUNDS_FROZEN',
            scope=dict(mode=mode, window=window, out='/tmp/new-output'),
            original_reserve_bytes=1000000000,
            source_derivation=[dict(path='/tmp/accepted-source', sha256='a'*64)],
            output_upper_bytes=outputs, projection_upper_bytes={'projection.json': 11},
            planned_v4_output_prefix='v4-output' if mode == 'cap-window' else None,
            metrics_gzip_inputs=metrics, gzip_workspace_upper_bytes=gzip,
            original_path_restore_peak_bytes=13, temporary_and_failed_partial_peak_bytes=19,
            adopted_free_space_gates=[],
            required_free_bytes=1000000000 + sum(outputs.values()) + 11 + 13 + 19 + gzip)
        return mode, window, request, list(outputs)

    def check(self, fixture):
        mode, window, request, names = fixture
        return candidate.validate_numeric_request(mode, window, '/tmp/new-output', request, names)

    def test_exact_cap_eleven_files_and_gzip(self):
        got = self.check(self.fixture())
        self.assertEqual(got['gzip_workspace_upper_bytes'], 1048593)
        self.assertLess(got['required_free_bytes'], 3100000000)
        self.assertFalse(got['preliminary_3_1GB_is_adopted_authority'])

    def test_typed_native_metadata_has_no_v4_or_gzip_floor(self):
        got = self.check(self.fixture('native-inventory'))
        self.assertEqual(got['gzip_workspace_upper_bytes'], 0)
        self.assertEqual(got['required_free_bytes'], 1000000163)

    def test_feasibility_typed_budget(self):
        self.check(self.fixture('native-feasibility-window'))

    def test_actual_adopted_gate_is_preserved_not_waived(self):
        fixture = self.fixture()
        fixture[2]['adopted_free_space_gates'] = [dict(required_free_bytes=3200000000,
            receipt=dict(path='/tmp/adopted', sha256='b'*64))]
        fixture[2]['required_free_bytes'] = 3200000000
        self.assertEqual(self.check(fixture)['required_free_bytes'], 3200000000)

    def test_unknown_or_boolean_term_fails_closed(self):
        for value in (None, True, -1, 1.5):
            fixture = self.fixture()
            fixture[2]['original_path_restore_peak_bytes'] = value
            with self.assertRaises(ValueError): self.check(fixture)

    def test_cannot_reduce_original_reserve(self):
        fixture = self.fixture()
        fixture[2]['original_reserve_bytes'] = 999999999
        with self.assertRaises(ValueError): self.check(fixture)

    def test_exact_gzip_rule_not_rounding_guess(self):
        fixture = self.fixture()
        fixture[2]['gzip_workspace_upper_bytes'] += 1
        with self.assertRaises(ValueError): self.check(fixture)

    def test_scope_out_window_mode_fail(self):
        for key, value in (('out', '/tmp/other'), ('window', candidate.core.WINDOWS[1]),
                           ('mode', 'native-inventory')):
            fixture = self.fixture()
            fixture[2]['scope'][key] = value
            with self.assertRaises(ValueError): self.check(fixture)

    def test_missing_qualified_output_is_not_silent_reduction(self):
        fixture = self.fixture()
        fixture[2]['output_upper_bytes'].pop('v4-output/QUALITY_ROWS.jsonl')
        with self.assertRaises(ValueError): self.check(fixture)

    def test_extra_unreviewed_output_or_projection_overlap_fails(self):
        fixture = self.fixture()
        fixture[2]['output_upper_bytes']['EXTRA.json'] = 5
        with self.assertRaises(ValueError): self.check(fixture)
        fixture = self.fixture()
        fixture[2]['projection_upper_bytes']['REPORT.json'] = 5
        with self.assertRaises(ValueError): self.check(fixture)

    def test_unbound_source_and_unbound_adopted_gate_fail(self):
        fixture = self.fixture()
        fixture[2]['source_derivation'] = []
        with self.assertRaises(ValueError): self.check(fixture)
        fixture = self.fixture()
        fixture[2]['adopted_free_space_gates'] = [dict(required_free_bytes=2000000000,
                                                     receipt=dict(path='/tmp/bad', sha256='bad'))]
        with self.assertRaises(ValueError): self.check(fixture)

    def test_native_cannot_waive_applicable_v4_output(self):
        fixture = self.fixture('native-inventory')
        fixture[2]['output_upper_bytes']['METRICS_BY_RUN.json'] = 3
        fixture[3].append('METRICS_BY_RUN.json')
        with self.assertRaises(ValueError): self.check(fixture)

    def test_no_total_from_unknown_file_or_unknown_gate_inventory(self):
        fixture = self.fixture()
        fixture[2]['output_upper_bytes']['REPORT.json'] = None
        with self.assertRaises(ValueError): self.check(fixture)
        fixture = self.fixture()
        fixture[2]['adopted_free_space_gates'] = None
        with self.assertRaises(ValueError): self.check(fixture)

    def test_original_sources_are_inert_on_import(self):
        self.assertNotIn('finite_existing_native_inventory', __import__('sys').modules)
        self.assertNotIn('finite_existing_native_audit', __import__('sys').modules)
        self.assertNotIn('finite_existing_delivery', __import__('sys').modules)


if __name__ == '__main__':
    unittest.main()
