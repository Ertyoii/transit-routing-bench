#!/usr/bin/env python3
"""DRAFT synthetic-only tests. NOT RUN or imported during live measurement.

Every fixture/file is created only at future test execution, in memory or a
TemporaryDirectory. Never reads the real READY, model, raw, source tree, storage,
evaluator or campaign lock. The operational consumer is imported only when this
suite is deliberately run in an owner-allocated quiet qualification slot.
"""
import collections
import contextlib
import copy
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).with_name('consumer.py')
SPEC = importlib.util.spec_from_file_location('runtime_window_consumer_under_test', MODULE)
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)


def runtime_fixture():
    """Eight84-position stages; each window160 offers plus8 forecast refusals."""
    defs = {w: {'window': w, 'dataset': {'path': '/synthetic/models/%d.json' % wi,
             'sha256': 'abcd'[wi] * 64, 'bytes': 1}}
            for wi, w in enumerate(C.WINDOWS)}
    ready = {'runtime_slots': 672, 'all672_state_rows': [], 'stages': []}
    plans, specs, ledgers, requests = [], [], [], []
    for stage in range(8):
        initial, run_specs, runs, rows, outputs = [], [], [], [], []
        root = '/synthetic/original/stage-%d' % stage
        for wi, window in enumerate(C.WINDOWS):
            for offset in range(21):
                position = stage * 84 + wi * 21 + offset
                # Deliberately misleading ID text: membership MUST use spec fields.
                rid = 'opaque-%03d-weekday-overnight-20261020' % position
                refusal = offset == 20
                origin = {'id': rid, 'state': 'NOT_OFFERED_MEMORY_FORECAST' if refusal else 'PLANNED_UNSTARTED'}
                if refusal:
                    origin.update(reason='frozen synthetic forecast refusal', evidence={'path': '/synthetic/forecast.json'})
                initial.append(origin)
                run = {'id': rid, 'window': window, 'variant_id': 'variant-%d' % position,
                       'argv': ['/synthetic/bin/native', '-dataset', defs[window]['dataset']['path'],
                                '-queries', '/synthetic/queries/%d.json' % wi,
                                '-preference-scenarios', '/synthetic/config/top3.json',
                                '-algorithm', 'mc_raptor', '-quality', '-display-k', '-1'],
                       'env': {'GOGC': '100', 'GOMEMLIMIT': '4GiB'},
                       'requested_selector_limit': 3,
                       'source_policy_binding': {'source': 'synthetic-frozen'}}
                run_specs.append(copy.deepcopy(run))
                row = {'id': rid, 'global_position': position, 'initial_state_row': copy.deepcopy(origin),
                       'state': origin['state'] if refusal else
                                ('UNKNOWN_MISSING_RESULT' if offset % 3 == 0 else
                                 'UNSTARTED_AFTER_TERMINAL_STAGE' if offset % 3 == 1 else 'RESULT_RECORDED'),
                       'admitted_raw_files': []}
                if not refusal:
                    runs.append(copy.deepcopy(run))
                    row['actual_result_fields'] = {'ok': False, 'outcome': 'prelaunch_memory_admission_rejected'} if offset == 2 else None
                    outputs.append({'role': 'proof-summary', 'run_id': rid,
                                    'raw_path': root + '/' + rid + '/artifact/summary.json',
                                    'frozen_bindings': {'dataset_sha256': defs[window]['dataset']['sha256']}})
                rows.append(row)
        ready['all672_state_rows'].extend(copy.deepcopy(initial))
        ready['stages'].append({'future_serving_root': root})
        plans.append({'runs': runs,
                      'runtime_stage': {'all84_state_rows': copy.deepcopy(initial), 'block':stage//4, 'segment':stage%4, 'global_start_position':84*(stage%4)},
                      'workload_registry': {'path': 'relative/registry.json', 'sha256': 'e' * 64, 'bytes': 7},
                      'frozen_ancestry': {'unchanged': [1, 2, 3]}})
        specs.append({'run_specs': run_specs})
        ledgers.append({'rows': rows})
        requests.append({'outputs': outputs})
    return ready, plans, specs, ledgers, requests, defs


def scalar_fixture():
    defs = runtime_fixture()[-1]
    weights = [{'transfer_seconds': i, 'extra_walk_weight': i / 10} for i in range(9)]
    slots, headers = [], {}
    for wi, window in enumerate(C.WINDOWS):
        source = '/synthetic/scalar/%d.jsonl' % wi
        header = {'kind': 'metadata', 'dataset_sha256': defs[window]['dataset']['sha256'],
                  'workload_sha256': str(wi + 1) * 64, 'weights_sha256': 'f' * 64}
        headers[source] = header
        for qi in range(12):
            query = {'id': 'w%d-q%d' % (wi, qi), 'departure': 100, 'latest_arrival': 200}
            for index, weight in enumerate(weights):
                missing = qi == 0 and index == 0
                slots.append({'key': [header['dataset_sha256'], header['workload_sha256'],
                                      header['weights_sha256'], query['id'], index],
                              'source': source, 'query': query, 'weight': copy.deepcopy(weight),
                              'state': 'UNRESOLVED_MISSING_ORIGINAL_ROW' if missing else 'PRESENT_ORIGINAL_SCALAR_RESULT',
                              'original_result': None if missing else {'result': {'complete': True, 'found': True}}})
    return {'slots': slots, 'headers': headers}, defs, weights


def scalar_output(slots):
    return [{'dataset_sha256': slot['key'][0], 'query_id': slot['key'][3],
             'source': slot['source'], 'weight': copy.deepcopy(slot['weight']),
             'complete': slot['original_result'] is not None,
             'found': slot['original_result'] is not None,
             **({'error': 'unresolved_missing_oracle_output'} if slot['original_result'] is None else {})}
            for slot in slots]


def native_fixture():
    rows = []
    for mi, digest in enumerate('abcd'):
        for run in range(4):
            for query in range(60):
                rows.append({'dataset_sha256': digest * 64, 'campaign': '/synthetic/donors/%d' % mi,
                             'run_id': 'native-%d' % run, 'query': {'id': 'q%d' % query},
                             'status': 'native_complete' if query % 3 else 'unresolved_source',
                             'native_complete': bool(query % 3), 'native_row_present': bool(query % 3)})
    counts, statuses = collections.Counter(), collections.defaultdict(collections.Counter)
    completion, missing = collections.Counter(), collections.Counter()
    for row in rows:
        key = (row['dataset_sha256'], row['campaign'], row['run_id'])
        counts[key] += 1
        statuses[key][row['status']] += 1
        completion[key] += row['native_complete']
        missing[key] += not row['native_row_present']
    return rows, {'counts': counts, 'statuses': statuses, 'completion': completion,
                  'missing': missing, 'offered_rows': 960}


def native_summary(expected, current):
    return {'offered_native_reference_rows': 960, 'offered_serving_rows_added': 0,
            'completed_serving_rows_added': 0, 'scalar_slots_added': 0,
            'source_denominators': [{'dataset_sha256': key[0], 'campaign': key[1], 'run_id': key[2],
                'offered_rows': count,
                'source_native_complete_rows': expected['completion'][key],
                'source_unknown_or_incomplete_rows': count - expected['completion'][key],
                'source_missing_rows': expected['missing'][key],
                'independent_materialization_statuses_source_audit_asserted': dict(expected['statuses'][key]),
                'native_presence_and_completion_rechecked_from_pass': key[0] == current}
                for key, count in expected['counts'].items()]}


class RegularFiles:
    @contextlib.contextmanager
    def regular_reader(self, path):
        with Path(path).open('rb') as file:
            yield file, None


class TestConsumerSynthetic(unittest.TestCase):
    def partitioned(self, data=None):
        return C.partition(*(runtime_fixture() if data is None else data))

    def test_01_all8_672_640_four160_plus8_closure(self):
        groups = self.partitioned()
        self.assertEqual(sum(len(group['runs']) for group in groups.values()), 640)
        self.assertEqual(sum(len(group['rows']) for group in groups.values()), 672)
        for group in groups.values():
            self.assertEqual((len(group['runs']), len(group['rows'])), (160, 168))
            self.assertEqual([parent['stage_index'] for parent in group['parents']], list(range(8)))

    def test_02_rejected_missing_unstarted_remain_included(self):
        groups = self.partitioned()
        for group in groups.values():
            offered = {run['id'] for run in group['runs']}
            for row in group['rows']:
                if row['state'] != 'NOT_OFFERED_MEMORY_FORECAST':
                    self.assertIn(row['id'], offered)
            self.assertTrue(any(row['state'] == 'UNKNOWN_MISSING_RESULT' for row in group['rows']))
            self.assertTrue(any(row['state'] == 'UNSTARTED_AFTER_TERMINAL_STAGE' for row in group['rows']))
            self.assertTrue(any((row.get('actual_result_fields') or {}).get('outcome') ==
                                'prelaunch_memory_admission_rejected' for row in group['rows']))

    def test_03_forecast_refusals_never_synthetic_run_objects(self):
        for group in self.partitioned().values():
            refused = {row['id'] for row in group['rows'] if row['state'] == 'NOT_OFFERED_MEMORY_FORECAST'}
            self.assertEqual(len(refused), 8)
            self.assertTrue(refused.isdisjoint({run['id'] for run in group['runs']}))

    def test_04_window_membership_uses_exact_fields_not_id_substrings(self):
        group = self.partitioned()[C.WINDOWS[0]]
        self.assertTrue(all('weekday-overnight-20261020' in run['id'] for run in group['runs']))
        self.assertTrue(all(run['run']['window'] == C.WINDOWS[0] for run in group['runs']))

    def test_05_stage_local_input_rejected(self):
        data = list(runtime_fixture())
        data[1] = data[1][:-1]
        with self.assertRaises(C.Stop):
            self.partitioned(data)

    def test_06_missing_global_position_rejected(self):
        data = runtime_fixture()
        data[0]['all672_state_rows'].pop()
        with self.assertRaises(C.Stop):
            self.partitioned(data)

    def test_07_reordered_or_mutated_observational_ledger_rejected(self):
        for mode in ('order', 'global_position', 'initial_state'):
            with self.subTest(mode=mode):
                data = runtime_fixture()
                row = data[3][0]['rows'][0]
                if mode == 'order':
                    data[3][0]['rows'][0], data[3][0]['rows'][1] = data[3][0]['rows'][1], row
                elif mode == 'global_position':
                    row['global_position'] = 999
                else:
                    row['initial_state_row']['state'] = 'rewritten'
                with self.assertRaises(C.Stop):
                    self.partitioned(data)

    def test_08_inserting_refusal_as_run_rejected(self):
        data = runtime_fixture()
        refused = next(spec for spec in data[2][0]['run_specs'] if spec['id'] not in
                       {run['id'] for run in data[1][0]['runs']})
        data[1][0]['runs'].append(copy.deepcopy(refused))
        with self.assertRaises(C.Stop):
            self.partitioned(data)

    def test_09_run_spec_window_mismatch_rejected(self):
        data = runtime_fixture()
        data[1][0]['runs'][0]['window'] = C.WINDOWS[1]
        with self.assertRaises(C.Stop):
            self.partitioned(data)

    def test_10_dataset_lexical_alias_or_relative_input_rejected(self):
        for name, replacement in (('-dataset', '/synthetic/models/alias.json'),
                                  ('-queries', 'relative/workload.json'),
                                  ('-preference-scenarios', 'relative/config.json')):
            with self.subTest(name=name):
                data = runtime_fixture()
                argv = data[1][0]['runs'][0]['argv']
                argv[argv.index(name) + 1] = replacement
                with self.assertRaises(C.Stop):
                    self.partitioned(data)

    def test_11_storage_model_identity_mismatch_rejected(self):
        data = runtime_fixture()
        data[4][0]['outputs'][0]['frozen_bindings']['dataset_sha256'] = '0' * 64
        with self.assertRaises(C.Stop):
            self.partitioned(data)

    def test_12_duplicate_original_ids_rejected(self):
        data = runtime_fixture()
        data[2][0]['run_specs'][1]['id'] = data[2][0]['run_specs'][0]['id']
        with self.assertRaises(C.Stop):
            self.partitioned(data)

    def test_13_derived_full_runs_registry_and_top84_equivalent(self):
        parent = runtime_fixture()[1][0]
        before = copy.deepcopy(parent)
        ids = [run['id'] for run in parent['runs'][:5]]
        registry = Path('/synthetic/original/registry.json')
        derived = C.derive_plan(parent, ids, Path('/synthetic/original/stage-0'), registry)
        self.assertEqual(parent, before)
        self.assertEqual(derived['runs'], parent['runs'][:5])
        self.assertEqual(derived['runtime_stage'], parent['runtime_stage'])
        self.assertEqual(derived['workload_registry'], dict(parent['workload_registry'], path=str(registry)))
        self.assertTrue(C.equivalent(parent, derived, ids, registry))

    def test_14_mutated_full_run_fields_rejected(self):
        parent = runtime_fixture()[1][0]
        ids = [parent['runs'][0]['id']]
        registry = Path('/synthetic/original/registry.json')
        for field in ('env', 'argv', 'variant_id', 'requested_selector_limit', 'source_policy_binding'):
            with self.subTest(field=field):
                derived = C.derive_plan(parent, ids, '/synthetic/original/stage-0', registry)
                derived['runs'][0][field] = {'changed': True} if field != 'argv' else ['changed']
                with self.assertRaises(C.Stop):
                    C.equivalent(parent, derived, ids, registry)

    def test_15_mutated_top84_or_new_top_level_fields_rejected(self):
        parent = runtime_fixture()[1][0]
        ids = [parent['runs'][0]['id']]
        for mode in ('top84', 'extra'):
            with self.subTest(mode=mode):
                derived = C.derive_plan(parent, ids, '/synthetic/original/stage-0', '/synthetic/registry.json')
                if mode == 'top84':
                    derived['runtime_stage']['all84_state_rows'].pop()
                else:
                    derived['unapproved_extra'] = True
                with self.assertRaises(C.Stop):
                    C.equivalent(parent, derived, ids, '/synthetic/registry.json')

    def test_16_duplicate_or_reordered_selection_rejected(self):
        parent = runtime_fixture()[1][0]
        first, second = [run['id'] for run in parent['runs'][:2]]
        for ids in ([first, first], [second, first], ['unknown']):
            with self.subTest(ids=ids), self.assertRaises(C.Stop):
                C.derive_plan(parent, ids, '/synthetic/original/stage-0', '/synthetic/registry.json')

    def test_17_registry_normalization_cannot_change_sha_or_bytes(self):
        parent = runtime_fixture()[1][0]
        ids = [parent['runs'][0]['id']]
        for field, value in (('sha256', '0' * 64), ('bytes', 999)):
            with self.subTest(field=field):
                derived = C.derive_plan(parent, ids, '/synthetic/original/stage-0', '/synthetic/registry.json')
                derived['workload_registry'][field] = value
                with self.assertRaises(C.Stop):
                    C.equivalent(parent, derived, ids, '/synthetic/registry.json')

    def test_18_original432_missing_rows_four108_disjoint_partitions(self):
        census, defs, _ = scalar_fixture()
        parts = C.scalar_partition(census, defs)
        self.assertEqual([len(parts[window]) for window in C.WINDOWS], [108] * 4)
        keys = [tuple(slot['key']) for slots in parts.values() for slot in slots]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), 432)
        self.assertEqual(sum(slot['state'] == 'UNRESOLVED_MISSING_ORIGINAL_ROW'
                             for slots in parts.values() for slot in slots), 4)

    def test_19_overlapping_or_missing_scalar_partition_rejected(self):
        for mode in ('overlap', 'omitted', 'wrong_hash'):
            with self.subTest(mode=mode):
                census, defs, _ = scalar_fixture()
                if mode == 'overlap':
                    defs[C.WINDOWS[1]]['dataset']['sha256'] = defs[C.WINDOWS[0]]['dataset']['sha256']
                elif mode == 'omitted':
                    census['slots'].pop()
                else:
                    census['slots'][0]['key'][0] = '0' * 64
                with self.assertRaises(C.Stop):
                    C.scalar_partition(census, defs)

    def test_20_missing_entire_scalar_file_or_header_rejected(self):
        census, defs, weights = scalar_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for mode in ('missing', 'empty', 'wrong_header'):
                with self.subTest(mode=mode):
                    path = root / (mode + '.jsonl')
                    header = copy.deepcopy(next(iter(census['headers'].values())))
                    if mode == 'empty':
                        path.write_text('')
                    elif mode == 'wrong_header':
                        header['kind'] = 'not_metadata'
                        path.write_text(json.dumps(header) + '\n')
                    source = {'file': {'path': str(path), 'sha256': 'e' * 64, 'bytes': 1},
                              'workload': {'path': '/synthetic/workload.json', 'sha256': header['workload_sha256'], 'bytes': 1},
                              'dataset_sha256': defs[C.WINDOWS[0]]['dataset']['sha256'], 'weights_sha256': header['weights_sha256']}
                    workload = {'dataset_sha256': source['dataset_sha256'], 'items': []}
                    with mock.patch.object(C, 'ident', return_value=source['file']), \
                         mock.patch.object(C, 'bound', return_value=workload), self.assertRaises(C.Stop):
                        C.scalar_census(RegularFiles(), [source], weights)

    def test_21_present_headers_expand_all_missing_cartesian432_rows(self):
        census, defs, weights = scalar_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            sources, identities, workloads = [], {}, {}
            for wi, window in enumerate(C.WINDOWS):
                path = Path(tmp) / ('scalar-%d.jsonl' % wi)
                header = copy.deepcopy(list(census['headers'].values())[wi])
                path.write_text(json.dumps(header) + '\n')
                ref = {'path': str(path), 'sha256': 'e' * 64, 'bytes': path.stat().st_size}
                workload_ref = {'path': '/synthetic/workload-%d.json' % wi,
                                'sha256': header['workload_sha256'], 'bytes': 1}
                source = {'file': ref, 'workload': workload_ref, 'dataset_sha256': header['dataset_sha256'],
                          'weights_sha256': header['weights_sha256']}
                sources.append(source)
                identities[str(path)] = ref
                unique = {slot['query']['id']: slot['query'] for slot in census['slots'] if slot['key'][0] == header['dataset_sha256']}
                workloads[workload_ref['path']] = {'dataset_sha256': header['dataset_sha256'],
                    'items': [{'query': query} for query in unique.values()]}
            with mock.patch.object(C, 'ident', side_effect=lambda _s, path: identities[str(path)]), \
                 mock.patch.object(C, 'bound', side_effect=lambda _s, ref: workloads[ref['path']]):
                actual = C.scalar_census(RegularFiles(), sources, weights)
            self.assertEqual(len(actual['slots']), 432)
            self.assertTrue(all(slot['original_result'] is None and
                                slot['state'] == 'UNRESOLVED_MISSING_ORIGINAL_ROW' for slot in actual['slots']))

    def test_22_scalar_output_missing_duplicate_ambiguous_or_coerced_rejected(self):
        census, defs, weights = scalar_fixture()
        slots = C.scalar_partition(census, defs)[C.WINDOWS[0]]
        self.assertTrue(C.check_scalar_output(scalar_output(slots), slots, census['headers'], weights))
        for mode in ('missing', 'duplicate', 'coerced', 'unknown_source', 'ambiguous_weight'):
            with self.subTest(mode=mode):
                rows, local_weights = scalar_output(slots), copy.deepcopy(weights)
                if mode == 'missing':
                    rows.pop()
                elif mode == 'duplicate':
                    rows[-1] = copy.deepcopy(rows[0])
                elif mode == 'coerced':
                    rows[0]['complete'] = 0
                elif mode == 'unknown_source':
                    rows[0]['source'] = '/synthetic/other.jsonl'
                else:
                    local_weights[1] = copy.deepcopy(local_weights[0])
                with self.assertRaises(C.Stop):
                    C.check_scalar_output(rows, slots, census['headers'], local_weights)

    def test_23_missing_original_scalar_row_cannot_be_promoted_or_error_erased(self):
        census, defs, weights = scalar_fixture()
        slots = C.scalar_partition(census, defs)[C.WINDOWS[0]]
        for mode in ('complete', 'found', 'erase_error'):
            with self.subTest(mode=mode):
                rows = scalar_output(slots)
                missing = next(row for row in rows if row.get('error') == 'unresolved_missing_oracle_output')
                if mode == 'erase_error':
                    missing.pop('error')
                else:
                    missing[mode] = True
                with self.assertRaises(C.Stop):
                    C.check_scalar_output(rows, slots, census['headers'], weights)

    def test_24_global_native960_preserved_in_each_of_four_not3840_donors(self):
        rows, expected = native_fixture()
        census = C.native_census(rows)
        self.assertEqual(census['counts'], expected['counts'])
        self.assertEqual(census['statuses'], expected['statuses'])
        self.assertEqual(sum(census['counts'].values()), 960)
        for digest in 'abcd':
            summary = native_summary(expected, digest * 64)
            self.assertTrue(C.check_native_import(summary, census, digest * 64))
            self.assertEqual(sum(source['offered_rows'] for source in summary['source_denominators']), 960)
            self.assertTrue(all(source['native_presence_and_completion_rechecked_from_pass'] is False
                                for source in summary['source_denominators'] if source['dataset_sha256'] != digest * 64))
        # Same source keys repeated in four accepted views still name960 donors.
        self.assertEqual(sum(expected['counts'].values()), 960)

    def test_25_native_short_or_duplicate_source_query_rejected(self):
        for mode in ('short', 'duplicate', 'coerced_complete', 'missing_presence'):
            with self.subTest(mode=mode):
                rows, _ = native_fixture()
                if mode == 'short':
                    rows.pop()
                elif mode == 'duplicate':
                    rows[-1] = copy.deepcopy(rows[0])
                elif mode == 'coerced_complete':
                    rows[0]['native_complete'] = 0
                else:
                    rows[0].pop('native_row_present')
                with self.assertRaises(C.Stop):
                    C.native_census(rows)

    def test_26_native_global_status_loss_promotion_or_serving_mint_rejected(self):
        _, expected = native_fixture()
        current = 'a' * 64
        for mode in ('missing_source', 'rewritten_status', 'promoted_nonrecipient', 'mint_serving', 'duplicate_source',
                     'completion_counter', 'unknown_counter', 'missing_counter'):
            with self.subTest(mode=mode):
                summary = native_summary(expected, current)
                if mode == 'missing_source':
                    summary['source_denominators'].pop()
                elif mode == 'rewritten_status':
                    summary['source_denominators'][0]['independent_materialization_statuses_source_audit_asserted'] = {'complete': 60}
                elif mode == 'promoted_nonrecipient':
                    next(source for source in summary['source_denominators'] if source['dataset_sha256'] != current)[
                        'native_presence_and_completion_rechecked_from_pass'] = True
                elif mode == 'mint_serving':
                    summary['completed_serving_rows_added'] = 1
                elif mode == 'duplicate_source':
                    summary['source_denominators'].append(copy.deepcopy(summary['source_denominators'][0]))
                else:
                    field = {'completion_counter': 'source_native_complete_rows',
                             'unknown_counter': 'source_unknown_or_incomplete_rows',
                             'missing_counter': 'source_missing_rows'}[mode]
                    summary['source_denominators'][0][field] += 1
                with self.assertRaises(C.Stop):
                    C.check_native_import(summary, expected, current)

    def test_27_stream_array_empty_and_large_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metrics.json'
            path.write_text(' [ ] \n')
            self.assertEqual(list(C.iter_array(path)), [])
            values = [{'proof': 'x' * 200000, 'nested': {'values': list(range(100))}}, {'id': 'second'}]
            path.write_text(json.dumps(values))
            self.assertEqual(list(C.iter_array(path)), values)

    def test_28_stream_array_invalid_truncated_trailing_comma_or_bytes_rejected(self):
        invalid = ('', '{}', '[', '[{"id":1}', '[{},]', '[{}, {}', '[{} {}]', '[1]',
                   '[{}] garbage', '[{"id": invalid}]', '[{}],[]', '[,{}]')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metrics.json'
            for value in invalid:
                with self.subTest(value=value):
                    path.write_text(value)
                    with self.assertRaises(C.Stop):
                        list(C.iter_array(path))

    def test_29_future_paths_cover_outputs_without_creating_bundle(self):
        request = {'bundle_root': '/synthetic/never-created/bundle'}
        with mock.patch.object(C.Path, 'mkdir', side_effect=AssertionError('Premature root creation')), \
             mock.patch.object(C.os, 'mkdir', side_effect=AssertionError('Premature root creation')):
            files = C.future_files(request, {})
        self.assertEqual(len(files), len(set(files)))
        for window in C.WINDOWS:
            for name in C.OUTPUT_NAMES:
                self.assertIn(str(Path(request['bundle_root']) / window / 'v4' / name), files)
            for stage in range(8):
                self.assertIn(str(Path(request['bundle_root']) / window / 'views' / ('stage-%d' % stage) / 'plan.json'), files)
        for bad in ('relative/bundle', '/synthetic/a/../bundle'):
            with self.subTest(bad=bad), self.assertRaises(C.Stop):
                C.future_files({'bundle_root': bad}, {})

    def test_30_admission_before_root_and_no_nested_storage_freeze_lock(self):
        class Storage:
            SCHEMA = 'prospective-lossless-storage-v1'
            def __init__(self):
                self.depth, self.events = 0, []
            @contextlib.contextmanager
            def quiet(self):
                if self.depth:
                    raise AssertionError('Nested campaign lock')
                self.depth += 1
                self.events.append(('lock', self.depth))
                try:
                    yield
                finally:
                    self.depth -= 1
            def absent(self, path):
                self.events.append(('absent', str(path)))
            def write_doc(self, path, document):
                self.events.append(('write', str(path)))
            def freeze(self, req, adm, inv):
                if self.depth:
                    raise AssertionError('freeze called with parent lock held')
                self.events.append(('freeze', str(adm)))
        storage = Storage()
        request = {'bundle_root': '/synthetic/bundle', 'storage_control_root': '/synthetic/control',
                   'owner': 'synthetic-owner', 'campaign_id': 'synthetic-only', 'minimum_free_bytes': 1000,
                   'native_reference': {'path': '/synthetic/native.jsonl', 'sha256': 'e' * 64, 'bytes': 1}}
        groups = self.partitioned()
        defs = runtime_fixture()[-1]
        context = {'groups': groups, 'windows': defs, 'scalar': {'slots': []},
                   'ledgers': runtime_fixture()[3]}
        ref = {'path': '/synthetic/request.json', 'sha256': 'f' * 64, 'bytes': 1}
        controls = tuple(Path('/synthetic/control') / name for name in ('request.json', 'admission.json', 'inventory.json'))
        with mock.patch.object(C, 'load_inputs', return_value=context), \
             mock.patch.object(C, 'admission_paths', return_value=controls), \
             mock.patch.object(C, 'ident', side_effect=lambda _s, path: {'path': str(path), 'sha256': 'a' * 64, 'bytes': 1}), \
             mock.patch.object(C.Path, 'mkdir', side_effect=AssertionError('Premature bundle creation')):
            result = C.admit(storage, request, ref)
        self.assertEqual(storage.depth, 0)
        self.assertEqual(set(result), {'storage_admission', 'storage_inventory', 'storage_request'})
        freeze_index = next(index for index, event in enumerate(storage.events) if event[0] == 'freeze')
        self.assertIn(('absent', request['bundle_root']), storage.events[:freeze_index])
        self.assertTrue(all(not event[1].startswith(request['bundle_root'] + '/')
                            for event in storage.events if event[0] == 'write'))
        census_write = next(index for index, event in enumerate(storage.events)
                            if event == ('write', '/synthetic/control/ORIGINAL_SCALAR432_CENSUS.json'))
        self.assertGreater(census_write, freeze_index)



class TestCompactRetentionSynthetic(unittest.TestCase):
    """Only future temporary fixtures; never opens a campaign artifact."""
    class Storage(RegularFiles):
        def digest_file(self,path):
            data=Path(path).read_bytes()
            return hashlib.sha256(data).hexdigest(),len(data)
        def read_doc(self,path):
            data=Path(path).read_bytes()
            return json.loads(data),hashlib.sha256(data).hexdigest()

    def fixture(self,root):
        storage=self.Storage();window=C.WINDOWS[0]
        def write(name,value):
            path=root/name;path.write_text(json.dumps(value)+'\n');return C.ident(storage,path)
        acceptance=write('acceptance.json',{'synthetic':True})
        outputs={name:write(name,{'synthetic':True,'name':name}) for name in C.DOWNSTREAM}
        ordinary=root/'ORDINARY_ACTUAL_ROWS.jsonl'
        with ordinary.open('w') as file:
            for process in range(168):
                for query in range(60):
                    file.write(json.dumps({'run':'r%d'%process,'query_id':'q%d'%query})+'\n')
        value={'schema':'sg-runtime8-window-projection-v1','window':window,'dataset_sha256':'a'*64,
            'acceptance_manifest':acceptance,'ordinary_rows':C.ident(storage,ordinary),
            'processes':[{'id':'r%d'%i} for i in range(168)],
            'authoritative_quality_aggregate':outputs['QUALITY_AGGREGATE.json'],
            'authoritative_scalar_comparisons':outputs['ORACLE_COMPARISONS.json']}
        projection=write('WINDOW_PROJECTION.json',value)
        checked={'window':window,'dataset_sha256':'a'*64,'outputs':outputs,
                 'runtime_state_rows':[{'id':'r%d'%i} for i in range(168)]}
        return storage,projection,acceptance,checked,ordinary,value

    def test_31_compact_rows_actual_bytes_required_before_metrics_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage,projection,acceptance,checked,ordinary,value=self.fixture(Path(tmp))
            C.validate_compact_retention(storage,projection,acceptance,checked,C.WINDOWS[0])
            with ordinary.open('a') as file:file.write('{}\n')
            with self.assertRaises(C.Stop):
                C.validate_compact_retention(storage,projection,acceptance,checked,C.WINDOWS[0])
            ordinary.unlink()
            with self.assertRaises((C.Stop,OSError)):
                C.validate_compact_retention(storage,projection,acceptance,checked,C.WINDOWS[0])

    def test_32_compact_acceptance_counts_and_retained_quality_cannot_be_lost(self):
        for mode in ('acceptance','process_count','ordinary_duplicate','quality_missing'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                storage,projection,acceptance,checked,ordinary,value=self.fixture(Path(tmp))
                if mode=='acceptance':value['acceptance_manifest']=dict(acceptance,sha256='f'*64)
                elif mode=='process_count':value['processes']=value['processes'][:-1]
                elif mode=='ordinary_duplicate':
                    text=ordinary.read_text().splitlines();text[-1]=text[-2];ordinary.write_text('\n'.join(text)+'\n')
                    value['ordinary_rows']=C.ident(storage,ordinary)
                else:Path(checked['outputs']['QUALITY_AGGREGATE.json']['path']).unlink()
                Path(projection['path']).write_text(json.dumps(value)+'\n');projection=C.ident(storage,Path(projection['path']))
                with self.assertRaises((C.Stop,OSError)):
                    C.validate_compact_retention(storage,projection,acceptance,checked,C.WINDOWS[0])

if __name__ == '__main__':
    unittest.main()
