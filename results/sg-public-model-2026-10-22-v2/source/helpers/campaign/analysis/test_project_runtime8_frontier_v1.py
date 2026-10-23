#!/usr/bin/env python3
"""STATIC focused fixtures; run only in an explicit quiet analysis slot."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

P = Path(__file__).with_name('project_runtime8_frontier_v1.py')
SPEC = importlib.util.spec_from_file_location('runtime8_projection_fixture', P)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class RuntimeProjectionTests(unittest.TestCase):
    def test_actual_quantiles_and_null_not_zero(self):
        self.assertEqual(M.distribution([1]*19+[100])['p95'], 1)
        self.assertEqual(M.distribution([1]*19+[100])['p99'], 100)
        self.assertIsNone(M.distribution([])['p95'])
        self.assertEqual(M.distribution([0])['p95'], 0)
        self.assertIsNone(M.ratio(0, 0))
        for value in (None, True, -1, 1.5):
            with self.assertRaises((ValueError, TypeError)):
                M.distribution([value])

    def test_full_cartesian_and_refusal_denominator(self):
        slots = M.expected_slots()
        self.assertEqual(len(slots), 672)
        self.assertEqual(len(M.PRODUCTS), 14)
        refused = {rid for rid, s in slots.items() if s['product'].startswith('tb-') and s['runtime']['GOGC'] == '200'}
        self.assertEqual(len(refused), 32)
        rows = [{'id': rid, 'state': 'NOT_OFFERED_MEMORY_FORECAST' if rid in refused else 'PLANNED_UNSTARTED'} for rid in slots]
        ledger = M.ready_rows({'all672_state_rows': rows})
        self.assertEqual(sorted(p['global_position'] for p in ledger.values()), list(range(672)))
        with self.assertRaises(ValueError):
            M.ready_rows({'all672_state_rows': rows[:-1]})
        bad = copy.deepcopy(rows)
        bad[0]['state'] = 'INDEPENDENTLY_ACCEPTED_COMPLETE'
        with self.assertRaises(ValueError):
            M.ready_rows({'all672_state_rows': bad})

    def fixture(self, runtime=('50', '4GiB'), ns=100):
        run = {'id': str(runtime), 'block': 0, 'window': M.WINDOWS[0],
               'process': {'supervisor_ok': True, 'sampled_peak_rss_bytes': 100,
                           'preparation': {'elapsed_ns': 100}}}
        rows = {str(i): {'attempted': True, 'published_response_ns': ns,
                'independently_complete': True, 'native_output_sha256': 'native',
                'selected_output_sha256': 'selected', 'authoritative_quality_sha256': 'quality'} for i in range(60)}
        return run, rows

    def test_native_order_hash_and_selected_clock_exclusion(self):
        a = {'raw': [1, 2], 'final': [1, 2]}
        b = {'raw': [2, 1], 'final': [1, 2]}
        self.assertNotEqual(M.digest(a), M.digest(b))
        row = {'recommendation_quality': {'choices': {'complete': True, 'groups': [{'selections': [
            {'limit': 3, 'method': 'preference_minimax', 'complete': True, 'selected': ['b', 'a'], 'elapsed_ns': 100}]}]}}}
        before = M.digest(M.selected_output(row))
        row['recommendation_quality']['choices']['groups'][0]['selections'][0]['elapsed_ns'] = 999
        self.assertEqual(M.digest(M.selected_output(row)), before)
        row['recommendation_quality']['choices']['groups'][0]['selections'][0]['selected'].reverse()
        self.assertNotEqual(M.digest(M.selected_output(row)), before)
        self.assertIsNone(M.selected_output({}))

    def test_incomplete_native_pair_is_unknown_not_exact(self):
        a, ar = self.fixture()
        b, br = self.fixture(('100', '4GiB'))
        rows = {a['id']: ar, b['id']: br}
        self.assertEqual(M.compare_runs(a, b, rows)['native_parity'], 'exact')
        br['0']['native_output_sha256'] = 'changed'
        self.assertEqual(M.compare_runs(a, b, rows)['native_parity'], 'mismatch')
        br['0']['independently_complete'] = False
        value = M.compare_runs(a, b, rows)
        self.assertEqual(value['native_parity'], 'unknown')
        self.assertFalse(value['quality_exact'])
        self.assertEqual(value['candidate_actual_clock_rows'], 60)
        self.assertEqual(value['candidate_independently_complete_clock_rows'], 59)

    def test_frozen_gate_needs_both_blocks_all_windows_and_resources(self):
        left, right, rows = [], [], {}
        for block in (0, 1):
            for window in M.WINDOWS:
                for group, runtime, ns in ((left, ('50', '4GiB'), 100), (right, ('100', '4GiB'), 97)):
                    run, records = self.fixture(runtime, ns)
                    run.update(id=f'{runtime}-{block}-{window}', block=block, window=window)
                    group.append(run)
                    rows[run['id']] = records
        def check(kind='same_source_same_product_runtime'):
            return M.contrast(kind, 'a', 'b', left, right, rows)
        self.assertTrue(check()['passes_frozen_same_cost_gate'])
        self.assertFalse(check('quality_latency_tradeoff_not_source_speedup')['passes_frozen_same_cost_gate'])
        right[-1]['process']['sampled_peak_rss_bytes'] = None
        self.assertIsNone(check()['max_sampled_rss_ratio'])
        self.assertFalse(check()['passes_frozen_same_cost_gate'])
        right[-1]['process']['sampled_peak_rss_bytes'] = 100
        rows[right[-1]['id']]['0']['independently_complete'] = None
        self.assertFalse(check()['same_cost_gate_eligible'])
        self.assertEqual(len(check()['cells']), 8)

    def test_window_regression_is_not_hidden_by_pooled_block_improvement(self):
        left, right, rows = [], [], {}
        for block in (0, 1):
            for i, window in enumerate(M.WINDOWS):
                for group, runtime, ns in ((left, ('50', '4GiB'), 1000 if i == 3 else 100),
                                          (right, ('100', '4GiB'), 970 if i == 3 else 97)):
                    run, records = self.fixture(runtime, ns)
                    run.update(id=f'{runtime}-{block}-{window}', block=block, window=window)
                    group.append(run)
                    rows[run['id']] = records
        for record in rows[right[0]['id']].values():
            record['published_response_ns'] = 104
        value = M.contrast('same_source_same_product_runtime', 'a', 'b', left, right, rows)
        self.assertEqual(value['pooled_actual_published_p95_ratio_by_block'], {'0': .97, '1': .97})
        self.assertEqual(value['cells'][0]['p95_ratio'], 1.04)
        self.assertFalse(value['passes_frozen_same_cost_gate'])

    def test_quality_summaries_do_not_average_quantiles_or_zero_unknowns(self):
        ordinary = [{'display_quality': {'score': {'eligible': 2, 'covered': 1,
            'regret_score_seconds': {'count': 2, 'mean': 1, 'max': 2, 'p95': 2}}}},
            {'display_quality': {'score': {'eligible': 1, 'covered': 0,
            'regret_score_seconds': {'count': 1, 'mean': 10, 'max': 10, 'p95': 10}}}},
            {'display_quality': None}]
        summary = M.quality_counts(ordinary)['score']
        self.assertEqual(summary['unknown_quality_rows'], 1)
        self.assertEqual(summary['eligible'], 3)
        self.assertEqual(summary['regret_score_seconds']['mean'], 4)
        self.assertEqual(summary['regret_score_seconds']['max'], 10)
        self.assertNotIn('p95', summary['regret_score_seconds'])

    def test_array_stream_and_preparation_projection_remain_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metrics.json'
            values = [{'id': 'x', 'blob': 'a'*70000}, {'id': 'y'}]
            path.write_text(json.dumps(values))
            self.assertEqual(list(M.array_rows(path)), values)
            for text in ('[{},]', '[{}', '[{}]garbage', '[{} {}]'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    list(M.array_rows(path))
        value = M.compact_process({'preparation': {'complete': True, 'elapsed_ns': 0,
            'native_diagnostics': ['large']}, 'sampled_peak_rss_bytes': None})
        self.assertEqual(value['preparation']['elapsed_ns'], 0)
        self.assertNotIn('native_diagnostics', value['preparation'])
        self.assertIsNone(value['sampled_peak_rss_bytes'])

    def test_bound_inputs_keep_view_path_and_detect_changes_and_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'target.json'
            view = Path(directory)/'view.json'
            M.write(target, {'state': None, 'clock': 0})
            view.symlink_to(target)
            ref = M.identity(view)
            self.assertEqual(ref['path'], str(view))
            bindings = {}
            self.assertEqual(M.bound(ref, bindings), view)
            self.assertIn(str(view), bindings)
            with self.assertRaises(FileExistsError):
                M.write(target, {})
            target.write_text('{}')
            with self.assertRaises(ValueError):
                M.bound(ref, {})


if __name__ == '__main__':
    unittest.main()
