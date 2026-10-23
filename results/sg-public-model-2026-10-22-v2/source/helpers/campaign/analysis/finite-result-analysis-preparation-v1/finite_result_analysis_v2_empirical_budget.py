#!/usr/bin/env python3
"""Operational v2 resource revision: source census plus reviewed empirical budgets.

Import is inert and does not import an evaluator/helper/model. This supersedes
only the unadopted 3.1GB constant and the native adapter selection in v1. It is
not qualified merely by existing, and never executes V4, a router or storage.
All previous source, drafts, successful tests and census receipts are preserved.
The sole revision accepts explicitly EMPIRICAL shared output-budget pools rather
than falsely dividing the previously accepted400MB envelope into ten proven
per-file bounds. No numerical margin is invented here, and no fit guarantee is
made. Source-derived terms and empirical terms remain separately labelled.

CLI is the v1 CLI. Binding/qualification/release/resource schemas have suffix-v2.
The numeric request is source-derived, exact mode/window/out, independently
accepted and owner-bound before any view is created. Numerical forecasts are
not supplied by this entrypoint. A missing/null bound is a hard failure.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import importlib.util
import os
from pathlib import Path
import resource
import signal
import sys

HERE = Path(__file__).absolute().parent
_spec = importlib.util.spec_from_file_location('finite_analysis_preserved_core_v1',
                                               HERE/'finite_result_analysis_v1.py')
core = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = core
_spec.loader.exec_module(core)
need, BoundIO = core.need, core.BoundIO
V4_FILES = frozenset(('METRICS_BY_RUN.json', 'CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl',
    'ORACLE_COMPARISONS.json', 'QUALITY_ROWS.jsonl', 'QUALITY_AGGREGATE.json',
    'INDEPENDENT_ORACLE_SLOTS.json', 'NATIVE_COUNTEREXAMPLES.json',
    'VALIDATION_ERRORS.json', 'REPORT.json', 'FEASIBLE_REFERENCE_IMPORT.json',
    'FEASIBLE_REFERENCE_PROVENANCE.json'))
MODES = ('cap-window', 'native-inventory', 'native-feasibility-window')
ORIGINAL_RESERVE = 1_000_000_000


def integer(value, name, positive=False):
    need(type(value) is int and value >= (1 if positive else 0),
         'unknown/invalid numeric bound: ' + name)
    return value


def relative_outputs(mapping, name):
    need(isinstance(mapping, dict), 'unknown output census: ' + name)
    for path, bound in mapping.items():
        need(isinstance(path, str) and path and Path(path).parts and not Path(path).is_absolute()
             and '..' not in Path(path).parts and str(Path(path)) == path,
             'unsafe output name: ' + str(path))
        integer(bound, name + '/' + path)
    return sum(mapping.values())


def validate_numeric_request(mode, window, out, request, expected_output_names):
    """Pure structural/arithmetic check, not independent numerical acceptance."""
    need(mode in MODES and window in core.WINDOWS, 'unknown resource scope')
    need(request.get('schema') == 'finite-analysis-numeric-operation-request-v2'
         and request.get('status') == 'SOURCE_DERIVED_BOUNDS_FROZEN'
         and request['scope'] == {'mode': mode, 'window': window, 'out': out},
         'numeric request differs from exact operation')
    need(request['original_reserve_bytes'] == ORIGINAL_RESERVE,
         'original one-billion-byte reserve differs')
    need(request['source_derivation'] and all(isinstance(ref, dict)
         and ref.get('path') and core.HEX.fullmatch(ref.get('sha256', ''))
         for ref in request['source_derivation']), 'source derivation refs missing')
    outputs = request['output_upper_bytes']
    output_bytes = relative_outputs(outputs, 'all outputs')
    names = set(outputs)
    pools = request['empirical_output_budget_pools']
    need(isinstance(pools, list), 'unknown empirical output budget pool census')
    for pool in pools:
        need(pool.get('basis') == 'EMPIRICAL_NOT_FIT_GUARANTEE'
             and pool.get('source_schema_delta_review_required') is True
             and pool.get('prior_accepted_request') and pool.get('prior_numeric_acceptance'),
             'shared margin lacks explicit empirical ancestry/review')
        members = pool['output_names']
        need(isinstance(members, list) and members and len(members) == len(set(members))
             and not names.intersection(members), 'duplicated/overlapping empirical output pool')
        relative_outputs({name:0 for name in members}, 'empirical pool output census')
        names.update(members)
        output_bytes += integer(pool['budget_bytes'], 'empirical output pool', True)
    need(len(expected_output_names) == len(set(expected_output_names))
         and names == set(expected_output_names), 'qualified full output census differs')
    projections = request['projection_upper_bytes']
    projection_bytes = relative_outputs(projections, 'all projections')
    need(not names.intersection(projections), 'outputs/projections overlap')
    metrics = request['metrics_gzip_inputs']
    need(isinstance(metrics, list), 'unknown gzip input census')
    if mode == 'cap-window':
        prefix = request['planned_v4_output_prefix']
        relative_outputs({prefix: 0}, 'planned V4 namespace')
        v4_names = {str(Path(prefix)/name) for name in V4_FILES}
        metrics_name = str(Path(prefix)/'METRICS_BY_RUN.json')
        need(v4_names <= names and metrics_name in outputs and outputs[metrics_name] >= 3
             and 'REPORT.json' in names,
             'all eleven unchanged V4 outputs must be bounded')
        recipe = request['metrics_recipe']
        need(recipe['nonpreparation_basis'] == 'EMPIRICAL_NOT_FIT_GUARANTEE'
             and recipe.get('prior_accepted_request') and recipe.get('prior_numeric_acceptance'),
             'non-preparation metrics margin lacks accepted empirical ancestry')
        prep = integer(recipe['exact_preparation_serialization_bytes'], 'exact preparation census')
        margin = integer(recipe['nonpreparation_margin_bytes'], 'empirical nonpreparation margin', True)
        need(outputs[metrics_name] == prep + margin, 'metrics census plus empirical margin differs')
        need(metrics == [{'path': metrics_name, 'upper_bytes': outputs[metrics_name]}],
             'exact cap METRICS gzip input bound differs')
    else:
        # Typed native helpers do not emit familybench/V4 METRICS. This is a
        # source-typed empty applicable set, not a waiver of an applicable gate.
        need(request['planned_v4_output_prefix'] is None
             and not (V4_FILES - {'REPORT.json'}).intersection(Path(path).name for path in names)
             and metrics == [], 'native mode cannot borrow or waive a V4 budget')
    gzip_bytes = sum(integer(row['upper_bytes'], 'gzip input')
                     + row['upper_bytes']//100 + 1_048_576 for row in metrics)
    need(request['gzip_workspace_upper_bytes'] == gzip_bytes,
         'gzip workspace must be exactly M + M//100 + 1048576 per input')
    restore = integer(request['original_path_restore_peak_bytes'], 'restore peak')
    partial = integer(request['temporary_and_failed_partial_peak_bytes'], 'partial overlap')
    gates = request['adopted_free_space_gates']
    need(isinstance(gates, list), 'applicable adopted gate inventory is unknown')
    adopted = []
    for gate in gates:
        ref = gate['receipt']
        need(ref.get('path') and core.HEX.fullmatch(ref.get('sha256', '')),
             'adopted gate is not source bound')
        adopted.append(integer(gate['required_free_bytes'], 'adopted gate', True))
    derived = restore + output_bytes + projection_bytes + partial + gzip_bytes + ORIGINAL_RESERVE
    required = max([derived] + adopted)
    need(request['required_free_bytes'] == required, 'numeric request arithmetic differs')
    return dict(original_path_restore_peak_bytes=restore,
        all_output_upper_bytes=output_bytes, all_projection_upper_bytes=projection_bytes,
        temporary_and_failed_partial_peak_bytes=partial, gzip_workspace_upper_bytes=gzip_bytes,
        original_reserve_bytes=ORIGINAL_RESERVE, derived_required_free_bytes=derived,
        required_free_bytes=required, applicable_adopted_gate_count=len(adopted),
        empirical_budget_pool_count=len(pools), empirical_fit_guarantee=False,
        preliminary_3_1GB_is_adopted_authority=False)


def gate_operation(args, io):
    need(args.quiet_window_open, 'explicit owner quiet slot is required')
    binding = io.read_ref(dict(path=str(core.absolute(args.binding)), sha256=args.binding_sha256))
    need(binding.get('schema') == 'finite-analysis-input-binding-v2'
         and binding.get('status') == 'INDEPENDENTLY_ACCEPTED'
         and args.mode in binding['modes'] and binding['out'] == str(core.absolute(args.out)),
         'exact input/mode/out not independently accepted')
    qualification = io.read_ref(binding['source_qualification'])
    need(qualification.get('schema') == 'finite-analysis-source-qualification-v2'
         and qualification.get('status') == 'INDEPENDENTLY_ACCEPTED'
         and args.mode in qualification['modes'], 'v2 source/mode qualification missing')
    io.file_ref(Path(__file__).absolute(), qualification['entrypoint_sha256'])
    io.file_ref(HERE/'finite_result_analysis_v1.py', qualification['preserved_core_sha256'])
    release = io.read_ref(binding['owner_release'])
    need(release.get('schema') == 'finite-analysis-owner-release-v2'
         and release.get('status') == 'OWNER_RELEASED'
         and release['scope'] == dict(mode=args.mode, window=binding['window'], out=binding['out'])
         and release['resource_request'] == binding['resource_request'],
         'owner release does not bind exact numeric request/scope')
    expiry = datetime.fromisoformat(release['expires_utc'].replace('Z', '+00:00'))
    need(expiry.tzinfo is not None and datetime.now(timezone.utc) < expiry,
         'owner quiet-slot release expired')
    return binding, qualification


def resource_gate(mode, binding, qualification, io):
    request = io.read_ref(binding['resource_request'])
    terms = validate_numeric_request(mode, binding['window'], binding['out'], request,
        qualification['output_paths_by_mode'][mode])
    admission = io.read_ref(binding['resource_admission'])
    need(admission.get('schema') == 'finite-analysis-resource-admission-v2'
         and admission.get('status') == 'INDEPENDENTLY_ACCEPTED'
         and admission['resource_request'] == binding['resource_request']
         and admission['scope'] == request['scope']
         and admission.get('adopted_gate_inventory_complete') is True
         and admission.get('empirical_margins_and_source_schema_delta_independently_reviewed') is True
         and admission['required_free_bytes'] == terms['required_free_bytes'],
         'independent exact per-mode numerical authority missing')
    for ref in request['source_derivation']:
        io.file_ref(ref['path'], ref['sha256'])
    empirical_refs = []
    if mode == 'cap-window':
        empirical_refs.extend(request['metrics_recipe'][name]
                              for name in ('prior_accepted_request', 'prior_numeric_acceptance'))
    for pool in request['empirical_output_budget_pools']:
        empirical_refs.extend(pool[name] for name in ('prior_accepted_request', 'prior_numeric_acceptance'))
    for ref in empirical_refs:
        io.file_ref(ref['path'], ref['sha256'])
    for gate in request['adopted_free_space_gates']:
        io.file_ref(gate['receipt']['path'], gate['receipt']['sha256'])
    for name in ('min_mem_available_bytes', 'address_space_bytes', 'cpu_seconds',
                 'wall_seconds', 'min_cgroup_headroom_bytes'):
        integer(admission[name], name, True)
    observed = core.resource_snapshot()
    need(observed['disk_free_bytes'] >= terms['required_free_bytes'], 'insufficient current free disk')
    need(observed['mem_available_bytes'] is not None
         and observed['mem_available_bytes'] >= admission['min_mem_available_bytes'],
         'insufficient/unknown current MemAvailable')
    for row in observed['exposed_cgroup_headroom']:
        if row['headroom_bytes'] is not None:
            need(row['headroom_bytes'] >= admission['min_cgroup_headroom_bytes'],
                 'insufficient current exposed cgroup headroom')
    resource.setrlimit(resource.RLIMIT_AS, (admission['address_space_bytes'],)*2)
    resource.setrlimit(resource.RLIMIT_CPU, (admission['cpu_seconds'], admission['cpu_seconds']+1))
    signal.alarm(admission['wall_seconds'])
    return dict(admission=admission, exact_bound_terms=terms, observed=observed,
                hard_rss_or_hidden_limit_guarantee=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True, choices=MODES)
    parser.add_argument('--quiet-window-open', action='store_true')
    parser.add_argument('--binding', required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    io = BoundIO()
    binding, qualification = gate_operation(args, io)
    fd = os.open(core.LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        resources = resource_gate(args.mode, binding, qualification, io)
        out = core.absolute(args.out)
        need(core.ROOT/'analysis' in out.parents and out.parent.is_dir()
             and out.parent.resolve() == out.parent and not out.exists(), 'output is not fresh')
        for ref in binding['references']:
            io.file_ref(ref['path'], ref['sha256'])
        io.file_ref(core.ROOT/'analysis/evaluate_v2_feasible_safe_fill_v4.py',
                    core.PINS['analysis/evaluate_v2_feasible_safe_fill_v4.py'])
        out.mkdir()
        core.write_json(out/'RESOURCE_OBSERVATIONS.json', resources)
        if args.mode == 'cap-window':
            delivery = core.load_pinned(io, 'finite_existing_delivery',
                'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py')
            lineage = core.load_pinned(io, 'finite_existing_lineage', 'analysis/feasible_reference_v1.py')
            return 0 if core.prepare_cap_window(binding, io, out, delivery, lineage) else 2
        adapter_path = HERE/'native216_orchestrator_v2.py'
        adapter_ref = io.file_ref(adapter_path, qualification['native_adapter_sha256'])
        spec = importlib.util.spec_from_file_location('finite_native216_orchestrator_v2', adapter_path)
        adapter = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = adapter
        spec.loader.exec_module(adapter)
        io.file_ref(core.ROOT.parent/'evalkit/evalkit.py', core.CHECKER_SHA)
        inv = core.load_pinned(io, 'finite_existing_native_inventory', 'analysis/summarize_native_auxiliary_v1.py')
        audit = None if args.mode == 'native-inventory' else core.load_pinned(io,
            'finite_existing_native_audit', 'analysis/audit_native_transit_v1.py')
        native = copy.deepcopy(binding['native'])
        native['mode'] = 'inventory' if args.mode == 'native-inventory' else 'feasibility-window'
        native['window'] = binding['window']
        native['orchestrator_source'] = adapter_ref
        adapter.run_native_window(native, io, out, inv, audit)
        return 0
    finally:
        signal.alarm(0)
        os.close(fd)


if __name__ == '__main__':
    raise SystemExit(main())
