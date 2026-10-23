#!/usr/bin/env python3
"""STATIC DRAFT: caps/native source-matched parsers and actual runner envelopes.

No routing. Not imported, compiled, tested, hashed or qualified. Use only in a
later explicitly allocated quiet slot, after independent all8 closure review.
Reuse existing generator/runtime-preparer operations, not a new campaign runner.
Prepared plan metadata lives separately from still-absent measurement/evaluation
roots. Their exact prospective lossless-storage admission remains a launch gate.
"""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path('/workspace/shared/sg-coldstart/campaign-v2-20261021')
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
GENERATOR = ROOT / 'harness/generate_finite_campaign_specs_v4.py'
PARSER_HELPER = ROOT / 'harness/prepare_runtime_stage_v6.py'
WRAPPER = ROOT / 'harness/run_campaign_memory_admission_v1.py'
BASE = ROOT / 'harness/run_campaign.py'
WRAPPER_SHA = '48a0e60df21641472796c4c52cc6168926c1a228048fea7acc13f6314e347ec9'
BASE_SHA = '206076513f4fb023e38deb9aee96de07c8c885b579e716c56350c7f73ff4480b'
NATIVE_PRIMARY = ROOT / 'experiments/native-primary-tune-v5-envelope/plan.json'
NATIVE_DOMAIN = ROOT / 'experiments/native-domain-tune-v5-envelope/plan.json'
COMPOSITION = ROOT / 'source-evidence/native-v5/COMPOSITION.json'
STOP = 5_500_000_000
MINIMUM = 6_500_000_000
EXPECTED = {'caps': 48, 'native': 108}


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def checked(reference):
    require(isinstance(reference, dict) and reference.get('path') and reference.get('sha256'),
            'Exact path/SHA256 reference required')
    actual = identity(reference['path'])
    require(all(actual.get(key) == value for key, value in reference.items()
                if key in {'path', 'sha256', 'bytes'}), 'Changed input: ' + str(reference['path']))
    return actual


def load(reference):
    reference = checked(reference)
    return json.loads(Path(reference['path']).read_text()), reference


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def observe_memory(prefix, gen, wrapper, envelope=None):
    record = {'snapshot': wrapper.memory_snapshot(), 'scope': 'Preparation only; no serving or hard-cap claim'}
    try:
        record['observed'] = wrapper.check_memory(record['snapshot'], envelope or {
            'sampled_group_rss_stop_bytes': STOP, 'min_mem_available_bytes': MINIMUM})
        record['decision'] = 'admitted'
    except (OSError, ValueError, TypeError, KeyError) as error:
        record.update(decision='rejected', error=repr(error))
    if prefix is not None:
        gen.write(prefix, record)
    require(record['decision'] == 'admitted', 'Observed preparation memory rejection; no automatic retry')
    return record


def future_roots(control, output):
    roots = [Path(value) for value in control['future_measurement_and_evaluation_roots']]
    require(roots and len(set(roots)) == len(roots), 'Exact distinct future output roots required')
    for root in roots:
        require(root.is_absolute() and ROOT in root.parents, 'Future output root must be absolute and campaign-contained')
        require(root.resolve(strict=False) == root, 'Future root must not traverse symlinks or dot components')
        require(not root.exists() and not root.is_symlink(), 'Future output root already exists: ' + str(root))
        require(root != output and root not in output.parents and output not in root.parents,
                'Preparation metadata and future writer roots must be disjoint')
    return roots


def operation_disk(control, path):
    forecast = control['preparation_disk_forecast']
    largest = forecast['maximum_single_operation_output_bytes']
    require(type(largest) is int and largest > 0 and largest <= forecast['planned_output_bytes'],
            'Positive conservative largest-parser/envelope output bound required')
    require(shutil.disk_usage(path).free >= forecast['reserve_bytes'] + largest,
            'Observed preparation operation disk admission rejected; no retry')


def assert_cap_contracts(rows, selected, policy_hashes, gen):
    require(set(selected['cap_products']) == {'mc', 'mc-early', 'tb'}, 'Exactly three frozen cap adapters required')
    require((selected['cap_runtime']['GOGC'], selected['cap_runtime']['GOMEMLIMIT']) in gen.CELLS,
            'Common cap runtime outside the original six cells')
    census = set()
    for row in rows:
        require(row['env'] == selected['cap_runtime'] and row.get('requested_selector_limit') == 3,
                'Cap runtime or top3 budget changed by cell')
        flag = lambda name: gen_value(row['argv'], name)
        if 'declared_label_ceiling' in row:
            cap = row['declared_label_ceiling']
            require(cap in (100000, 250000, 500000, 1000000), 'Undeclared Mc cap')
            product = {'mc_raptor': 'mc', 'mc_raptor_early': 'mc-early'}.get(flag('-algorithm'))
            require(product is not None and flag('-max-labels') == str(cap), 'Mc adapter/label-cap mismatch')
        else:
            cap, product = row.get('declared_retained_link_ceiling'), 'tb'
            require(cap in (5000000, 25000000, 100000000, 150000000), 'Undeclared TB cap')
            require(flag('-algorithm') == selected['cap_products']['tb']['algorithm'] and
                    flag('-algorithm') in ('trip_based_capped', 'trip_based_capped_answer_walk_ties'),
                    'TB second branch or source-dependent branch swap')
            original = json.loads((ROOT / 'configs/trip_based_capped-transfers100000000-closure1000000.json').read_text())
            original['trip_based']['max_precomputed_transfers'] = cap
            require(json.loads(Path(flag('-scoped-config')).read_text()) == original,
                    'TB cap changed config beyond the predeclared retained-link ceiling')
        require(row['window'] in gen.WINDOWS, 'Unknown cap window')
        source = selected['cap_products'][product]['source']
        policy = selected['cap_products'][product]['selector_product']
        require(policy in gen.POLICY_IDS and policy.endswith('-k3') and
                (product != 'tb' or policy == 'finite20-lean-k3'), 'Undeclared cap selector product')
        require(identity(flag('-preference-scenarios'))['sha256'] == policy_hashes[policy],
                'Cap selector/config changed per cell')
        binding = row['source_policy_binding']
        require(binding['source']['path'] == source['source_root'] and
                binding['source']['go_source_hash_sha256'] == source['go_source_sha256'] and
                row['argv'][0] == binding['binary']['path'] == source['binary']['path'] and
                binding['binary']['sha256'] == source['binary']['sha256'], 'Cap source/binary changed per cell')
        item = (product, cap, row['window'])
        require(item not in census, 'Duplicate cap tuple')
        census.add(item)
    require(len(census) == 48, 'Lost cap tuples')


def gen_value(argv, name):
    positions = [index for index, value in enumerate(argv) if value == name]
    require(len(positions) == 1 and positions[0] + 1 < len(argv), 'Missing/ambiguous flag: ' + name)
    return argv[positions[0] + 1]


def assert_fixed_block_order(payload):
    """Pure metadata assertion; no new order, source choice, or process offer."""
    stage, block = payload.get('stage'), payload.get('block')
    require(stage in EXPECTED and type(block) is int and block in (0, 1), 'Unknown fixed finite lane/block')
    binding = payload['balanced_comparison_binding']
    zero = binding['block_zero_cell_order']
    require(isinstance(zero, list) and len(zero) == len(set(zero)) == EXPECTED[stage],
            'Wrong exact original block-zero cell inventory')
    require(type(payload.get('order_seed')) is int and payload['order_seed'] == binding.get('order_seed'),
            'Lane order seed differs from frozen comparison')
    ordered = zero if block == 0 else list(reversed(zero))
    rows = payload['run_specs']
    require([row['id'] for row in rows] == [f'b{block}-' + cell for cell in ordered],
            'Not the exact frozen block-zero order or full block-one reverse')
    require(all(type(row.get('position')) is int and row['position'] == index
                and type(row.get('block')) is int and row['block'] == block
                for index, row in enumerate(rows)), 'Original fixed block/position metadata changed')
    require(payload.get('segment') is None, 'Cap/native blocks cannot be split into new storage segments')


def assert_offer_accounting(payload, forecast):
    """Preserve every fixed position; unknown resource forecasts never offer."""
    stage = payload['stage']
    states = payload['state_rows']
    offered_list = payload['offered_run_ids_after_forecast']
    offered = set(offered_list)
    require(len(offered_list) == len(offered), 'Duplicate offered run ID')
    require(len(states) == len({row['id'] for row in states}) == EXPECTED[stage]
            and len({row['id'] for row in payload['run_specs']}) == EXPECTED[stage]
            and {row['id'] for row in states} == {row['id'] for row in payload['run_specs']},
            'Lost finite state accounting')
    require(offered == {row['id'] for row in states if row['state'] == 'PLANNED_UNSTARTED'},
            'Offered/state-row mismatch')
    for row in payload['run_specs']:
        if row['id'] not in offered:
            continue
        prediction = forecast.get('memory_forecasts', {}).get(row['id'].split('-', 1)[1], {})
        upper = prediction.get('conservative_peak_rss_upper_bytes')
        require(type(upper) is int and 0 < upper < STOP and
                prediction.get('classification') == 'safe_to_offer_under_declared_forecast' and
                prediction.get('observed_basis') and prediction.get('representation_and_growth_assumptions'),
                'Offered descendant lacks its exact safe prospective memory forecast')
    return offered, states


def native_originals(control, gen):
    primary, primary_ref = load(control['native_originals']['primary'])
    domain, domain_ref = load(control['native_originals']['domain'])
    composition, composition_ref = load(control['native_originals']['composition'])
    require(primary_ref['path'] == str(NATIVE_PRIMARY) and domain_ref['path'] == str(NATIVE_DOMAIN)
            and composition_ref['path'] == str(COMPOSITION), 'Authoritative original native paths required')
    original = [row for row in primary['runs'] if row['family'] in {'range_raptor', 'tad', 'core_ch'}
                or (row['family'] == 'trip_based' and row['window'] == gen.WINDOWS[3])]
    original += [row for row in domain['runs'] if
                 row['family'] == 'tp_source_domain_retained_fixed_caps_experimental_v1'
                 and row['window'] == gen.WINDOWS[3]]
    require(len(original) == 18 and len({row['id'] for row in original}) == 18,
            'Exactly18 original successful source/window contracts required')
    census = {family: sum(row['family'] == family for row in original) for family in
              ('range_raptor', 'tad', 'core_ch', 'trip_based', 'tp_source_domain_retained_fixed_caps_experimental_v1')}
    require(list(census.values()) == [8, 4, 4, 1, 1], 'Native18 contract census changed')
    return {row['id']: row for row in original}, composition, [primary_ref, domain_ref, composition_ref]


def assert_native_contract(row, original, composition, gen):
    expected_argv = list(original['argv'])
    # Existing native source/driver/config/query/cap flags remain byte-for-byte;
    # change the existing guard where supported, never invent a new driver flag.
    if '-rss-safety-stop' in expected_argv:
        gen.replace_flag(expected_argv, '-rss-safety-stop', STOP)
    require(row['argv'] == expected_argv, 'Native argv changed beyond predeclared RSS guard')
    for field in ('cwd', 'source_roots', 'family', 'variant_id', 'window', 'timeout_s',
                  'contrast', 'equal_caps_control', 'walking_metric'):
        require(row.get(field) == original.get(field), 'Changed original native contract field: ' + field)
    require(set(original.get('inputs', [])) <= set(row.get('inputs', [])), 'Original native input ancestry lost')
    require(row['rss_safety_stop_bytes'] == STOP, 'Native supervisor stop changed')
    require((row['env']['GOGC'], row['env']['GOMEMLIMIT']) in gen.CELLS, 'Unknown runtime cell')
    require({key: value for key, value in row['env'].items() if key not in {'GOGC', 'GOMEMLIMIT'}}
            == {key: value for key, value in original.get('env', {}).items() if key not in {'GOGC', 'GOMEMLIMIT'}},
            'Changed non-runtime native environment')
    roles = [role for role in composition['roles'].values() if role['source_root'] == original['cwd']]
    require(len(roles) == 1, 'Original COMPOSITION role missing/ambiguous')
    role = roles[0]
    binary = next((value for value in role['binaries'].values() if value['path'] == row['argv'][0]), None)
    require(binary is not None, 'Original driver binary not in COMPOSITION')
    binding = row['source_policy_binding']
    require(binding['source']['path'] == original['cwd']
            and binding['source']['go_source_hash_sha256'] == role['go_source_hash_sha256']
            and binding['binary']['sha256'] == binary['sha256'], 'Native source/binary substitution')
    return role


def assert_native_census(rows, originals, composition, gen):
    roles, census = {}, set()
    for row in rows:
        contract = row.get('original_native_contract_id')
        require(contract in originals, 'Unfrozen native contract offered')
        roles[row['id']] = assert_native_contract(row, originals[contract], composition, gen)
        cell = (contract, row['env']['GOGC'], row['env']['GOMEMLIMIT'])
        require(cell not in census, 'Duplicate original native/runtime tuple')
        census.add(cell)
    require(census == {(contract, gc, heap) for contract in originals for gc, heap in gen.CELLS},
            'Native contract/runtime Cartesian census changed')
    return roles


def objects(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.startswith('{')]


def input_capture(argv, row, prefix, cpus, gen, wrapper, runner, helper):
    name = Path(argv[0]).name
    require(name.startswith('inputpreflight') or
            (name.startswith(('familybench', 'profilebench', 'tadbench', 'corechgraphbench'))
             and argv.count('-input-only') == 1), 'Only qualified parser/input-only children may launch')
    env = dict(runner.campaign_environment(), GOGC='50', GOMEMLIMIT='4GiB')
    return helper.capture(argv, row['cwd'], env, prefix, cpus, gen, wrapper, runner)


def parser_check(key, row, role, control, out, cpus, gen, wrapper, runner, helper):
    operation_disk(control, out)
    observe_memory(out / (key + '.before-input-hash-admission.json'), gen, wrapper)
    flag = lambda name: runner.campaign_gate.flags(row['argv'], name)
    dataset, queries = identity(flag('-dataset')[0]), identity(flag('-queries')[0])
    config = identity(flag('-scoped-config')[0]) if flag('-scoped-config') else None
    preferences = identity(flag('-preference-scenarios')[0]) if flag('-preference-scenarios') else None
    is_old = Path(row['source_policy_binding']['native_origin']).name == 'bench-v3-control'
    driver = Path(row['argv'][0]).name.split('-native-v5-')[0]
    algorithm = (flag('-algorithm') or flag('-algorithms') or [row.get('family')])[0]
    generic_value = None
    if role is not None or is_old:
        if role is not None:
            generic_binary = checked(role['binaries']['inputpreflight'])
        else:
            receipt, _ = load(control['old_source_matched_helper_receipt'])
            generic_binary = checked(receipt['binary'])
            require(receipt['source_before_after'] == row['source_policy_binding']['source'],
                    'Old strict helper is not bound to the exact original source identity')
        generic = [generic_binary['path'], '-dataset', dataset['path'], '-queries', queries['path'],
                   '-schema', 'profile-from-point' if driver == 'profilebench' else 'point',
                   '-algorithm', algorithm, '-ready-span-seconds', '60', '-max-window-seconds', '600']
        if config:
            generic += ['-scoped-config', config['path']]
        if preferences:
            generic += ['-preferences', preferences['path']]
        operation_disk(control, out)
        stdout, observation = input_capture(generic, row, out / (key + '-generic'), cpus, gen, wrapper, runner, helper)
        values = objects(stdout)
        require(len(values) == 1 and values[0].get('accepted'), 'Strict source-matched generic parser failed')
        generic_value = values[0]
        require(generic_value.get('queries_sha256') == queries['sha256']
                and generic_value.get('dataset_sha256') == dataset['sha256'], 'Generic parser input-byte mismatch')
    if is_old:
        require(generic_value.get('query_count') == 60 and preferences
                and generic_value.get('preferences_sha256') == preferences['sha256'], 'Old cap source/config/input binding mismatch')
        if config:
            require(generic_value.get('scoped_configuration_sha256') == config['sha256'], 'Old scoped-config binding mismatch')
        return {'mode': 'exact_original_source_strict_helper_not_familybench_input_only',
                'prototype': row, 'acceptance': generic_value, 'observation': observation}
    argv = list(row['argv'])
    gen.replace_flag(argv, '-out-dir', out / (key + '-input-only-output'))
    argv.append('-input-only')
    operation_disk(control, out)
    stdout, observation = input_capture(argv, row, out / (key + '-actual'), cpus, gen, wrapper, runner, helper)
    values = objects(stdout)
    require(not any(value.get('event') == 'first_available_answer' for value in values), 'Parser emitted serving output')
    accepted = [value for value in values if value.get('event') == 'input_only_acceptance']
    require(len(accepted) == 1, 'Exactly one actual consuming-driver input-only acceptance required')
    value = accepted[0]
    require((role is not None or value.get('accepted')) and value.get('queries_sha256') == queries['sha256']
            and value.get('dataset_sha256') == dataset['sha256'], 'Actual parser acceptance/input-byte mismatch')
    provenance = value.get('provenance', {})
    require(provenance.get('runtime_matches_build') and provenance.get('runtime_tree_sha256') ==
            row['source_policy_binding']['source']['go_source_hash_sha256'], 'Actual parser source/build mismatch')
    if config:
        require(value.get('scoped_configuration_sha256') == config['sha256'], 'Actual scoped-config binding mismatch')
    if role is not None:
        require(value.get('driver') == driver and value.get('seed_metadata') == generic_value.get('seed_metadata'),
                'Native actual-driver/schema/seed mismatch')
    else:
        require(value.get('query_count') == 60 and value.get('selection', {}).get('algorithm') == algorithm,
                'Cap actual consuming-driver count/algorithm mismatch')
    return {'mode': 'actual_source_matched_consuming_driver_input_only', 'prototype': row,
            'acceptance': value, 'generic_acceptance': generic_value, 'observation': observation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet-window-open', action='store_true')
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--cpus', default='0-3')
    args = parser.parse_args()
    require(args.quiet_window_open, 'Explicit later owner-allocated quiet preparation slot required')
    # No campaign import/hash or output creation occurs before the authoritative
    # fail-immediate lock. Never invoke this CLI under a different outer flock.
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sys.dont_write_bytecode = True
        control_ref = identity(args.control)
        control = json.loads(args.control.read_text())
        require(control.get('schema') == 'remaining-finite-preflight-control-v4'
                and control.get('independent_preparation_inputs_accepted') is True,
                'Independently accepted exact preparation control required')
        output = args.out_dir.resolve()
        require(not output.exists() and not output.is_symlink(), 'Create-only fresh preparation directory required')
        roots = future_roots(control, output)
        forecast = control['preparation_disk_forecast']
        planned, reserve, required = (forecast.get(key) for key in
            ('planned_output_bytes', 'reserve_bytes', 'required_disk_free_bytes'))
        require(all(type(value) is int and value > 0 for value in (planned, reserve, required))
                and reserve >= 1_000_000_000 and required >= planned + reserve,
                'Exact conservative preparation output forecast plus >=1e9 reserve required')
        ancestor = output.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        free = shutil.disk_usage(ancestor).free
        require(free >= required, 'Preparation disk admission rejected before output creation')
        require(identity(WRAPPER)['sha256'] == WRAPPER_SHA and identity(BASE)['sha256'] == BASE_SHA,
                'Qualified wrapper/base identity changed')
        for key, path in (('generator', GENERATOR), ('parser_capture_helper', PARSER_HELPER)):
            require(checked(control[key])['path'] == str(path), 'Wrong existing helper path')
        gen = module(GENERATOR, '_remaining_finite_existing_generator_v4')
        wrapper, runner = gen.load_wrapper()
        initial_memory = observe_memory(None, gen, wrapper)
        payload, specs_ref = load(control['prospective_specs'])
        selected, selected_ref = load(control['selected_bindings'])
        require(payload.get('stage') in EXPECTED and payload.get('block') in (0, 1)
                and payload.get('schema') == 'prospective-finite-run-specs-v4-NOT-A-RUNNER-PLAN'
                and len(payload.get('run_specs', [])) == EXPECTED[payload['stage']], 'Wrong exact finite lane/block count')
        require(selected.get('owner_selections_frozen') is True and
                selected.get('schema') == 'finite-campaign-selected-bindings-v4', 'Owner source/config/runtime selection not frozen')
        require(payload['balanced_comparison_binding']['owner_bindings_sha256'] == selected_ref['sha256'],
                'Prospective specs do not bind exact owner selection')
        assert_fixed_block_order(payload)
        for reference in control['required_independent_gate_refs']:
            checked(reference)
        require(control['required_independent_gate_refs'], 'All8/frontier/scope/forecast independent gate refs required')
        original, composition, native_refs = (native_originals(control, gen) if payload['stage'] == 'native'
                                              else ({}, {}, []))
        if payload['stage'] == 'caps':
            assert_cap_contracts(payload['run_specs'], selected,
                                 payload['balanced_comparison_binding']['policy_config_sha256'], gen)
        helper = module(PARSER_HELPER, '_remaining_finite_existing_capture_v6')
        output.mkdir(parents=True, exist_ok=False)
        try:
            gen.write(output / 'PREPARATION_ADMISSION.json', {'disk': {'observed_free_bytes': free,
                'declared': forecast}, 'memory': initial_memory,
                'future_writer_roots_still_absent': [str(root) for root in roots]})
            parser_dir = output / 'parsers'
            parser_dir.mkdir()
            prototypes = {}
            roles = (assert_native_census(payload['run_specs'], original, composition, gen)
                     if payload['stage'] == 'native' else {})
            for row in payload['run_specs']:
                key = gen.parser_class_key(row)
                prototypes.setdefault(key, row)
            expected_classes = 48 if payload['stage'] == 'caps' else 18
            require(len(prototypes) == expected_classes, 'Exact cap/native parser-equivalence census changed')
            forecast, _ = load(selected['resource_forecast'])
            offered, state_rows = assert_offer_accounting(payload, forecast)
            # Never execute a parser for a forecast-refused class merely to fill
            # an attractive complete parser-bank count. Refusals stay explicit.
            classes = {}
            for key, row in prototypes.items():
                class_offered = [candidate for candidate in payload['run_specs']
                                 if candidate['id'] in offered and gen.parser_class_key(candidate) == key]
                if not class_offered:
                    continue
                prototype = class_offered[0]
                classes[key] = parser_check(key, prototype, roles.get(prototype['id']), control,
                    parser_dir, args.cpus, gen, wrapper, runner, helper)
            bank_path = output / 'PARSER_COVERAGE.json'
            gen.write(bank_path, {'schema': 'remaining-finite-source-matched-parser-coverage-v4',
                'stage': payload['stage'], 'classes': classes, 'all_offered_classes_accepted': True,
                'original_class_inventory_count': len(prototypes), 'router_executed': False})
            specs, envelopes = [], []
            for raw in payload['run_specs']:
                if raw['id'] not in offered:
                    continue
                row = copy.deepcopy(raw)
                require(gen.parser_class_key(row) in classes, 'Offered row lacks exact source-matched parser coverage')
                row['inputs'] = list(dict.fromkeys(row['inputs'] + [str(WRAPPER), str(BASE), str(Path(__file__).resolve()),
                    control_ref['path'], specs_ref['path'], selected_ref['path'], str(bank_path)]
                    + [ref['path'] for ref in native_refs] + [ref['path'] for ref in control['required_independent_gate_refs']]))
                wrapper.envelope(row, runner.campaign_gate)
                specs.append(row)
            plan = dict(payload['runner_plan_fields'], runs=specs, prospective_specs=specs_ref,
                purpose='Existing fixed finite cap/native lane only; original native contracts and every finite state retained.',
                finite_lane={'stage': payload['stage'], 'block': payload['block'], 'all_state_rows': state_rows},
                parser_coverage=gen.identity(bank_path), live_storage_admission_still_required=True)
            wrapper.validate_plan(plan)
            registered = runner.campaign_gate.load_registry(plan, output)
            runner.campaign_gate.reject_execution_claims(plan, final_gate_passed=False)
            for row in specs:
                operation_disk(control, output)
                observe_memory(output / (row['id'] + '.before-envelope-admission.json'), gen, wrapper,
                               wrapper.envelope(row, runner.campaign_gate))
                metadata, *_ = runner.prepare_run(row, Path('/__REMAINING_FINITE_NOT_EXECUTED__') / row['id'],
                    Path('/__NO_REMAINING_FINITE_CAMPAIGN__'), runner.campaign_environment(), args.cpus, .1,
                    registered, inspect_heldout=False)
                expected = row['source_policy_binding']
                require(metadata['binary']['sha256'] == expected['binary']['sha256'] and
                        metadata['sources_before'][0]['go_source_hash_sha256'] == expected['source']['go_source_hash_sha256'],
                        'Actual immutable runner source/binary mismatch')
                require(metadata['workload_gate']['classification'] == 'registered_development' and
                        not metadata['workload_gate']['heldout_detected'] and
                        all(work['classification'] == 'tune' and work['registered']
                            for work in metadata['workload_gate']['workloads']), 'Original tune registry envelope failed')
                envelopes.append(metadata)
            envelope_path = output / 'RUNNER_ENVELOPE_PREFLIGHT.json'
            gen.write(envelope_path, {'status': 'ALL_OFFERED_ACTUAL_PREPARE_RUN_ENVELOPES_PASS',
                'runs': envelopes, 'all_original_state_rows': state_rows, 'router_executed': False})
            for row in specs:
                row['inputs'].append(str(envelope_path))
            future_roots(control, output)
            require(identity(args.control) == control_ref and checked(specs_ref) == specs_ref
                    and checked(selected_ref) == selected_ref, 'Preparation inputs changed')
            plan_path = output / 'PREPARED_PLAN_METADATA_NOT_LAUNCH_AUTHORIZATION.json'
            gen.write(plan_path, plan)
            gen.write(output / 'PREPARATION_FREEZE.json', {
                'status': 'PARSER_AND_ACTUAL_ENVELOPE_PASS_STORAGE_ADMISSION_AND_LIVE_SLOT_PENDING',
                'plan': gen.identity(plan_path), 'prospective_specs': specs_ref,
                'parser_coverage': gen.identity(bank_path), 'actual_envelopes': gen.identity(envelope_path),
                'all_finite_slots': len(state_rows), 'offered': len(specs), 'unoffered': len(state_rows) - len(specs),
                'memory_admission': wrapper.plan_binding(), 'router_executed': False,
                'future_writer_roots_still_absent': [str(root) for root in roots],
                'next_gate': 'Independent review; freeze exact eligible raw/sidecar/METRICS storage paths against this plan before those roots exist; separately allocate live wrapper serving.'})
        except BaseException as error:
            gen.write(output / 'FAILED.json', {'status': 'FAILED_PARTIALS_PRESERVED_NO_RETRY',
                'error': repr(error), 'router_executed': False})
            raise
    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
