#!/usr/bin/env python3
"""Generate exact create-only finite serving specifications, never launch.

Static draft. Imports of campaign code, source scans, config materialization and
identity verification occur only after explicit quiet-slot approval and the
authoritative nonblocking flock. Output is deliberately NOT a runnable plan:
run_specs must receive actual source-matched parser/envelope preflight before a
new executable plan is created and separately authorized. No run_one call exists.
"""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
PANEL = ROOT / 'data-workload/workloads/phase_hash_a_conservative600'
WRAPPER = ROOT / 'harness/run_campaign_memory_admission_v1.py'
BASE = ROOT / 'harness/run_campaign.py'
WRAPPER_SHA = '48a0e60df21641472796c4c52cc6168926c1a228048fea7acc13f6314e347ec9'
BASE_SHA = '206076513f4fb023e38deb9aee96de07c8c885b579e716c56350c7f73ff4480b'
COUNT_FREEZE = ROOT / 'protocol/FINITE_CAMPAIGN_COUNT_FREEZE_V4.json'
CORRECTION = ROOT / 'protocol/BASELINE_PRESERVATION_CORRECTION_V3.json'
RUNTIME_SELECTION = ROOT / 'protocol/RUNTIME_SELECTION_FREEZE_V6.json'
WINDOWS = ['weekday-morning-20261020', 'weekday-midday-20261020',
           'weekday-evening-20261020', 'weekday-overnight-20261020']
CELLS = [(str(gc), heap) for gc in (50, 100, 200) for heap in ('4GiB', '7GiB')]
STOP = 5_500_000_000
EXPECTED = {'runtime': 672, 'caps': 96, 'native': 216, 'selectors': 96}
POINT = {
    'raptor-local-walk-ties': ('raptor_local_walk_ties', None),
    'raptor-early-local-walk-ties': ('raptor_early_local_walk_ties', None),
    'mc-qualified-top3': ('mc_raptor', None),
    'mc-early-qualified-top3': ('mc_raptor_early', None),
    'ultra-capped-local-walk-ties': ('ultra_capped_local_walk_ties', 'ultra_transfer_complete_capped.json'),
    'ultra-subset-local-walk-ties': ('ultra_subset_local_walk_ties', 'ultra_cap_safe_stay_witness_subset_v1.json'),
    'tb-compact-native-capped': ('trip_based_capped', 'trip_based_capped-transfers100000000-closure1000000.json'),
    'tb-compact-answer-walk-ties': ('trip_based_capped_answer_walk_ties', 'trip_based_capped-transfers100000000-closure1000000.json'),
}
OLD = {
    'old-native-raptor-control': ('raptor', None),
    'old-native-raptor-early-control': ('raptor_early', None),
    'old-native-mc-control': ('mc_raptor', None),
    'old-native-mc-early-control': ('mc_raptor_early', None),
    'old-native-ultra-capped-control': ('ultra_transfer_complete_capped', 'ultra_transfer_complete_capped.json'),
    'old-native-ultra-subset-control': ('ultra_cap_safe_stay_witness_subset_v1', 'ultra_cap_safe_stay_witness_subset_v1.json'),
}
POLICY_IDS = ['finite20-lean-k3', 'finite20-lean-k5', 'absolute-greedy-k3', 'absolute-greedy-k5',
              'absolute-hybrid-k3', 'absolute-hybrid-k5', 'normalized-greedy-k3', 'normalized-hybrid-k3',
              'finite20-safe-absolute-k3', 'finite20-safe-normalized-k3',
              'absolute-hybrid-fill-k3', 'absolute-hybrid-fill-k5']
QUALIFIED_ROOTS = {
    'bench-v3-control', 'bench-v3-storage', 'bench-v3-quality', 'bench-tb-answer-ties',
    'bench-sparse-lean-v3', 'bench-finite20-safe-q01', 'bench-safe-fill-B-q01',
    'bench-native-v5-range', 'bench-native-v5-range-control', 'bench-native-v5-prep',
}


def write(path, value):
    with Path(path).open('x') as out:
        json.dump(value, out, sort_keys=True, indent=2, ensure_ascii=False)
        out.write('\n')


def identity(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def checked_ref(ref):
    if not isinstance(ref, dict) or not ref.get('path') or not ref.get('sha256'):
        raise ValueError('Exact path+SHA256 binding required')
    actual = identity(ref['path'])
    if actual['sha256'] != ref['sha256'] or ('bytes' in ref and actual['bytes'] != ref['bytes']):
        raise ValueError('Bound input changed: ' + actual['path'])
    return actual


def load_wrapper():
    if identity(WRAPPER)['sha256'] != WRAPPER_SHA or identity(BASE)['sha256'] != BASE_SHA:
        raise ValueError('Qualified wrapper/base changed')
    spec = importlib.util.spec_from_file_location('_finite_specs_memory_wrapper_v4', WRAPPER)
    wrapper = importlib.util.module_from_spec(spec)
    old = list(sys.path)
    try:
        sys.path.insert(0, str(WRAPPER.parent))
        exec(compile(WRAPPER.read_bytes(), str(WRAPPER), 'exec'), wrapper.__dict__)
        runner = wrapper.load_base()
    finally:
        sys.path[:] = old
    return wrapper, runner


def replace_flag(argv, flag, value):
    positions = [i for i, arg in enumerate(argv) if arg == flag]
    if len(positions) > 1:
        raise ValueError('Duplicate flag ' + flag)
    if positions:
        argv[positions[0] + 1] = str(value)
    else:
        argv.extend([flag, str(value)])


def remove_flag(argv, flag):
    while flag in argv:
        i = argv.index(flag)
        del argv[i:i + 2]


def runtime(value):
    if not isinstance(value, dict) or set(value) != {'GOGC', 'GOMEMLIMIT'}:
        raise ValueError('Freeze exactly GOGC and GOMEMLIMIT')
    if (value['GOGC'], value['GOMEMLIMIT']) not in CELLS:
        raise ValueError('Runtime outside the six predeclared cells')
    return dict(value)


def policies(out, common_inputs):
    """Only materialize existing policies at the twelve owner-declared budgets."""
    directory = out / 'configs'
    directory.mkdir()
    original = ROOT / 'selector-quality/configs'
    configs = {}
    for objective, filename, is_hybrid in [
            ('absolute', 'bounded-absolute-delivery-top3.json', False),
            ('absolute', 'bounded-absolute-hybrid-delivery-top3.json', True),
            ('normalized', 'bounded-normalized-delivery-top3.json', False),
            ('normalized', 'bounded-normalized-hybrid-delivery-top3.json', True)]:
        source = original / filename
        common_inputs.append(identity(source))
        for k in ((3, 5) if objective == 'absolute' else (3,)):
            config = json.loads(source.read_text())
            config['bounded']['limits'] = [k]
            if (config['bounded']['objective'] != objective or config['bounded']['exact_subset_search']
                    or bool(config['bounded'].get('exact_when_feasible', False)) != is_hybrid
                    or config['bounded']['nested'] or config['bounded']['distinct_patterns']):
                raise ValueError('Existing bounded policy changed')
            configs[f'{objective}-' + ('hybrid' if is_hybrid else 'greedy') + f'-k{k}'] = config
    fpath = original / 'finite20-lean-delivery-top3.json'
    common_inputs.append(identity(fpath))
    finite = json.loads(fpath.read_text())
    if not finite.get('lean_delivery') or finite['delivery_policy'] != 'finite_preferences_v2' or finite['delivery_limits'] != [3]:
        raise ValueError('Historical finite20 lean config changed')
    for k in (3, 5):
        config = copy.deepcopy(finite)
        config['delivery_limits'] = [k]
        configs[f'finite20-lean-k{k}'] = config
    bsource = ROOT / 'src/bench-safe-fill-B-q01'
    for name, mapping in [
            ('FINITE_SAFE_MATRIX.json', {'finite20_safe_absolute_exact_v1': 'finite20-safe-absolute-k3',
                                         'finite20_safe_normalized_exact_v1': 'finite20-safe-normalized-k3'}),
            ('HYBRID_FILL_MATRIX.json', {'bounded_absolute_hybrid_fill_v1_top3': 'absolute-hybrid-fill-k3',
                                         'bounded_absolute_hybrid_fill_v1_top5': 'absolute-hybrid-fill-k5'})]:
        source = bsource / name
        ref = identity(source)
        expected = {'FINITE_SAFE_MATRIX.json': 'd91bb11a61616ea8cb9e50c247e2eff10d45af14847ea4235f8dd84a145b2ce5',
                    'HYBRID_FILL_MATRIX.json': '5c7d8a1c93683dd5d97234a66fe0a50ec3ece9570b5b1504d21958bd8b8dc650'}
        if ref['sha256'] != expected[name]:
            raise ValueError('Qualified Source B policy matrix changed')
        common_inputs.append(ref)
        matrix = json.loads(source.read_text())
        for row in matrix['policies']:
            if row['id'] in mapping:
                configs[mapping[row['id']]] = copy.deepcopy(row['config'])
    if set(configs) != set(POLICY_IDS):
        raise ValueError('Exactly the twelve declared policy products required')
    result = {}
    for name in POLICY_IDS:
        path = directory / (name + '.json')
        if name == 'finite20-lean-k3':
            with path.open('xb') as file:
                file.write(fpath.read_bytes())
        else:
            write(path, configs[name])
        result[name] = identity(path)
    return result


def source_binding(desc, runner, cache, common_inputs):
    root = Path(desc['source_root']).resolve(strict=True)
    origin = str(root)
    snapshot = desc.get('metadata_only_snapshot')
    if snapshot:
        receipt_ref = checked_ref(snapshot)
        receipt = json.loads(Path(receipt_ref['path']).read_text())
        origin = receipt['original_source_root']
        before, after = receipt['before'], receipt['after']
        if (receipt.get('metadata_only_exact_snapshot') is not True
                or Path(receipt['snapshot_source_root']).resolve(strict=True) != root
                or before['complete_source_file_sha256'] != after['complete_source_file_sha256']
                or before['go_source_sha256'] != after['go_source_sha256']
                or after['go_source_sha256'] != desc['go_source_sha256']
                or not before['complete_source_file_sha256']
                or checked_ref(receipt['unchanged_original_binary']) != checked_ref(desc['binary'])):
            raise ValueError('Metadata-only snapshot must prove complete-file/Go equality and unchanged old binary')
        common_inputs.append(receipt_ref)
    if (root.parent != ROOT / 'src' or Path(origin).parent != ROOT / 'src'
            or Path(origin).name not in QUALIFIED_ROOTS or (root.name not in QUALIFIED_ROOTS and not snapshot)):
        raise ValueError('Source is outside existing qualified origins or exact metadata-only snapshot contract')
    binary = checked_ref(desc['binary'])
    if Path(binary['path']).parent != ROOT / 'bin':
        raise ValueError('Only existing campaign binaries are eligible')
    receipt = checked_ref(desc['qualification'])
    key = (str(root), desc['go_source_sha256'])
    if key not in cache:
        actual = runner.source_identity(root)
        if actual['go_source_hash_sha256'] != desc['go_source_sha256']:
            raise ValueError('Exact qualified source identity changed')
        cache[key] = actual
    common_inputs.extend([binary, receipt])
    return {'source': cache[key], 'binary': binary, 'qualification': receipt, 'native_origin': origin}


def old_descriptor():
    return {'source_root': str(ROOT / 'src/bench-v3-control'),
            'go_source_sha256': '05a41ecd0b4687e83b57d8a548835137c2d049755815dcbef01bb92590a17800',
            'binary': {'path': str(ROOT / 'bin/familybench-v3-control'),
                       'sha256': 'c9a9b5fc28c5696f89418e29261269497222cc4a8981482426e1ce5a73324d15'},
            'qualification': identity(ROOT / 'evidence/REPAIRED_TUNE_FREEZE_V3.json')}


def point_spec(template, product, algorithm, scoped_name, selected, window, config, common_inputs):
    spec = copy.deepcopy(template)
    argv = spec['argv']
    if Path(selected['native_origin']).name == 'bench-v3-control':
        if (algorithm not in {value[0] for value in OLD.values()}
                or config['sha256'] != 'e15b386211fd5002a37d13076dd5577b95da1c27aafe6043eaa8ab876f9ea612'):
            raise ValueError('Old native controls retain their own objective and supported finite20 lean k3 selector')
    argv[0] = selected['binary']['path']
    replace_flag(argv, '-algorithm', algorithm)
    replace_flag(argv, '-dataset', ROOT / 'data-workload/models/phase_hash_a' / window / 'dataset.json')
    workload = PANEL / (window + '.tune.full.primary_1h_walk600.json')
    replace_flag(argv, '-queries', workload)
    replace_flag(argv, '-preference-scenarios', config['path'])
    replace_flag(argv, '-rss-safety-stop', STOP)
    replace_flag(argv, '-out-dir', '{run_dir}/artifact')
    if scoped_name:
        scoped = ROOT / 'configs' / scoped_name
        replace_flag(argv, '-scoped-config', scoped)
        common_inputs.append(identity(scoped))
    else:
        remove_flag(argv, '-scoped-config')
    # These exact old binaries lack the new optional diagnostics flag.
    compact = Path(selected['native_origin']).name in {'bench-sparse-lean-v3', 'bench-finite20-safe-q01', 'bench-safe-fill-B-q01'}
    if compact:
        replace_flag(argv, '-sparse-diagnostics', 'compact')
    else:
        remove_flag(argv, '-sparse-diagnostics')
    limit = 3 if config['sha256'] == 'e15b386211fd5002a37d13076dd5577b95da1c27aafe6043eaa8ab876f9ea612' else int(config['path'].split('-k')[-1].split('.')[0])
    spec.update(id=product, variant_id=product, window=window,
                cwd=selected['source']['path'], source_roots=[selected['source']['path']],
                inputs=[str(workload.with_suffix('.metadata.json')), selected['qualification']['path']],
                rss_safety_stop_bytes=STOP, requested_selector_limit=limit,
                methodology_qualification_only=False, functional_only=False,
                diagnostic_block=None, offered_queries=60, source_policy_binding=selected,
                diagnostic_export_contract='compact_on_supported_sparse_only' if compact else 'original_full_export_no_new_flag')
    return spec


def native_specs(common_inputs):
    primary_path = ROOT / 'experiments/native-v5-envelope-frozen/primary-tune-native-plan.json'
    domain_path = ROOT / 'experiments/native-v5-envelope-frozen/native-domain-tune-plan.json'
    common_inputs.extend([identity(primary_path), identity(domain_path)])
    primary, domain = json.loads(primary_path.read_text()), json.loads(domain_path.read_text())
    selected = []
    for spec in primary['runs']:
        family = spec['family']
        if family in ('range_raptor', 'tad', 'core_ch') or (family == 'trip_based' and spec['window'] == WINDOWS[3]):
            selected.append(copy.deepcopy(spec))
    selected += [copy.deepcopy(spec) for spec in domain['runs']
                 if spec['family'] == 'tp_source_domain_retained_fixed_caps_experimental_v1' and spec['window'] == WINDOWS[3]]
    if len(selected) != 18:
        raise ValueError('Expected exactly18 previously completed native source/window contracts')
    result = []
    for spec in selected:
        original_id = spec['id']
        for gc, heap in CELLS:
            row = copy.deepcopy(spec)
            row['id'] = f'native-{original_id}-gc{gc}-{heap}'
            row['variant_id'] = spec['variant_id']
            row['env'] = dict(row.get('env', {}), GOGC=gc, GOMEMLIMIT=heap)
            row['rss_safety_stop_bytes'] = STOP
            if '-rss-safety-stop' in row['argv']:
                replace_flag(row['argv'], '-rss-safety-stop', STOP)
            row['native_contract_only'] = True
            row['original_native_contract_id'] = original_id
            result.append(row)
    return result, [primary['workload_registry'], domain['workload_registry']]


def parser_class_key(spec):
    argv = list(spec['argv'])
    replace_flag(argv, '-out-dir', '__PARSER_OUTPUT_PATH_ONLY__')
    binding = {'argv': argv, 'cwd': spec['cwd'], 'source_roots': spec['source_roots'],
               'source_go_sha256': spec['source_policy_binding']['source']['go_source_hash_sha256'],
               'binary_sha256': spec['source_policy_binding']['binary']['sha256']}
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def preview_order(args, out):
    """Small finite order/size-count preview; no campaign imports/source/model scan."""
    cells = []
    if args.stage == 'runtime':
        for product in {**POINT, **OLD}:
            for window in WINDOWS:
                for gc, heap in CELLS:
                    cells.append((f'runtime-{product}-{window}-gc{gc}-{heap}', product))
    elif args.stage == 'selectors':
        cells = [(f'selector-{policy}-{window}', policy) for policy in POLICY_IDS for window in WINDOWS]
    elif args.stage == 'caps':
        for product in ('mc', 'mc-early'):
            for cap in (100000, 250000, 500000, 1000000):
                cells += [(f'cap-{product}-labels{cap}-{window}', product) for window in WINDOWS]
        for cap in (5000000, 25000000, 100000000, 150000000):
            cells += [(f'cap-tb-links{cap}-{window}', 'tb') for window in WINDOWS]
    else:
        native, _ = native_specs([])
        cells = [(spec['id'], spec['variant_id']) for spec in native]
    if len(cells) * 2 != EXPECTED[args.stage]:
        raise ValueError('Order preview count differs from fixed stage budget')
    random.Random(args.order_seed).shuffle(cells)
    full = cells if args.block == 0 else list(reversed(cells))
    start = 84 * args.segment if args.segment is not None else 0
    selected = full[start:start + 84] if args.segment is not None else full
    ids = [f'b{args.block}-' + row[0] for row in selected]
    heavy = [qid for qid, row in zip(ids, selected) if 'ultra-subset' in row[1]]
    canonical = json.dumps(ids, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    payload = {'schema': 'finite-order-disk-count-preview-v4-NOT-A-RUNNER-PLAN',
               'stage': args.stage, 'block': args.block, 'segment': args.segment, 'order_seed': args.order_seed,
               'block_zero_cell_order': [row[0] for row in cells], 'ordered_run_ids': ids,
               'run_ids_sha256': hashlib.sha256(canonical).hexdigest(),
               'heavy_run_ids': heavy, 'heavy_run_count': len(heavy), 'light_run_count': len(ids) - len(heavy),
               'execution_ready': False, 'source_or_model_scan_performed': False, 'router_executed': False,
               'scope': 'Exact prospective order/count input for the resource forecast, not source/config/parser qualification or execution approval.'}
    write(out / 'ORDER_DISK_COUNT_PREVIEW.json', payload)
    print(json.dumps({'status': 'ORDER_PREVIEW_ONLY', 'artifact': identity(out / 'ORDER_DISK_COUNT_PREVIEW.json')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet-window-open', action='store_true')
    parser.add_argument('--stage', choices=list(EXPECTED), required=True)
    parser.add_argument('--block', type=int, choices=(0, 1), required=True)
    parser.add_argument('--segment', type=int, choices=(0, 1, 2, 3))
    parser.add_argument('--bindings', type=Path)
    parser.add_argument('--order-preview-only', action='store_true')
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--order-seed', type=int, required=True)
    parser.add_argument('--first-block-spec', type=Path)
    parser.add_argument('--first-block-sha256')
    args = parser.parse_args()
    if not args.quiet_window_open:
        raise SystemExit('Explicit later owner-allocated generation slot required')
    if (args.stage == 'runtime') != (args.segment is not None):
        raise SystemExit('Runtime requires a contiguous segment0..3; other serving stages are not segmented')
    if not args.order_preview_only and args.bindings is None:
        raise SystemExit('Exact frozen source/config/runtime/forecast bindings are required')
    sys.dont_write_bytecode = True
    with LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = args.out_dir.resolve()
        out.mkdir(parents=True, exist_ok=False)
        try:
            if args.order_preview_only:
                preview_order(args, out)
                return
            wrapper, runner = load_wrapper()
            bindings = json.loads(args.bindings.read_text())
            if bindings.get('schema') != 'finite-campaign-selected-bindings-v4' or bindings.get('owner_selections_frozen') is not True:
                raise ValueError('Explicit exact owner selections must be frozen, not inferred')
            runtime_selection = None
            if args.stage == 'runtime':
                runtime_selection = json.loads(RUNTIME_SELECTION.read_text())
                if args.order_seed != 202610211930 or runtime_selection['order_seed'] != 202610211930:
                    raise ValueError('Runtime order seed was fixed before outcomes at202610211930')
                if runtime_selection['memory_admission'] != wrapper.plan_binding():
                    raise ValueError('Frozen runtime admission binding differs from actual qualified wrapper')
                fixed = {name: {'source': runtime_selection['source_B'], 'selector_product': 'finite20-lean-k3'} for name in POINT}
                if 'point_products' in bindings and bindings['point_products'] != fixed:
                    raise ValueError('Runtime candidate selections are fixed Source B+finite20k3, not outcome-dependent')
                bindings['point_products'] = fixed
                if 'old_native_source' in bindings and bindings['old_native_source'] != runtime_selection['old_native']:
                    raise ValueError('No old metadata clone is authorized without a concrete eligibility blocker')
                bindings['old_native_source'] = runtime_selection['old_native']
            count = json.loads(COUNT_FREEZE.read_text())
            if count['totals']['remaining_prevalidation_maximum'] != 1083:
                raise ValueError('Accepted finite count ledger changed')
            forecast_ref = checked_ref(bindings['resource_forecast'])
            common = [identity(args.bindings), identity(__file__), identity(COUNT_FREEZE), identity(CORRECTION),
                      identity(WRAPPER), identity(BASE), forecast_ref,
                      identity(ROOT / 'protocol/STORAGE_STAGING_AMENDMENT_V5.json'),
                      identity(ROOT / 'protocol/RESOURCE_FORECAST_INPUTS_V4.json')]
            common += [checked_ref(ref) for ref in bindings['qualification_receipts']]
            if runtime_selection:
                common.append(identity(RUNTIME_SELECTION))
                common += [checked_ref(runtime_selection[role]['qualification']) for role in ('source_B', 'old_native')]
                common += [checked_ref(ref) for ref in runtime_selection['scoped_config_bindings'].values()]
            if bindings.get('artifact_retention_policy'):
                common.append(checked_ref(bindings['artifact_retention_policy']))
            forecast = json.loads(Path(forecast_ref['path']).read_text())
            disk_stage_key = f'{args.stage}:b{args.block}' + (f':s{args.segment}' if args.segment is not None else '')
            disk_forecast = forecast.get('disk_stages', {}).get(disk_stage_key)
            if not isinstance(disk_forecast, dict):
                raise ValueError('Exact predeclared disk forecast missing for ' + disk_stage_key)
            required_disk = disk_forecast['required_disk_free_bytes']
            if type(required_disk) is not int or required_disk <= 0:
                raise ValueError('Positive explicit whole-block disk forecast and reserve required')
            planned = disk_forecast['planned_stage_output_bytes']
            reserve = disk_forecast['reserve_bytes']
            if (type(planned) is not int or planned <= 0 or type(reserve) is not int or reserve < 1_000_000_000
                    or required_disk < planned + reserve):
                raise ValueError('Disk forecast must include exact contiguous stage outputs and at least1e9 reserve')
            available_disk = shutil.disk_usage(out).free
            write(out / 'GENERATION_DISK_ADMISSION.json', {'forecast': forecast_ref, 'observed_free_bytes': available_disk,
                'required_free_bytes': required_disk, 'decision': 'admitted' if available_disk >= required_disk else 'rejected',
                'disk_stage_key': disk_stage_key,
                'scope': 'One predeclared contiguous randomized stage, no guarantee, no family-wise reordering or deletion'})
            if available_disk < required_disk:
                raise RuntimeError('Insufficient observed disk for the complete block plus reserve; stop')
            admission = {'snapshot': wrapper.memory_snapshot(), 'scope': 'Generation before source scan only; no router launch'}
            try:
                admission['observed'] = wrapper.check_memory(admission['snapshot'], {
                    'sampled_group_rss_stop_bytes': STOP, 'min_mem_available_bytes': 6_500_000_000})
                admission['decision'] = 'admitted'
            except (OSError, ValueError, TypeError, KeyError) as error:
                admission.update(decision='rejected', error=repr(error))
            write(out / 'GENERATION_MEMORY_ADMISSION.json', admission)
            if admission['decision'] != 'admitted':
                raise RuntimeError('Generation admission rejected; no source scan or automatic retry')
            configs = ({'finite20-lean-k3': checked_ref(runtime_selection['single_selector_for_all14']['config'])}
                       if runtime_selection else policies(out, common))
            sources = {}
            template_path = ROOT / 'experiments/certified-k3k5-all240-methodology-v1/all240-methodology-plan.json'
            common.append(identity(template_path))
            template = json.loads(template_path.read_text())['runs'][0]
            originals = [identity(ROOT / 'protocol' / name) for name in
                         ('TUNE_PROTOCOL_V1.md', 'POINT_LATTICE_STAGING_V1.md', 'TUNE_SCOPE_AMENDMENT_V2.md')]
            common.extend(originals)
            block_one, registry_refs = [], [identity(PANEL / 'registry.json')]
            if args.stage == 'runtime':
                if set(bindings['point_products']) != set(POINT):
                    raise ValueError('Exactly eight candidate operating products must be frozen')
                old_plan_path = ROOT / 'experiments/initial-source-quality-tune-v3-seed/plan.json'
                old_plan_ref = identity(old_plan_path)
                if old_plan_ref['sha256'] != '3316fc768131a56f17a58f5c0231494cb0b769baea9345a9b68d59e1a1109ac9':
                    raise ValueError('Archived initial24 source/control plan changed')
                common.append(old_plan_ref)
                old_runs = json.loads(old_plan_path.read_text())['runs']
                old_template_ids = {'raptor': 'raptor-control', 'raptor_early': 'raptor-early-control',
                                    'mc_raptor': 'mc-early-control', 'mc_raptor_early': 'mc-early-control',
                                    'ultra_transfer_complete_capped': 'ultra-capped-control',
                                    'ultra_cap_safe_stay_witness_subset_v1': 'ultra-capped-control'}
                for product, (algorithm, scoped) in {**POINT, **OLD}.items():
                    choice = {'source': bindings.get('old_native_source', old_descriptor()), 'selector_product': 'finite20-lean-k3'} if product in OLD else bindings['point_products'][product]
                    policy = choice['selector_product']
                    if policy not in POLICY_IDS or not policy.endswith('-k3'):
                        raise ValueError('Runtime products must keep an existing top3 policy')
                    if algorithm not in ('mc_raptor', 'mc_raptor_early') and policy != 'finite20-lean-k3':
                        raise ValueError('Non-Mc runtime slots retain finite20 lean top3 baseline')
                    selected = source_binding(choice['source'], runner, sources, common)
                    if product in OLD and (Path(selected['native_origin']).name != 'bench-v3-control'
                            or selected['source']['go_source_hash_sha256'] != old_descriptor()['go_source_sha256']
                            or selected['binary']['sha256'] != old_descriptor()['binary']['sha256']):
                        raise ValueError('All six old native controls must retain their exact old source/binary')
                    for window in WINDOWS:
                        original = template
                        if product in OLD:
                            matches = [spec for spec in old_runs if spec['variant_id'] == old_template_ids[algorithm]
                                       and spec['window'] == window and spec['block'] == 0]
                            if len(matches) != 1:
                                raise ValueError('Exact archived native control/window contract missing')
                            original = matches[0]
                        base = point_spec(original, product, algorithm, scoped, selected, window, configs[policy], common)
                        for gc, heap in CELLS:
                            spec = copy.deepcopy(base)
                            spec.update(id=f'runtime-{product}-{window}-gc{gc}-{heap}', env={'GOGC': gc, 'GOMEMLIMIT': heap})
                            block_one.append(spec)
            elif args.stage == 'selectors':
                selected = source_binding(bindings['selector_engine'], runner, sources, common)
                if Path(selected['native_origin']).name != 'bench-safe-fill-B-q01':
                    raise ValueError('All twelve serving products need the same already qualified Source B engine')
                env = runtime(bindings['selector_runtime'])
                for policy in POLICY_IDS:
                    for window in WINDOWS:
                        spec = point_spec(template, policy, 'mc_raptor_early', None, selected, window, configs[policy], common)
                        spec.update(id=f'selector-{policy}-{window}', env=env, selector_serving_only=True)
                        block_one.append(spec)
            elif args.stage == 'caps':
                env = runtime(bindings['cap_runtime'])
                if set(bindings['cap_products']) != {'mc', 'mc-early', 'tb'}:
                    raise ValueError('Freeze exactly ordinary/Early Mc and one TB source/config branch')
                for product, algorithm in [('mc', 'mc_raptor'), ('mc-early', 'mc_raptor_early')]:
                    choice = bindings['cap_products'][product]
                    if not choice['selector_product'].endswith('-k3') or choice['selector_product'] not in POLICY_IDS:
                        raise ValueError('Mc cap selector must be a declared top3 product')
                    selected = source_binding(choice['source'], runner, sources, common)
                    for cap in (100000, 250000, 500000, 1000000):
                        for window in WINDOWS:
                            spec = point_spec(template, product, algorithm, None, selected, window, configs[choice['selector_product']], common)
                            replace_flag(spec['argv'], '-max-labels', cap)
                            spec.update(id=f'cap-{product}-labels{cap}-{window}', env=env, declared_label_ceiling=cap)
                            block_one.append(spec)
                choice = bindings['cap_products']['tb']
                algorithm = choice['algorithm']
                if algorithm not in ('trip_based_capped', 'trip_based_capped_answer_walk_ties'):
                    raise ValueError('Exactly one predeclared eligible TB branch required')
                selected = source_binding(choice['source'], runner, sources, common)
                for cap in (5000000, 25000000, 100000000, 150000000):
                    original = ROOT / 'configs/trip_based_capped-transfers100000000-closure1000000.json'
                    common.append(identity(original))
                    config = json.loads(original.read_text())
                    config['trip_based']['max_precomputed_transfers'] = cap
                    path = out / 'configs' / f'tb-retained-links-{cap}.json'
                    write(path, config)
                    common.append(identity(path))
                    for window in WINDOWS:
                        spec = point_spec(template, 'tb', algorithm, None, selected, window, configs['finite20-lean-k3'], common)
                        replace_flag(spec['argv'], '-scoped-config', path)
                        spec.update(id=f'cap-tb-links{cap}-{window}', env=env, declared_retained_link_ceiling=cap)
                        block_one.append(spec)
            else:
                block_one, registry_refs = native_specs(common)
                composition_path = ROOT / 'source-evidence/native-v5/COMPOSITION.json'
                composition = json.loads(composition_path.read_text())
                common.append(identity(composition_path))
                for spec in block_one:
                    role = composition['roles'][spec['source_roots'][0].split('bench-native-v5-')[-1]]
                    binary = next(ref for ref in role['binaries'].values() if ref['path'] == spec['argv'][0])
                    selected = source_binding({'source_root': role['source_root'], 'go_source_sha256': role['go_source_hash_sha256'],
                                               'binary': binary, 'qualification': identity(composition_path)}, runner, sources, common)
                    spec['source_policy_binding'] = selected
            if len(block_one) * 2 != EXPECTED[args.stage]:
                raise ValueError('Stage expansion differs from the exact finite accepted count')
            parser_prototypes = {}
            if args.stage == 'runtime':
                for spec in block_one:
                    key = parser_class_key(spec)
                    if key not in parser_prototypes:
                        parser_prototypes[key] = copy.deepcopy(spec)
                if len(parser_prototypes) != 56:
                    raise ValueError('Runtime must have exactly32 Source B and24 old-control parser classes')
            random.Random(args.order_seed).shuffle(block_one)
            comparison = {'stage': args.stage, 'order_seed': args.order_seed,
                          'owner_bindings_sha256': identity(args.bindings)['sha256'],
                          'block_zero_cell_order': [spec['id'] for spec in block_one],
                          'source_go_identities': [{'path': row['path'], 'go_source_hash_sha256': row['go_source_hash_sha256']}
                                                   for row in sources.values()],
                          'policy_config_sha256': {name: ref['sha256'] for name, ref in configs.items()},
                          'original_registry_sha256': [ref['sha256'] for ref in registry_refs]}
            first_block_ref = None
            if args.block == 1 or (args.stage == 'runtime' and args.segment != 0):
                if not args.first_block_spec or not args.first_block_sha256:
                    raise ValueError('Second block requires the exact first-block spec path+SHA binding')
                first_block_ref = checked_ref({'path': str(args.first_block_spec), 'sha256': args.first_block_sha256})
                first_block = json.loads(Path(first_block_ref['path']).read_text())
                if (first_block.get('block') != 0 or first_block.get('balanced_comparison_binding') != comparison
                        or (args.stage == 'runtime' and first_block.get('segment') != 0)):
                    raise ValueError('Second block source/config/runtime/seed/cell order differs from frozen first block')
                common.append(first_block_ref)
            specs = []
            sequence = block_one if args.block == 0 else list(reversed(block_one))
            segment_start = 84 * args.segment if args.segment is not None else 0
            if args.segment is not None:
                sequence = sequence[segment_start:segment_start + 84]
            for block, sequence in [(args.block, sequence)]:
                for position, raw in enumerate(sequence):
                    spec = copy.deepcopy(raw)
                    spec.update(id=f'b{block}-' + raw['id'], block=block, position=segment_start + position)
                    if args.segment is not None:
                        spec['contiguous_storage_stage'] = args.segment
                    specs.append(spec)
            heavy_ids = [spec['id'] for spec in specs if 'ultra-subset' in spec['variant_id']]
            light_ids = [spec['id'] for spec in specs if spec['id'] not in heavy_ids]
            ids_sha = wrapper.canonical_hash([spec['id'] for spec in specs])
            if (disk_forecast.get('run_ids_sha256') != ids_sha
                    or disk_forecast.get('heavy_run_count') != len(heavy_ids)
                    or disk_forecast.get('light_run_count') != len(light_ids)
                    or planned < len(heavy_ids) * 51_000_000):
                raise ValueError('Stage-specific exact order/heavy/light count or conservative artifact floor mismatch')
            write(out / 'CONTIGUOUS_STAGE_DISK_ACCOUNTING.json', {'stage_key': disk_stage_key,
                'run_ids_sha256': ids_sha, 'heavy_run_ids': heavy_ids, 'light_run_ids': light_ids,
                'heavy_run_count': len(heavy_ids), 'light_run_count': len(light_ids),
                'forecast': forecast_ref, 'archive_policy': bindings.get('artifact_retention_policy'),
                'scope': 'Storage pauses only between predeclared contiguous stages; no scoring or timing-order revision'})
            overrides = bindings.get('not_offered_rows', {})
            all_allowed_ids = {'b' + str(block) + '-' + spec['id'] for block in (0, 1) for spec in block_one}
            if set(overrides) - all_allowed_ids:
                raise ValueError('Refusal map names a tuple outside the exact frozen stage')
            states = []
            allowed_refusal = {'NOT_OFFERED_SOURCE_QUALIFICATION', 'NOT_OFFERED_MEMORY_FORECAST'}
            memory_forecasts = forecast.get('memory_forecasts', {})
            for spec in specs:
                refusal = overrides.get(spec['id'])
                raw_id = spec['id'].split('-', 1)[1]
                predicted = memory_forecasts.get(raw_id)
                if not refusal:
                    upper = predicted.get('conservative_peak_rss_upper_bytes') if isinstance(predicted, dict) else None
                    if (type(upper) is not int or not 0 < upper < STOP
                            or predicted.get('classification') != 'safe_to_offer_under_declared_forecast'
                            or not predicted.get('observed_basis') or not predicted.get('representation_and_growth_assumptions')):
                        refusal = {'state': 'NOT_OFFERED_MEMORY_FORECAST', 'evidence': forecast_ref,
                                   'reason': 'Missing, unsafe, unknown or incomplete prospective memory forecast for this exact descendant; no retry or cap substitution.'}
                if refusal:
                    if refusal.get('state') not in allowed_refusal or not refusal.get('reason'):
                        raise ValueError('Explicit qualification/forecast refusal reason and evidence required')
                    common.append(checked_ref(refusal['evidence']))
                states.append({'id': spec['id'], **(refusal or {'state': 'PLANNED_UNSTARTED'})})
            entries, seen = [], {}
            for ref in registry_refs:
                checked = checked_ref(ref)
                common.append(checked)
                payload = json.loads(Path(checked['path']).read_text())
                for entry in payload['entries']:
                    key = entry['workload']['path']
                    if key in seen and seen[key] != entry:
                        raise ValueError('Original registry conflict; never rewrite a workload')
                    if key not in seen:
                        seen[key] = entry
                        entries.append(entry)
            source_freeze = out / 'SOURCE_CONFIG_BINDING.json'
            unique = {ref['path']: ref for ref in common + list(configs.values())}
            write(source_freeze, {'status': 'GENERATED_SOURCE_CONFIG_BINDINGS_ACTUAL_PARSER_AND_ENVELOPE_PREFLIGHT_PENDING',
                                  'inputs': list(unique.values()), 'sources': list(sources.values()),
                                  'memory_admission': wrapper.plan_binding(), 'stage': args.stage})
            registry = out / 'ORIGINAL_WORKLOAD_REGISTRY_UNION.json'
            write(registry, {'schema': 'predeclared-workload-registry-v1', 'source_manifest': identity(source_freeze),
                             'entries': entries, 'scope': 'Original entries retained exactly; no derived or filtered workloads'})
            for spec in specs:
                spec['inputs'] = list(dict.fromkeys(spec.get('inputs', []) + [str(WRAPPER), str(BASE), str(source_freeze),
                    str(COUNT_FREEZE), str(CORRECTION), str(args.bindings.resolve()), str(Path(__file__).resolve())]))
                wrapper.envelope(spec, runner.campaign_gate)
                if any('csa' in value.lower() for name in ('-algorithm', '-algorithms')
                       for values in runner.campaign_gate.flags(spec['argv'], name) for value in values.split(',')):
                    raise ValueError('No CSA-family offer is permitted')
            refused = {row['id'] for row in states if row['state'] != 'PLANNED_UNSTARTED'}
            artifact = out / 'PROSPECTIVE_RUN_SPECS.json'
            write(artifact, {'schema': 'prospective-finite-run-specs-v4-NOT-A-RUNNER-PLAN', 'stage': args.stage,
                              'block': args.block, 'balanced_comparison_binding': comparison,
                              'segment': args.segment, 'segment_global_start_position': segment_start,
                              'first_block_spec': first_block_ref,
                              'execution_ready': False, 'router_executed': False,
                              'exact_frozen_offer_count_this_stage': len(specs),
                              'exact_frozen_offer_count_whole_block': EXPECTED[args.stage] // 2,
                              'exact_frozen_stage_count_both_blocks': EXPECTED[args.stage], 'order_seed': args.order_seed,
                              'runner_plan_fields': {'schema': 'sg-coldstart-campaign-v2', 'evaluation_mode': 'diagnostic',
                                  'dataset_tier': 'public_modeled_pipeline_validation', 'continue_on_failure': False,
                                  'memory_admission': wrapper.plan_binding(), 'workload_registry': identity(registry)},
                              'run_specs': specs, 'offered_run_ids_after_forecast': [spec['id'] for spec in specs if spec['id'] not in refused],
                              'parser_equivalence_prototypes': parser_prototypes,
                              'state_rows': states,
                              'next_gate': 'New actual source-matched parser plus immutable runner.prepare_run preflight; then create a separate new executable plan binding their reports. No source/flag changes, routing, or automatic retries.'})
            expected_here = 84 if args.segment is not None else EXPECTED[args.stage] // 2
            if sum(1 for _ in states) != expected_here:
                raise ValueError('Lost prospective tuple accounting')
            write(out / 'GENERATION_RECEIPT.json', {'status': 'SPEC_GENERATION_ONLY_NO_PARSER_NO_ROUTER',
                'artifact': identity(artifact), 'stage': args.stage, 'total_slots': len(states),
                'block': args.block, 'whole_stage_slots_both_blocks': EXPECTED[args.stage],
                'segment': args.segment,
                'explicitly_unoffered': len(refused), 'remaining_prevalidation_global_ceiling': 1083,
                'actual_parser_checks_run_here': 0, 'actual_runner_prepare_run_checks_here': 0})
            print(json.dumps({'status': 'SPECS_GENERATED_NOT_PREFLIGHTED_OR_ROUTED', 'artifact': identity(artifact)}))
        except BaseException as error:
            write(out / 'FAILED.json', {'status': 'FAILED_CREATE_ONLY_ARTIFACTS_PRESERVED', 'error': repr(error),
                                       'router_executed': False, 'automatic_retry': False})
            raise


if __name__ == '__main__':
    main()
