#!/usr/bin/env python3
"""STATIC synthetic qualification draft. No test has been executed.

Future invocation requires --quiet-window-open and the authoritative nonblocking
campaign lock BEFORE importing the draft under test. Never wrap this CLI in an
outer flock. Fixtures are tiny new files under tempfile; no actual campaign
source, model, workload, plan, result, admission, parser binary or router is read
or executed. Every child-capture, memory observation and runner is a test double.
"""
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
DRIVER = Path(__file__).with_name('prepare_remaining_finite_v4.py')
api = None
lock_fd = None


def setUpModule():
    global api, lock_fd
    if '--quiet-window-open' not in sys.argv:
        raise RuntimeError('Explicit bounded synthetic quiet-slot flag required')
    sys.argv.remove('--quiet-window-open')
    lock_fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('_synthetic_remaining_finite_v4', DRIVER)
        api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(api)
    except BaseException:
        os.close(lock_fd)
        lock_fd = None
        raise


def tearDownModule():
    global lock_fd
    if lock_fd is not None:
        os.close(lock_fd)
        lock_fd = None


def flags(argv, flag):
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == flag]


def replace_flag(argv, flag, value):
    positions = [index for index, item in enumerate(argv) if item == flag]
    if len(positions) != 1:
        raise ValueError('Synthetic expected exactly one flag: ' + flag)
    argv[positions[0] + 1] = str(value)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='remaining-finite-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root_patch = patch.object(api, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.windows = [f'weekday-{part}-20261020' for part in ('morning', 'midday', 'evening', 'overnight')]
        self.gen = SimpleNamespace(WINDOWS=self.windows,
            CELLS=[(str(gc), heap) for gc in (50, 100, 200) for heap in ('4GiB', '7GiB')],
            POLICY_IDS=['finite20-lean-k3', 'absolute-hybrid-k3'], replace_flag=replace_flag,
            write=Mock(), identity=api.identity)
        self.runner = SimpleNamespace(campaign_gate=SimpleNamespace(flags=flags),
            campaign_environment=lambda: {'GOMAXPROCS': '4', 'SYNTHETIC': '1'})
        self.disk_control = {'preparation_disk_forecast': {'planned_output_bytes': 10000,
            'maximum_single_operation_output_bytes': 2000, 'reserve_bytes': 1_000_000_000,
            'required_disk_free_bytes': 1_000_010_000}}

    def file(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + '\n')
        return path

    def cap_fixture(self):
        policy = self.file('policies/finite20-lean-k3.json', {'delivery_limits': [3], 'lean_delivery': True})
        hashes = {'finite20-lean-k3': api.identity(policy)['sha256']}
        base = {'trip_based': {'max_precomputed_transfers': 100000000, 'closure_limit': 1000000},
                'unchanged_native_contract': True}
        self.file('configs/trip_based_capped-transfers100000000-closure1000000.json', base)
        sources = {product: {'source_root': str(self.root / 'src' / product),
            'go_source_sha256': str(index + 1) * 64,
            'binary': {'path': str(self.root / 'bin' / ('familybench-' + product)), 'sha256': str(index + 4) * 64}}
            for index, product in enumerate(('mc', 'mc-early', 'tb'))}
        runtime = {'GOGC': '50', 'GOMEMLIMIT': '4GiB'}
        selected = {'cap_runtime': runtime, 'cap_products': {product: {'source': source,
            'selector_product': 'finite20-lean-k3'} for product, source in sources.items()}}
        selected['cap_products']['tb']['algorithm'] = 'trip_based_capped'
        rows = []
        for product, algorithm in [('mc', 'mc_raptor'), ('mc-early', 'mc_raptor_early')]:
            for cap in (100000, 250000, 500000, 1000000):
                for window in self.windows:
                    rows.append({'id': f'cap-{product}-labels{cap}-{window}', 'window': window,
                        'declared_label_ceiling': cap, 'requested_selector_limit': 3, 'env': dict(runtime),
                        'argv': [sources[product]['binary']['path'], '-algorithm', algorithm, '-max-labels', str(cap),
                                 '-preference-scenarios', str(policy)],
                        'source_policy_binding': {'source': {'path': sources[product]['source_root'],
                            'go_source_hash_sha256': sources[product]['go_source_sha256']},
                            'binary': dict(sources[product]['binary'])}})
        for cap in (5000000, 25000000, 100000000, 150000000):
            config = copy.deepcopy(base)
            config['trip_based']['max_precomputed_transfers'] = cap
            path = self.file(f'generated/tb-{cap}.json', config)
            for window in self.windows:
                rows.append({'id': f'cap-tb-links{cap}-{window}', 'window': window,
                    'declared_retained_link_ceiling': cap, 'requested_selector_limit': 3, 'env': dict(runtime),
                    'argv': [sources['tb']['binary']['path'], '-algorithm', 'trip_based_capped',
                             '-scoped-config', str(path), '-preference-scenarios', str(policy)],
                    'source_policy_binding': {'source': {'path': sources['tb']['source_root'],
                        'go_source_hash_sha256': sources['tb']['go_source_sha256']}, 'binary': dict(sources['tb']['binary'])}})
        return rows, selected, hashes

    def payload(self, stage='caps', block=0):
        count = api.EXPECTED[stage]
        zero = [f'{stage}-cell-{index:03d}' for index in range(count)]
        sequence = zero if block == 0 else list(reversed(zero))
        rows = [{'id': f'b{block}-' + raw, 'position': index, 'block': block}
                for index, raw in enumerate(sequence)]
        payload = {'stage': stage, 'block': block, 'segment': None, 'order_seed': 314159,
            'balanced_comparison_binding': {'block_zero_cell_order': zero, 'order_seed': 314159},
            'run_specs': rows, 'offered_run_ids_after_forecast': [row['id'] for row in rows],
            'state_rows': [{'id': row['id'], 'state': 'PLANNED_UNSTARTED'} for row in rows]}
        forecast = {'memory_forecasts': {raw: {'classification': 'safe_to_offer_under_declared_forecast',
            'conservative_peak_rss_upper_bytes': 4_000_000_000, 'observed_basis': 'synthetic observation only',
            'representation_and_growth_assumptions': 'synthetic objects; explicit1.5GB margin'} for raw in zero}}
        return payload, forecast

    def native_fixture(self):
        roles = {}
        for index, role in enumerate(('range', 'range-control', 'prep')):
            root = str(self.root / 'src' / ('bench-native-v5-' + role))
            drivers = ['profilebench'] if role.startswith('range') else ['tadbench', 'corechgraphbench', 'familybench']
            roles[role] = {'source_root': root, 'go_source_hash_sha256': str(index + 1) * 64,
                'binaries': {driver: {'path': str(self.root / 'bin' / f'{driver}-native-v5-{role}'),
                                     'sha256': str(index + 4) * 64} for driver in drivers}}
        original = []
        groups = [('range', 'range_raptor', 'profilebench', self.windows),
                  ('range-control', 'range_raptor', 'profilebench', self.windows),
                  ('prep', 'tad', 'tadbench', self.windows),
                  ('prep', 'core_ch', 'corechgraphbench', self.windows),
                  ('prep', 'trip_based', 'familybench', [self.windows[3]]),
                  ('prep', 'tp_source_domain_retained_fixed_caps_experimental_v1', 'familybench', [self.windows[3]])]
        for role_name, family, driver, windows in groups:
            role = roles[role_name]
            for window in windows:
                argv = [role['binaries'][driver]['path'], '-dataset', f'/synthetic/{window}/dataset.json',
                        '-queries', f'/synthetic/{window}/original-queries.json', '-out-dir', '{run_dir}/artifact']
                if driver == 'profilebench':
                    argv += ['-algorithms', family, '-point-workload', '-ready-span-seconds', '60', '-max-window-seconds', '600']
                elif driver == 'familybench':
                    argv += ['-algorithm', family, '-rss-safety-stop', '7000000000', '-max-transfers', '100000000']
                original.append({'id': f'native-contract-{len(original):02d}', 'argv': argv,
                    'cwd': role['source_root'], 'source_roots': [role['source_root']], 'family': family,
                    'variant_id': family + '-' + role_name, 'window': window, 'timeout_s': 1800,
                    'contrast': None, 'equal_caps_control': None, 'walking_metric': None,
                    'inputs': ['/synthetic/original-freeze.json'], 'env': {}, 'rss_safety_stop_bytes': 7000000000})
        expanded = []
        for contract in original:
            role = next(role for role in roles.values() if role['source_root'] == contract['cwd'])
            binary = next(ref for ref in role['binaries'].values() if ref['path'] == contract['argv'][0])
            for gc, heap in self.gen.CELLS:
                row = copy.deepcopy(contract)
                row.update(id=f"native-{contract['id']}-gc{gc}-{heap}", original_native_contract_id=contract['id'],
                    env={'GOGC': gc, 'GOMEMLIMIT': heap}, rss_safety_stop_bytes=api.STOP,
                    source_policy_binding={'source': {'path': contract['cwd'],
                        'go_source_hash_sha256': role['go_source_hash_sha256']}, 'binary': dict(binary)})
                if '-rss-safety-stop' in row['argv']:
                    replace_flag(row['argv'], '-rss-safety-stop', api.STOP)
                expanded.append(row)
        return original, expanded, {'roles': roles}


class FixedInventoryTests(Fixture):
    def test_cap96_is_two48_blocks_and_one32_offer_tb_branch(self):
        rows, selected, hashes = self.cap_fixture()
        api.assert_cap_contracts(rows, selected, hashes, self.gen)
        self.assertEqual(len(rows), 48)
        self.assertEqual(sum('declared_label_ceiling' in row for row in rows) * 2, 64)
        self.assertEqual(sum('declared_retained_link_ceiling' in row for row in rows) * 2, 32)

    def test_cap_tuple_drop_duplicate_new_ceiling_and_second_tb_branch_reject(self):
        rows, selected, hashes = self.cap_fixture()
        for alteration in ('drop', 'duplicate', 'extra-cap', 'second-tb'):
            with self.subTest(alteration=alteration):
                changed = copy.deepcopy(rows)
                if alteration == 'drop': changed.pop()
                elif alteration == 'duplicate': changed[-1] = copy.deepcopy(changed[-2])
                elif alteration == 'extra-cap': changed[0]['declared_label_ceiling'] = 2000000
                else: replace_flag(changed[-1]['argv'], '-algorithm', 'trip_based_capped_answer_walk_ties')
                with self.assertRaises(ValueError): api.assert_cap_contracts(changed, selected, hashes, self.gen)

    def test_cap_source_binary_runtime_policy_or_tb_config_drift_reject(self):
        rows, selected, hashes = self.cap_fixture()
        changed_policy = self.file('policies/different-k3.json', {'delivery_limits': [3], 'changed': True})
        for alteration in ('source', 'binary', 'driver-path', 'runtime', 'policy', 'tb-config'):
            with self.subTest(alteration=alteration):
                changed = copy.deepcopy(rows)
                if alteration == 'source': changed[0]['source_policy_binding']['source']['path'] += '-swap'
                elif alteration == 'binary': changed[0]['source_policy_binding']['binary']['sha256'] = 'f' * 64
                elif alteration == 'driver-path': changed[0]['argv'][0] += '-different-driver'
                elif alteration == 'runtime': changed[0]['env']['GOGC'] = '100'
                elif alteration == 'policy': replace_flag(changed[0]['argv'], '-preference-scenarios', changed_policy)
                else:
                    bad = self.file('generated/different-native-cap.json', {'trip_based': {'max_precomputed_transfers': 150000000}})
                    replace_flag(changed[-1]['argv'], '-scoped-config', bad)
                with self.assertRaises(ValueError): api.assert_cap_contracts(changed, selected, hashes, self.gen)

    def test_exact48_108_order_and_full_reverse_pass(self):
        for stage in ('caps', 'native'):
            for block in (0, 1):
                with self.subTest(stage=stage, block=block): api.assert_fixed_block_order(self.payload(stage, block)[0])

    def test_family_regrouping_same_order_second_block_position_seed_or_segment_reject(self):
        for alteration in ('swap', 'same-order-b1', 'position', 'seed', 'segment', 'drop', 'duplicate'):
            with self.subTest(alteration=alteration):
                payload, _ = self.payload('native', 1)
                if alteration == 'swap': payload['run_specs'][0], payload['run_specs'][1] = payload['run_specs'][1], payload['run_specs'][0]
                elif alteration == 'same-order-b1':
                    for row, raw in zip(payload['run_specs'], payload['balanced_comparison_binding']['block_zero_cell_order']): row['id'] = 'b1-' + raw
                elif alteration == 'position': payload['run_specs'][0]['position'] = 100
                elif alteration == 'seed': payload['order_seed'] += 1
                elif alteration == 'segment': payload['segment'] = 0
                elif alteration == 'drop': payload['run_specs'].pop()
                else: payload['balanced_comparison_binding']['block_zero_cell_order'][-1] = payload['balanced_comparison_binding']['block_zero_cell_order'][0]
                with self.assertRaises(ValueError): api.assert_fixed_block_order(payload)

    def test_native18_original_contracts_expand_to108_then216_without_source_swap(self):
        originals, rows, composition = self.native_fixture()
        by_id = {row['id']: row for row in originals}
        self.assertEqual(len(originals), 18)
        self.assertEqual(len(rows), 108)
        api.assert_native_census(rows, by_id, composition, self.gen)
        census = {family: sum(row['family'] == family for row in rows) * 2 for family in
            ('range_raptor', 'tad', 'core_ch', 'trip_based', 'tp_source_domain_retained_fixed_caps_experimental_v1')}
        self.assertEqual(list(census.values()), [96, 48, 48, 12, 12])

    def test_native_missing_duplicate_extra_or_unknown_runtime_tuple_reject(self):
        originals, rows, composition = self.native_fixture()
        by_id = {row['id']: row for row in originals}
        for alteration in ('missing', 'duplicate', 'extra-contract', 'unknown-cell'):
            with self.subTest(alteration=alteration):
                changed = copy.deepcopy(rows)
                if alteration == 'missing': changed.pop()
                elif alteration == 'duplicate': changed[-1] = copy.deepcopy(changed[-2])
                elif alteration == 'extra-contract': changed[0]['original_native_contract_id'] = 'unapproved-native'
                else: changed[0]['env']['GOMEMLIMIT'] = '9GiB'
                with self.assertRaises(ValueError): api.assert_native_census(changed, by_id, composition, self.gen)

    def test_native_alias_copy_matches_executed_original_but_driver_query_caps_source_or_clocks_drift_reject(self):
        originals, rows, composition = self.native_fixture()
        original = originals[0]
        alias_projection = copy.deepcopy(rows[0])
        api.assert_native_contract(alias_projection, original, composition, self.gen)
        for alteration in ('driver', 'query', 'logical-cap', 'source', 'clock', 'native-input'):
            with self.subTest(alteration=alteration):
                changed = copy.deepcopy(alias_projection)
                if alteration == 'driver': changed['argv'][0] += '-new-engine'
                elif alteration == 'query': replace_flag(changed['argv'], '-queries', '/synthetic/filtered.json')
                elif alteration == 'logical-cap': replace_flag(changed['argv'], '-max-window-seconds', 900)
                elif alteration == 'source': changed['source_policy_binding']['source']['go_source_hash_sha256'] = 'f' * 64
                elif alteration == 'clock': changed['timeout_s'] = 9999
                else: changed['inputs'] = []
                with self.assertRaises(ValueError): api.assert_native_contract(changed, original, composition, self.gen)

    def test_native_original_loader_keeps_only18_and_rejects_extra_success_contract(self):
        originals, _, composition = self.native_fixture()
        primary = {'runs': [row for row in originals if not row['family'].startswith('tp_')]}
        domain = {'runs': [row for row in originals if row['family'].startswith('tp_')]}
        primary['runs'].append({'id': 'previous-budget-exhaustion', 'family': 'unsupported_aux', 'window': self.windows[0]})
        refs = {'primary': {'path': str(api.NATIVE_PRIMARY), 'sha256': '1' * 64},
                'domain': {'path': str(api.NATIVE_DOMAIN), 'sha256': '2' * 64},
                'composition': {'path': str(api.COMPOSITION), 'sha256': '3' * 64}}
        docs = {str(api.NATIVE_PRIMARY): primary, str(api.NATIVE_DOMAIN): domain, str(api.COMPOSITION): composition}
        def fake_load(ref): return copy.deepcopy(docs[ref['path']]), dict(ref)
        with patch.object(api, 'load', side_effect=fake_load):
            selected, _, _ = api.native_originals({'native_originals': refs}, self.gen)
            self.assertEqual(set(selected), {row['id'] for row in originals})
            extra = copy.deepcopy(originals[0]); extra['id'] = 'unapproved-extra-range'
            docs[str(api.NATIVE_PRIMARY)]['runs'].append(extra)
            with self.assertRaises(ValueError): api.native_originals({'native_originals': refs}, self.gen)


class ResourceAndAccountingTests(Fixture):
    def test_all_fixed_states_and_unknown_refusals_remain_without_fake_runs(self):
        payload, forecast = self.payload()
        refused = payload['run_specs'][-1]['id']
        payload['offered_run_ids_after_forecast'].remove(refused)
        payload['state_rows'][-1].update(state='NOT_OFFERED_MEMORY_FORECAST', reason='synthetic150m growth unknown')
        forecast['memory_forecasts'].pop(refused.split('-', 1)[1])
        offered, states = api.assert_offer_accounting(payload, forecast)
        self.assertEqual(len(offered), 47)
        self.assertEqual(len(states), 48)
        self.assertNotIn(refused, offered)

    def test_missing_unknown_unsafe_boolean_boundary_or_unexplained_forecasts_reject_offered_cell(self):
        for alteration in ('missing', 'unknown', 'unsafe', 'boolean', 'stop', 'zero', 'basis', 'growth'):
            with self.subTest(alteration=alteration):
                payload, forecast = self.payload()
                key = payload['run_specs'][0]['id'].split('-', 1)[1]
                prediction = forecast['memory_forecasts'][key]
                if alteration == 'missing': del forecast['memory_forecasts'][key]
                elif alteration in ('unknown', 'unsafe'): prediction['classification'] = alteration
                elif alteration == 'boolean': prediction['conservative_peak_rss_upper_bytes'] = True
                elif alteration == 'stop': prediction['conservative_peak_rss_upper_bytes'] = api.STOP
                elif alteration == 'zero': prediction['conservative_peak_rss_upper_bytes'] = 0
                elif alteration == 'basis': prediction['observed_basis'] = ''
                else: prediction['representation_and_growth_assumptions'] = ''
                with self.assertRaises(ValueError): api.assert_offer_accounting(payload, forecast)

    def test_duplicate_missing_or_offered_refusal_state_reject(self):
        for alteration in ('duplicate-state', 'missing-state', 'offered-refusal', 'duplicate-offer'):
            with self.subTest(alteration=alteration):
                payload, forecast = self.payload()
                if alteration == 'duplicate-state': payload['state_rows'][-1] = copy.deepcopy(payload['state_rows'][0])
                elif alteration == 'missing-state': payload['state_rows'].pop()
                elif alteration == 'offered-refusal': payload['state_rows'][0]['state'] = 'NOT_OFFERED_MEMORY_FORECAST'
                else: payload['offered_run_ids_after_forecast'].append(payload['offered_run_ids_after_forecast'][0])
                with self.assertRaises(ValueError): api.assert_offer_accounting(payload, forecast)

    def test_disk_exact_threshold_passes_low_space_or_invalid_bound_reject(self):
        with patch.object(api.shutil, 'disk_usage', return_value=SimpleNamespace(free=1_000_002_000)):
            api.operation_disk(self.disk_control, self.root)
        with patch.object(api.shutil, 'disk_usage', return_value=SimpleNamespace(free=1_000_001_999)):
            with self.assertRaises(ValueError): api.operation_disk(self.disk_control, self.root)
        for bad in (True, 0, 10001):
            control = copy.deepcopy(self.disk_control)
            control['preparation_disk_forecast']['maximum_single_operation_output_bytes'] = bad
            with self.assertRaises(ValueError): api.operation_disk(control, self.root)

    def test_memory_rejection_records_once_and_never_retries(self):
        wrapper = SimpleNamespace(memory_snapshot=Mock(return_value={'synthetic': True}),
            check_memory=Mock(side_effect=ValueError('synthetic low MemAvailable')))
        with self.assertRaises(ValueError): api.observe_memory(self.root / 'mock-only-admission.json', self.gen, wrapper)
        self.assertEqual(wrapper.memory_snapshot.call_count, 1)
        self.assertEqual(wrapper.check_memory.call_count, 1)
        self.assertEqual(self.gen.write.call_args.args[1]['decision'], 'rejected')
        self.assertFalse((self.root / 'mock-only-admission.json').exists())

    def test_busy_lock_rejects_before_campaign_import_hash_or_output_creation(self):
        target = self.root / 'never-created-preflight'
        argv = ['prepare_remaining_finite_v4.py', '--quiet-window-open', '--control',
                str(self.root / 'never-read-control.json'), '--out-dir', str(target)]
        with patch.object(sys, 'argv', argv), patch.object(api.os, 'open', return_value=123456), \
             patch.object(api.os, 'close') as closed, \
             patch.object(api.fcntl, 'flock', side_effect=BlockingIOError('synthetic busy lock')), \
             patch.object(api, 'identity') as identities, patch.object(api, 'module') as imports:
            with self.assertRaises(BlockingIOError): api.main()
            identities.assert_not_called()
            imports.assert_not_called()
            closed.assert_called_once_with(123456)
        self.assertFalse(target.exists())

    def test_missing_quiet_flag_rejects_before_opening_lock(self):
        argv = ['prepare_remaining_finite_v4.py', '--control', '/synthetic/not-read',
                '--out-dir', str(self.root / 'not-created')]
        with patch.object(sys, 'argv', argv), patch.object(api.os, 'open') as opened:
            with self.assertRaises(ValueError): api.main()
            opened.assert_not_called()

    def test_writer_roots_absent_disjoint_and_no_symlink_traversal(self):
        control = {'future_measurement_and_evaluation_roots': [str(self.root / 'future-measurement'), str(self.root / 'future-v4')]}
        api.future_roots(control, self.root / 'qualification')
        (self.root / 'future-measurement').mkdir()
        with self.assertRaises(ValueError): api.future_roots(control, self.root / 'qualification')
        (self.root / 'future-measurement').rmdir()
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        control['future_measurement_and_evaluation_roots'] = [str(self.root / 'alias' / 'future')]
        with self.assertRaises(ValueError): api.future_roots(control, self.root / 'qualification')


class ParserSemanticsTests(Fixture):
    def parser_fixture(self, native=False, old=False):
        dataset = self.file('tiny-parser-fixtures/dataset.json', {'synthetic': 'not a campaign model'})
        queries = self.file('tiny-parser-fixtures/queries.json', {'synthetic': 'not actual requests'})
        preferences = self.file('tiny-parser-fixtures/preferences.json', {'delivery_limits': [3]})
        native_origin = 'bench-v3-control' if old else ('bench-native-v5-range' if native else 'bench-safe-fill-B-q01')
        source = {'path': str(self.root / 'src' / native_origin), 'go_source_hash_sha256': 'a' * 64}
        binary = self.root / 'bin' / ('profilebench-native-v5-range' if native else 'familybench-synthetic')
        argv = [str(binary), '-dataset', str(dataset), '-queries', str(queries), '-out-dir', '{run_dir}/artifact']
        argv += ['-algorithms', 'range_raptor'] if native else ['-algorithm', 'mc_raptor', '-preference-scenarios', str(preferences)]
        row = {'argv': argv, 'cwd': source['path'], 'source_policy_binding': {'source': source,
               'native_origin': source['path']}}
        actual = {'event': 'input_only_acceptance', 'accepted': True, 'query_count': 60,
            'queries_sha256': api.identity(queries)['sha256'], 'dataset_sha256': api.identity(dataset)['sha256'],
            'selection': {'algorithm': 'mc_raptor'}, 'provenance': {'runtime_matches_build': True,
                'runtime_tree_sha256': source['go_source_hash_sha256']},
            'driver': 'profilebench' if native else 'familybench', 'seed_metadata': {'synthetic_seed': 123}}
        generic = {'accepted': True, 'query_count': 60, 'queries_sha256': actual['queries_sha256'],
            'dataset_sha256': actual['dataset_sha256'], 'preferences_sha256': api.identity(preferences)['sha256'],
            'seed_metadata': dict(actual['seed_metadata'])}
        helper_binary = {'path': str(self.root / 'bin/inputpreflight-synthetic'), 'sha256': 'b' * 64}
        role = {'binaries': {'inputpreflight': helper_binary}} if native else None
        control = dict(self.disk_control, old_source_matched_helper_receipt={'path': '/synthetic/helper-receipt', 'sha256': 'c' * 64})
        return row, actual, generic, role, control, helper_binary

    def call_parser(self, row, actual, generic, role, control, old=False):
        stdout_actual = self.file('capture/actual.stdout', actual)
        stdout_generic = self.file('capture/generic.stdout', generic)
        def fake_capture(argv, *unused):
            return (stdout_generic if Path(argv[0]).name.startswith('inputpreflight') else stdout_actual), {'synthetic': True}
        receipt = {'source_before_after': row['source_policy_binding']['source'],
                   'binary': {'path': str(self.root / 'bin/inputpreflight-synthetic'), 'sha256': 'b' * 64}}
        with patch.object(api, 'operation_disk'), patch.object(api, 'observe_memory'), \
             patch.object(api, 'input_capture', side_effect=fake_capture) as capture, \
             patch.object(api, 'checked', side_effect=lambda ref: ref), \
             patch.object(api, 'load', return_value=(receipt, control['old_source_matched_helper_receipt'])):
            result = api.parser_check('synthetic-class', row, role, control, self.root, '0-3',
                self.gen, Mock(), self.runner, Mock())
        return result, capture

    def test_sourceb_actual_consumer_accepts_exact_input_source_algorithm_and_count(self):
        row, actual, generic, role, control, _ = self.parser_fixture()
        result, capture = self.call_parser(row, actual, generic, role, control)
        self.assertEqual(result['mode'], 'actual_source_matched_consuming_driver_input_only')
        self.assertEqual(capture.call_count, 1)
        self.assertEqual(capture.call_args.args[0].count('-input-only'), 1)

    def test_actual_source_count_algorithm_or_input_bytes_mismatch_reject(self):
        for alteration in ('source', 'build', 'count', 'algorithm', 'dataset', 'query'):
            with self.subTest(alteration=alteration):
                row, actual, generic, role, control, _ = self.parser_fixture()
                if alteration == 'source': actual['provenance']['runtime_tree_sha256'] = 'f' * 64
                elif alteration == 'build': actual['provenance']['runtime_matches_build'] = False
                elif alteration == 'count': actual['query_count'] = 59
                elif alteration == 'algorithm': actual['selection']['algorithm'] = 'different-objective'
                elif alteration == 'dataset': actual['dataset_sha256'] = 'f' * 64
                else: actual['queries_sha256'] = 'f' * 64
                with self.assertRaises(ValueError): self.call_parser(row, actual, generic, role, control)

    def test_native_generic_plus_actual_driver_and_seed_must_match(self):
        row, actual, generic, role, control, _ = self.parser_fixture(native=True)
        result, capture = self.call_parser(row, actual, generic, role, control)
        self.assertEqual(capture.call_count, 2)
        self.assertEqual(result['acceptance']['driver'], 'profilebench')
        for alteration in ('driver', 'seed', 'generic-rejection'):
            with self.subTest(alteration=alteration):
                changed, changed_generic = copy.deepcopy(actual), copy.deepcopy(generic)
                if alteration == 'driver': changed['driver'] = 'familybench'
                elif alteration == 'seed': changed['seed_metadata'] = {'synthetic_seed': 999}
                else: changed_generic['accepted'] = False
                with self.assertRaises(ValueError): self.call_parser(row, changed, changed_generic, role, control)

    def test_old_original_source_uses_only_qualified_strict_helper_not_familybench_input_only(self):
        row, actual, generic, role, control, _ = self.parser_fixture(old=True)
        result, capture = self.call_parser(row, actual, generic, role, control, old=True)
        self.assertEqual(result['mode'], 'exact_original_source_strict_helper_not_familybench_input_only')
        self.assertEqual(capture.call_count, 1)
        argv = capture.call_args.args[0]
        self.assertTrue(Path(argv[0]).name.startswith('inputpreflight'))
        self.assertNotIn('-input-only', argv)

    def test_serving_marker_missing_acceptance_or_duplicate_actual_acceptance_reject(self):
        row, actual, generic, role, control, _ = self.parser_fixture()
        for values in ([actual, {'event': 'first_available_answer'}], [], [actual, actual]):
            with self.subTest(events=[item.get('event') for item in values]):
                stdout = self.root / 'capture-events.stdout'
                stdout.write_text(''.join(json.dumps(item) + '\n' for item in values))
                with patch.object(api, 'operation_disk'), patch.object(api, 'observe_memory'), \
                     patch.object(api, 'input_capture', return_value=(stdout, {})):
                    with self.assertRaises(ValueError): api.parser_check('events', row, None, control,
                        self.root, '0-3', self.gen, Mock(), self.runner, Mock())

    def test_router_or_unsupported_binary_reject_before_capture(self):
        helper = SimpleNamespace(capture=Mock(return_value=('synthetic', {})))
        for argv in (['familybench-synthetic', '-algorithm', 'mc_raptor'],
                     ['profilebench-synthetic'], ['corechgraphbench-synthetic'],
                     ['tadbench-synthetic'], ['unknown-driver', '-input-only'],
                     ['familybench-synthetic', '-input-only', '-input-only']):
            with self.subTest(argv=argv):
                with self.assertRaises(ValueError): api.input_capture(argv, {'cwd': '/synthetic'}, self.root / 'capture',
                    '0-3', self.gen, Mock(), self.runner, helper)
        helper.capture.assert_not_called()

    def test_allowed_input_only_capture_is_only_mocked_and_uses_safe_parser_environment(self):
        helper = SimpleNamespace(capture=Mock(return_value=('synthetic', {})))
        api.input_capture(['corechgraphbench-synthetic', '-input-only'], {'cwd': '/synthetic'}, self.root / 'capture',
            '0-3', self.gen, Mock(), self.runner, helper)
        env = helper.capture.call_args.args[2]
        self.assertEqual((env['GOGC'], env['GOMEMLIMIT']), ('50', '4GiB'))
        self.assertEqual(env['SYNTHETIC'], '1')


if __name__ == '__main__':
    # unittest parses flags before setUpModule, so preserve the authorization
    # signal outside argv while constructing the test program.
    if '--quiet-window-open' not in sys.argv:
        raise SystemExit('Explicit bounded synthetic quiet slot required; no tests imported/run')
    sys.argv.remove('--quiet-window-open')
    original_setup = setUpModule
    def authorized_setup():
        sys.argv.append('--quiet-window-open')
        original_setup()
    setUpModule = authorized_setup
    unittest.main(verbosity=2)
