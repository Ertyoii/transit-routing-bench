#!/usr/bin/env python3
"""Create-only finite analysis input views and typed native orchestration.

UNEXECUTED SOURCE CANDIDATE. Import is inert: helpers and inputs are loaded only
after explicit quiet release, independently accepted source/input bindings, the
global lock and current resource admission. This CLI never runs V4 or a router,
restores/archives/retires files, manufactures a reference export, or accepts its
own outputs. The original seven preparation drafts are not modified.

Later CLI: --mode cap-window|native-inventory|native-feasibility-window
 --quiet-window-open --binding ABS_JSON --binding-sha256 SHA --out FRESH_ABS_DIR

Common binding schema finite-analysis-input-binding-v1 / INDEPENDENTLY_ACCEPTED:
 out, modes, window, source_qualification(ref), owner_release(ref),
 resource_admission(ref), references(list of exact original reference refs).
 Source qualification binds this source, native216_orchestrator_v1.py, and modes.
 Release schema finite-analysis-owner-release-v1 / OWNER_RELEASED has modes and
 expires_utc. Resource schema finite-analysis-resource-admission-v1 /
 INDEPENDENTLY_ACCEPTED has mode, required_free_bytes (>=3.1GB),
 min_mem_available_bytes, address_space_bytes, cpu_seconds, wall_seconds.

Cap binding: cap_sources two plan refs; initial_plan ref; seed_manifest ref;
 initial_control_variants list; source_B_plan ref; source_B_coverage ref;
 source_B_parity ref; source_B_projection_report ref; source_B_v4_report ref;
 methodology_plan ref; donor_lineage ref; frozen_files
 mapping absolute original config path -> {path,sha256,bytes}; input_states
 mapping original campaign -> run ID -> {summary:ref|null, absence_reason:str}.
 Native binding: native subsection consumed by the truthful injected orchestrator.

All refs require path/sha256; bytes is checked when present. These schemas are
prospective qualification seams, not claims that acceptance receipts exist.
"""
from __future__ import annotations

import argparse
import collections
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import sys
from typing import Any, Iterable, Mapping


ROOT = Path('/workspace/shared/sg-coldstart/campaign-v2-20261021')
HERE = ROOT / 'analysis/finite-result-analysis-preparation-v1'
LOCK = ROOT.parent / 'setup/campaign.lock'
WINDOWS = tuple('weekday-' + name + '-20261020'
                for name in ('morning', 'midday', 'evening', 'overnight'))
HEX = re.compile(r'[0-9a-f]{64}')
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}')
PINS = {
    'analysis/evaluate_v2_feasible_safe_fill_v4.py':
        'b75ff1d989896d411fa33d39f70ccc995a2af25f5b2d598c23fa0004c1dc37b0',
    'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py':
        'b95a3706d533c89e53a06a798d8b65815146c94fcdc5b0cb8f481ded300bee88',
    'analysis/feasible_reference_v1.py':
        '7d08bf7ae1fe0c0a030dfea12c429e297c9aa6fbf0e56620c11a516e10df988a',
    'analysis/summarize_native_auxiliary_v1.py':
        'c29af276cf69e09f5bbb800063c1665e2ff556418409f147c9a09596a93e0e4b',
    'analysis/audit_native_transit_v1.py':
        'cad78e1d20fb05f941a9bc5777ccf2bd9d82a36a381360c4672521c2f106bfb0',
}
INITIAL_PLAN_SHA = '3316fc768131a56f17a58f5c0231494cb0b769baea9345a9b68d59e1a1109ac9'
SOURCE_B_PLAN_SHA = '562780615b349aca408e291a3f5cee989b125977f030d805d241b87696a75627'
SEED_MANIFEST_SHA = '52712fdc0ecf6f1d1db4ef33a52bf90f1f909eb6bc038707200bc54bb8df9812'
SOURCE_B_PARITY_SHA = '7aa6471c5809694971604f4568a275e66d7ed71f3622fc3ef75ad41e1801aaf5'
SOURCE_B_COVERAGE_SHA = '1e7877375770d087b8f3e4b1e8d05006dc58c311c952fa2bff7e2058177940b2'
SOURCE_B_PROJECTION_REPORT_SHA = '16524b26154b6d0fcab0c7d00e1ba0615daf13922bfd35d2a55c3d44fa3c6335'
CHECKER_SHA = 'd26f32d8cabfcc873387749cd1d9d818bbaecd8ad3b597753f029b0f7a5aeedb'
DEFAULT_INITIAL_CONTROLS = (
    'raptor-control', 'raptor-early-control', 'raptor-local-walk-ties',
    'raptor-early-local-walk-ties', 'mc-storage', 'mc-early-control',
    'tb-capped-control', 'ultra-capped-control', 'ultra-subset-storage',
    'ultra-capped-local-walk-ties', 'ultra-subset-local-walk-ties',
)


def need(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def strict_json(text: str) -> Any:
    def bad_constant(value):
        raise ValueError('nonfinite JSON token: ' + value)
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=bad_constant)


def absolute(path: str | Path) -> Path:
    path = Path(path)
    need(path.is_absolute() and str(path) == os.path.normpath(str(path)),
         'path must be lexical absolute without traversal: ' + str(path))
    return path


def flag(argv: list[str], name: str) -> str:
    need(argv.count(name) == 1, 'missing/duplicate flag: ' + name)
    pos = argv.index(name)
    need(pos + 1 < len(argv), 'missing flag value: ' + name)
    return argv[pos + 1]


def write_json(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


class BoundIO:
    """No automatic restoration, source mutation, model loading or subprocess."""
    def __init__(self):
        self.bindings: dict[str, str] = {}

    def file_ref(self, path, expected_sha=None, max_bytes=128 * 1024 * 1024):
        path = absolute(path)
        need(path.is_file(), 'missing bound file: ' + str(path))
        size = path.stat().st_size
        need(type(max_bytes) is int and 0 <= size <= max_bytes,
             'file exceeds admitted bounded read: ' + str(path))
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected_sha is not None:
            need(isinstance(expected_sha, str) and HEX.fullmatch(expected_sha),
                 'invalid bound SHA: ' + str(path))
            need(actual == expected_sha, 'bound file changed: ' + str(path))
        prior = self.bindings.setdefault(str(path), actual)
        need(prior == actual, 'file changed within analysis operation: ' + str(path))
        return {'path': str(path), 'sha256': actual, 'bytes': size}

    def read_path(self, path, expected_sha=None, max_bytes=128 * 1024 * 1024):
        ref = self.file_ref(path, expected_sha, max_bytes)
        data = Path(ref['path']).read_bytes()
        need(len(data) == ref['bytes'] and hashlib.sha256(data).hexdigest() == ref['sha256'],
             'bound file changed before JSON read')
        return strict_json(data.decode('utf-8'))

    def read_ref(self, ref):
        need(isinstance(ref, dict) and isinstance(ref.get('path'), str)
             and HEX.fullmatch(ref.get('sha256', '')), 'missing exact file reference')
        value = self.read_path(ref['path'], ref['sha256'])
        if 'bytes' in ref:
            need(type(ref['bytes']) is int and Path(ref['path']).stat().st_size == ref['bytes'],
                 'bound file byte count changed')
        return value

    def jsonl_ref(self, ref, max_bytes=128 * 1024 * 1024):
        checked = self.file_ref(ref['path'], ref['sha256'], max_bytes)
        if 'bytes' in ref:
            need(ref['bytes'] == checked['bytes'], 'JSONL byte census changed')
        digest = hashlib.sha256()
        with Path(checked['path']).open('rb') as stream:
            for line in stream:
                need(len(line) <= 8 * 1024 * 1024 and line.strip(),
                     'unbounded/empty JSONL record')
                digest.update(line)
                yield strict_json(line.decode('utf-8'))
        need(digest.hexdigest() == checked['sha256'], 'JSONL changed during read')


def load_pinned(io: BoundIO, name: str, relative: str):
    path = ROOT / relative
    io.file_ref(path, PINS[relative])
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, 'helper loader unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_runs(plan: dict) -> dict[str, dict]:
    need(plan.get('evaluation_mode') == 'diagnostic', 'non-diagnostic source plan')
    runs = plan.get('runs')
    need(isinstance(runs, list), 'source runs missing')
    result = {}
    for run in runs:
        rid = run.get('id')
        need(isinstance(rid, str) and SAFE_ID.fullmatch(rid) and rid not in result,
             'unsafe/duplicate original run ID')
        need(run.get('window') in WINDOWS, 'unfrozen original window')
        need('csa' not in flag(run['argv'], '-algorithm').lower(), 'CSA input excluded')
        result[rid] = run
    return result


def stable_variant_ids(plan: dict, variants: Iterable[str]) -> list[str]:
    variants = tuple(variants)
    need(variants and len(variants) == len(set(variants)), 'duplicate/empty control variants')
    source_runs(plan)
    result = [run['id'] for run in plan['runs'] if run.get('variant_id') in variants]
    for variant in variants:
        rows = [run for run in plan['runs'] if run.get('variant_id') == variant]
        need(len(rows) == 8 and {(row['block'], row['window']) for row in rows}
             == {(block, window) for block in (0, 1) for window in WINDOWS},
             'control does not retain every original block/window: ' + variant)
    return result


def derive_window_plan(parent, selected_ids, original_campaign, registry_path, plan_sha):
    """Stable exact run objects; only registry path and additive view ancestry."""
    selected = set(selected_ids)
    need(len(selected_ids) == len(selected), 'duplicate view ID')
    source = [run for run in parent['runs'] if run['id'] in selected]
    need([run['id'] for run in source] == selected_ids, 'not a stable original subsequence')
    need('finite_analysis_view' not in parent, 'nested/unqualified derived view')
    derived = copy.deepcopy(parent)
    derived['runs'] = copy.deepcopy(source)
    if parent.get('workload_registry') is not None:
        need(isinstance(parent['workload_registry'], dict) and registry_path is not None,
             'original registry identity missing')
        derived['workload_registry']['path'] = str(absolute(registry_path))
    else:
        need(registry_path is None, 'invented registry for an original plan')
    derived['finite_analysis_view'] = {
        'schema': 'finite-cap-input-view-v1', 'purpose': 'NONEXECUTABLE_ANALYSIS_ONLY',
        'original_campaign': str(absolute(original_campaign)),
        'original_plan_sha256': plan_sha, 'selected_original_ids': list(selected_ids),
        'original_run_indexes': [i for i, run in enumerate(parent['runs']) if run['id'] in selected],
    }
    return derived


def check_view_equivalence(parent, derived, selected_ids, original_campaign,
                           registry_path, plan_sha):
    expected = derive_window_plan(parent, selected_ids, original_campaign, registry_path, plan_sha)
    need(derived == expected, 'view changed original run objects or unapproved metadata')


def compare_donor_unions(full, retained):
    """Compare bound reconstructed data/tags, never calculate a quality score."""
    differences = []
    for key in sorted(set(full) | set(retained)):
        a, b = full.get(key), retained.get(key)
        if a is None or b is None:
            differences.append({'key': list(key), 'fields': ['missing_identity']})
            continue
        fields = [field for field in ('feature', 'journey', 'families', 'lineages')
                  if a[field] != b[field]]
        if fields:
            differences.append({'key': list(key), 'fields': fields})
    return {'schema': 'finite-cap-original192-donor-union-check-v1',
            'status': 'EQUAL_BOUND_UNION_ONLY_NOT_GENERAL_COMPLETENESS'
                      if not differences else 'BLOCKED_DONOR_UNION_DISCREPANCY',
            'full_identities': len(full), 'retained_identities': len(retained),
            'differences': differences, 'quality_evaluation_authorized': False}


def seed_union_check(initial, selected_ids, manifest, seed_rows, members, lineage):
    """Reuse the accepted raw/final seed and preserve all192 offer outcomes."""
    runs = source_runs(initial)
    need(len(runs) == 192 and manifest.get('schema') == 'sg-selector-replay-manifest-v1'
         and manifest.get('candidate_rows') == 11520
         and manifest.get('authoritative_errors') == 0
         and manifest.get('authoritative_native_counterexamples') == 0,
         'not the accepted full original192 seed')
    selected = set(selected_ids)
    need(selected <= set(runs), 'unoffered retained control')
    old_algorithms = {flag(run['argv'], '-algorithm') for run in runs.values()}
    new_algorithms = {flag(runs[rid]['argv'], '-algorithm') for rid in selected}
    need(len(old_algorithms) == 11 and new_algorithms == old_algorithms,
         'retained controls do not cover all eleven original algorithm contracts')
    offered, per_run, queries, states = set(), collections.Counter(), {}, []
    families = {}
    for row in seed_rows:
        rid, qid = row['run'], row['query']['id']
        need(rid in runs and (rid, qid) not in offered, 'unknown/duplicate original seed offer')
        run = runs[rid]
        algorithm = flag(run['argv'], '-algorithm')
        need(row['window'] == run['window'] and row['algorithm'] == algorithm
             and row['variant_id'] == run['variant_id'], 'seed run identity differs')
        need(type(row['independent_complete']) is bool, 'untyped original completion')
        lineage.group(algorithm, row['family'])
        families[rid] = row['family']
        key = row['dataset_sha256'], qid
        signature = canonical({'query': row['query'], 'stratum': row['stratum']})
        need(queries.setdefault(key, signature) == signature, 'query/stratum identity collision')
        offered.add((rid, qid)); per_run[rid] += 1
        states.append({key: row[key] for key in (
            'run', 'variant_id', 'window', 'algorithm', 'family', 'dataset_sha256',
            'query', 'stratum', 'native_complete', 'independent_complete', 'independent_status')})
    need(len(offered) == 11520 and set(per_run) == set(runs)
         and all(count == 60 for count in per_run.values()), 'original192 full offer census differs')
    full, reduced, provenance = {}, {}, []
    for member in members:
        donors = set(member['donor_runs']) & set(runs)
        if not donors:
            need(set(member['donor_families']) == {'independent_scalar_oracle'},
                 'unrecognized non-native seed donor')
            continue  # unchanged independently imported scalar source on BOTH sides
        key = member['dataset_sha256'], member['query_id'], member['identity']
        need(key not in full and key[:2] in queries, 'duplicate/unmatched seed member')
        need(member['feature'].get('metrics') is not None
             and member.get('journey') is not None, 'independent reconstruction features missing')
        def projected(ids):
            return {'feature': member['feature'], 'journey': member['journey'],
                    'families': sorted({families[rid] for rid in ids}),
                    'lineages': sorted({tuple(lineage.group(flag(runs[rid]['argv'], '-algorithm'),
                                                          families[rid])) for rid in ids})}
        full[key] = projected(donors)
        need(set(full[key]['families']) == set(member['donor_families']) - {'independent_scalar_oracle'},
             'seed donor-family provenance inconsistent')
        retained = donors & selected
        if retained:
            reduced[key] = projected(retained)
        provenance.append({'key': list(key), 'original_donor_runs': sorted(donors),
                           'retained_actual_control_runs': sorted(retained)})
    result = compare_donor_unions(full, reduced)
    result.update(original_processes=192, original_offers=11520,
                  original_unknown_offers=sum(not row['independent_complete'] for row in states),
                  retained_control_processes=len(selected),
                  provenance_map=provenance, original_offer_ledger_retained=True,
                  original_scalar432_native960_unchanged=True)
    return result, states


def check_source_B_reduction(plan, coverage, parity, selected_ids):
    runs = source_runs(plan)
    selected = set(selected_ids)
    need(len(runs) == 96 and len(selected) == 8, 'wrong Source-B full/reduced process census')
    need(coverage.get('runs') == 96 and coverage.get('offered') == 5760
         and coverage.get('completed') == 5760 and coverage.get('validation_errors') == 0
         and coverage.get('native_counterexamples') == 0
         and coverage.get('projection_native_parity') == {'exact': 88},
         'Source-B accepted coverage/parity differs')
    pairs, covered = set(), set(selected)
    checks = parity.get('checks', [])
    need(len(checks) == 88, 'Source-B exact88 parity census differs')
    for check in checks:
        a, b = check['baseline'], check['candidate']
        need(a in selected and b in runs and (a, b) not in pairs
             and check['status'] == 'exact' and check.get('offered') == 60
             and not check.get('differences') and not check.get('incomplete_query_ids')
             and not check.get('incomplete_outcome_differences'),
             'Source-B missing/incomplete/mismatched parity pair')
        need(runs[a]['window'] == runs[b]['window'] == check['window']
             and runs[a]['block'] == runs[b]['block'] == check['block'],
             'Source-B cross-contract parity pair')
        pairs.add((a, b)); covered.add(b)
    need(covered == set(runs), 'Source-B original offers omitted from parity coverage')


def _pinned_ref(io, reference, expected_path, expected_sha):
    need(reference['path'] == str(expected_path) and reference['sha256'] == expected_sha,
         'wrong accepted source/seed reference: ' + str(expected_path))
    return io.read_ref(reference)


def _config_check(run, io, frozen_files, delivery, require_k3):
    argv = run['argv']
    need(argv.count('-quality') == 1 and flag(argv, '-display-k') == '-1',
         'uncertified or extra display work in retained serving control')
    path = str(absolute(flag(argv, '-preference-scenarios')))
    need(path in frozen_files and frozen_files[path]['path'] == path, 'unbound config bytes')
    config = io.read_ref(frozen_files[path])
    k, _kind = delivery.delivery_config(config, 'per-run')
    need(not require_k3 or k == 3, 'retained control is not certified single-k3')


def prepare_cap_window(binding, io, out, delivery, lineage_module):
    window = binding['window']
    need(window in WINDOWS, 'unfrozen cap window')
    initial_ref = binding['initial_plan']
    initial = _pinned_ref(io, initial_ref, ROOT/'experiments/initial-source-quality-tune-v3-seed/plan.json', INITIAL_PLAN_SHA)
    source_b_ref = binding['source_B_plan']
    source_b = _pinned_ref(io, source_b_ref, ROOT/'experiments/source-B-12policy-serving-v1-run/plan.json', SOURCE_B_PLAN_SHA)
    seed_ref = binding['seed_manifest']
    seed_root = ROOT/'analysis/selector-tune-v3-manifest-attempt02'
    seed = _pinned_ref(io, seed_ref, seed_root/'MANIFEST.json', SEED_MANIFEST_SHA)
    need(seed['inputs'].get(initial_ref['path']) == INITIAL_PLAN_SHA, 'seed original plan mismatch')
    projection = _pinned_ref(io, binding['source_B_projection_report'],
        ROOT/'analysis/source-B-96-frontier-v1-attempt01/REPORT.json', SOURCE_B_PROJECTION_REPORT_SHA)
    v4ref = binding['source_B_v4_report']
    need(v4ref['path'] == str(ROOT/'analysis/source-B-96-native-ancestry-v1-attempt01/REPORT.json')
         and v4ref['sha256'] == projection['evaluator_report_sha256'],
         'accepted Source-B V4 reference-generation report changed')
    previous_v4 = io.read_ref(v4ref)
    need(previous_v4.get('schema') == 'sg-independent-v2-feasible-safe-fill-v4'
         and previous_v4['runs'] == 96 and previous_v4['offered_run_rows'] == 5760
         and previous_v4['oracle_offered_slots'] == 432
         and previous_v4['oracle_complete_slots'] == 414
         and previous_v4['feasible_native_reference_import']['offered_native_reference_rows'] == 960,
         'original accepted scalar432/native960 reference census changed')
    need(binding['donor_lineage']['path'] == str(ROOT.parent/'campaign-v2-audit-20261021/DONOR_ANCESTRY_ALGORITHMS_V2.json'),
         'donor-lineage destination changed')
    need(binding['donor_lineage']['sha256'] == previous_v4['inputs'][binding['donor_lineage']['path']],
         'donor-lineage bytes differ from accepted reference generation')
    io.read_ref(binding['donor_lineage'])
    def lineage_read(path, expected=None, as_text=False):
        checked = io.file_ref(path, expected)
        text = Path(path).read_text()
        need(hashlib.sha256(text.encode()).hexdigest() == checked['sha256'], 'lineage changed')
        return text if as_text else strict_json(text)
    lineage = lineage_module.DonorLineage(binding['donor_lineage']['path'], lineage_read)
    initial_ids = stable_variant_ids(initial, binding['initial_control_variants'])
    source_b_ids = stable_variant_ids(source_b, ['finite20-lean-k3'])
    for rid in initial_ids:
        _config_check(source_runs(initial)[rid], io, binding['frozen_files'], delivery, True)
    coverage = _pinned_ref(io, binding['source_B_coverage'], ROOT/'analysis/source-B-96-frontier-v1-attempt01/COVERAGE_REFERENCE_ACCEPTANCE.json', SOURCE_B_COVERAGE_SHA)
    parity = _pinned_ref(io, binding['source_B_parity'], ROOT/'analysis/source-B-96-frontier-v1-attempt01/NATIVE_POLICY_PARITY_88.json', SOURCE_B_PARITY_SHA)
    check_source_B_reduction(source_b, coverage, parity, source_b_ids)
    checked_reference_paths = coverage.get('exact_old_reference_binding_checks', {})
    expected_scalar_paths = {str(ROOT/('selector-quality/results/oracle-tune-full1h-48x9/%s.jsonl' % name))
                             for name in WINDOWS}
    expected_native_path = str(ROOT/'analysis/native-transit-independent-v1-attempt01/FEASIBLE_REFERENCE_WITNESSES.jsonl')
    need(expected_scalar_paths | {expected_native_path} <= set(checked_reference_paths),
         'accepted reference file census incomplete')
    for path, accepted in checked_reference_paths.items():
        need(accepted is True and path in previous_v4['inputs'], 'unbound original reference companion')
        io.file_ref(path, previous_v4['inputs'][path])
    rows_ref = {'path': str(seed_root/'CANDIDATE_ROWS.jsonl'), 'sha256': seed['outputs']['CANDIDATE_ROWS.jsonl']}
    members_ref = {'path': str(seed_root/'POOL_MEMBERS.jsonl'), 'sha256': seed['outputs']['POOL_MEMBERS.jsonl']}
    union, original_states = seed_union_check(initial, initial_ids, seed,
        io.jsonl_ref(rows_ref), io.jsonl_ref(members_ref), lineage)
    with (out/'ORIGINAL192_OFFER_LEDGER.jsonl').open('x') as stream:
        for row in original_states:
            stream.write(canonical(row) + '\n')
    write_json(out/'CONTROL_UNION_CHECK.json', union)
    if union['differences']:
        write_json(out/'REPORT.json', {'schema': 'finite-cap-window-preparation-v1',
            'status': 'BLOCKED_DONOR_UNION_DISCREPANCY', 'window': window,
            'next': 'Preserve discrepancy; propose existing compatible controls or existing typed export for independent review.',
            'inputs': io.bindings, 'numeric_v4_forecast': None,
            'evaluation_launch_authorized': False})
        return False
    sources = []
    need(len(binding['cap_sources']) == 2, 'both original cap blocks required')
    cap_ids, cap_blocks = set(), set()
    for source in binding['cap_sources']:
        ref = source['plan']; plan = io.read_ref(ref); runs = source_runs(plan)
        campaign = absolute(ref['path']).parent
        block = plan['finite_lane']['block']
        need(block in (0, 1) and block not in cap_blocks
             and campaign == ROOT/('experiments/cap96-v1-b%d-run' % block), 'cap campaign/block changed')
        need(len(runs) == 48 and all(run['block'] == block for run in runs.values()), 'cap48 stage census differs')
        cap_blocks.add(block); cap_ids.update(runs)
        sources.append(('cap_target', ref, plan, list(runs)))
    need(cap_blocks == {0, 1} and len(cap_ids) == 96, 'cap96 unique census changed')
    sources += [('initial_control', initial_ref, initial, initial_ids),
                ('source_B_control', source_b_ref, source_b, source_b_ids)]
    method_ref = binding['methodology_plan']; method = io.read_ref(method_ref)
    method_runs = source_runs(method)
    need(absolute(method_ref['path']) == ROOT/'experiments/certified-k3k5-all240-methodology-v1-run/plan.json'
         and len(method_runs) == 8, 'all original methodology8 controls required')
    sources.append(('methodology_control', method_ref, method, list(method_runs)))
    role_rows, views, all_ids = [], [], set()
    for index, (role, ref, plan, ids) in enumerate(sources):
        original = absolute(ref['path']).parent
        selected = [run for run in plan['runs'] if run['id'] in set(ids) and run['window'] == window]
        need(selected, 'source has no exact-window controls')
        registry_ref = plan.get('workload_registry'); registry_path = None
        if registry_ref is not None:
            registry_ref = copy.deepcopy(registry_ref)
            candidate = Path(registry_ref['path'])
            registry_path = candidate if candidate.is_absolute() else original/candidate
            registry_ref['path'] = str(absolute(registry_path))
            io.read_ref(registry_ref)
        selected_ids = [run['id'] for run in selected]
        need(not all_ids.intersection(selected_ids), 'cross-source run-ID collision in V4 joins')
        all_ids.update(selected_ids)
        for run in selected:
            _config_check(run, io, binding['frozen_files'], delivery, role != 'methodology_control')
            expected_dataset = ROOT/('data-workload/models/phase_hash_a/%s/dataset.json' % window)
            expected_workload = ROOT/('data-workload/workloads/phase_hash_a_conservative600/%s.tune.full.primary_1h_walk600.json' % window)
            need(flag(run['argv'], '-dataset') == str(expected_dataset)
                 and flag(run['argv'], '-queries') == str(expected_workload), 'source window/query scope changed')
            state = binding['input_states'][str(original)][run['id']]
            if state['summary'] is not None:
                need(state['summary']['path'] == str(original/run['id']/'artifact/summary.json'),
                     'summary alias changed')
                io.read_ref(state['summary'])
            else:
                need(state.get('absence_reason') and not (original/run['id']/'artifact/summary.json').exists(),
                     'unexplained or changed original summary absence')
                need(not (original/run['id']/'artifact/summary.json.gz').exists()
                     and not (original/run['id']/'artifact/summary.retirement-after-stage.json').exists(),
                     'recoverably retired summary must be restored by qualified operator, not recast as missing')
            role_rows.append({'id': run['id'], 'role': role, 'window': window,
                              'original_campaign': str(original), 'offered': 60,
                              'original_summary_state': state})
        view_root = out/('source-%02d' % index)
        view_root.mkdir()
        derived = derive_window_plan(plan, selected_ids, original, registry_path, ref['sha256'])
        check_view_equivalence(plan, derived, selected_ids, original, registry_path, ref['sha256'])
        write_json(view_root/'plan.json', derived)
        for rid in selected_ids:
            target = original/rid
            if target.exists():
                need(target.is_dir() and not target.is_symlink(), 'original run is not an exact directory')
                os.symlink(str(target), str(view_root/rid), target_is_directory=True)
        views.append({'role': role, 'campaign': str(view_root),
                      'original_plan': ref, 'selected_original_ids': selected_ids,
                      'view_plan': io.file_ref(view_root/'plan.json')})
    target_rows = [row for row in role_rows if row['role'] == 'cap_target']
    need(len(target_rows) == 24 and sum(row['offered'] for row in target_rows) == 1440,
         'exact cap/window target count changed')
    write_json(out/'RUN_ROLES_AND_OFFERS.json', {'rows': role_rows,
        'target_processes': 24, 'target_offers': 1440,
        'all_metric_processes': len(role_rows), 'all_metric_offers': 60 * len(role_rows),
        'source_B_full_original_processes': 96, 'source_B_full_original_offers': 5760,
        'original192_offer_ledger': io.file_ref(out/'ORIGINAL192_OFFER_LEDGER.jsonl')})
    write_json(out/'REPORT.json', {'schema': 'finite-cap-window-preparation-v1',
        'status': 'CREATED_PENDING_INDEPENDENT_READER_AND_ACTUAL_INPUT_ACCEPTANCE',
        'window': window, 'views': views, 'inputs': io.bindings,
        'target_processes': 24, 'target_offers': 1440,
        'all_metric_processes': len(role_rows), 'all_metric_offers': 60 * len(role_rows),
        'original_scalar_offers': 432, 'original_native_reference_offers': 960,
        'numeric_v4_forecast': None, 'unchanged_v4': PINS['analysis/evaluate_v2_feasible_safe_fill_v4.py'],
        'evaluation_launch_authorized': False,
        'timing_scope': 'diagnostic only; cap block0 retained0.2s monitor versus block1 0.1s; no homogeneous96 or paired same-envelope claim'})
    return True


def gate_operation(args, io):
    need(args.quiet_window_open, 'explicit owner quiet slot is required')
    binding = io.read_ref({'path': str(absolute(args.binding)), 'sha256': args.binding_sha256})
    need(binding.get('schema') == 'finite-analysis-input-binding-v1'
         and binding.get('status') == 'INDEPENDENTLY_ACCEPTED'
         and args.mode in binding['modes'], 'new input/mode not independently accepted')
    need(binding['out'] == str(absolute(args.out)), 'output differs from exact admitted destination')
    qualification = io.read_ref(binding['source_qualification'])
    need(qualification.get('schema') == 'finite-analysis-source-qualification-v1'
         and qualification.get('status') == 'INDEPENDENTLY_ACCEPTED'
         and args.mode in qualification['modes'], 'new source/mode qualification missing')
    source_ref = io.file_ref(Path(__file__).absolute())
    need(qualification['source_sha256'] == source_ref['sha256'], 'new candidate source changed')
    release = io.read_ref(binding['owner_release'])
    need(release.get('schema') == 'finite-analysis-owner-release-v1'
         and release.get('status') == 'OWNER_RELEASED' and args.mode in release['modes'],
         'owner did not release this phase')
    expiry = datetime.fromisoformat(release['expires_utc'].replace('Z', '+00:00'))
    need(expiry.tzinfo is not None and datetime.now(timezone.utc) < expiry,
         'owner quiet-slot release expired')
    return binding, qualification


def resource_snapshot():
    snapshot = {'disk_free_bytes': shutil.disk_usage(ROOT).free,
                'mem_available_bytes': None, 'exposed_cgroup_headroom': []}
    with Path('/proc/meminfo').open() as stream:
        for line in stream:
            words = line.split()
            if words[0] == 'MemAvailable:':
                snapshot['mem_available_bytes'] = int(words[1]) * 1024
    # Check the exposed v2 hierarchy only; unsupported/unexposed limits remain
    # explicit unknowns, never an inferred hard-RSS or hidden-limit guarantee.
    try:
        entries = Path('/proc/self/cgroup').read_text().splitlines()
        roots = [line.split(':', 2)[2] for line in entries if line.startswith('0::')]
        for relative in roots:
            need('..' not in Path(relative).parts, 'unsafe exposed cgroup path')
            base = Path('/sys/fs/cgroup')/relative.lstrip('/')
            maximum, current = base/'memory.max', base/'memory.current'
            row = {'path': str(base), 'limit_bytes': None, 'current_bytes': None,
                   'headroom_bytes': None, 'status': 'unknown_unexposed'}
            if maximum.is_file() and current.is_file():
                limit_text, current_text = maximum.read_text().strip(), current.read_text().strip()
                if current_text.isdigit() and (limit_text == 'max' or limit_text.isdigit()):
                    row['current_bytes'] = int(current_text)
                    row['limit_bytes'] = None if limit_text == 'max' else int(limit_text)
                    row['status'] = 'exposed_unlimited' if limit_text == 'max' else 'exposed_finite'
                    if row['limit_bytes'] is not None:
                        row['headroom_bytes'] = row['limit_bytes'] - row['current_bytes']
            snapshot['exposed_cgroup_headroom'].append(row)
    except OSError as exc:
        snapshot['cgroup_observation_error'] = type(exc).__name__ + ': ' + str(exc)
    return snapshot


def resource_gate(mode, binding, io):
    admission = io.read_ref(binding['resource_admission'])
    need(admission.get('schema') == 'finite-analysis-resource-admission-v1'
         and admission.get('status') == 'INDEPENDENTLY_ACCEPTED'
         and admission['mode'] == mode, 'resource operation scope differs')
    for name in ('required_free_bytes', 'min_mem_available_bytes', 'address_space_bytes',
                 'cpu_seconds', 'wall_seconds', 'min_cgroup_headroom_bytes'):
        need(type(admission[name]) is int and admission[name] > 0, 'unknown resource term: ' + name)
    need(admission['required_free_bytes'] >= 3_100_000_000,
         'original applicable3.1GB floor was reduced')
    observed = resource_snapshot()
    need(observed['disk_free_bytes'] >= admission['required_free_bytes'], 'insufficient current free disk')
    need(observed['mem_available_bytes'] is not None
         and observed['mem_available_bytes'] >= admission['min_mem_available_bytes'],
         'insufficient/unknown current MemAvailable')
    for row in observed['exposed_cgroup_headroom']:
        if row['headroom_bytes'] is not None:
            need(row['headroom_bytes'] >= admission['min_cgroup_headroom_bytes'],
                 'insufficient current exposed cgroup headroom')
    resource.setrlimit(resource.RLIMIT_AS, (admission['address_space_bytes'],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (admission['cpu_seconds'], admission['cpu_seconds'] + 1))
    signal.alarm(admission['wall_seconds'])
    return {'admission': admission, 'observed': observed,
            'hard_rss_or_hidden_limit_guarantee': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', required=True,
        choices=('cap-window', 'native-inventory', 'native-feasibility-window'))
    parser.add_argument('--quiet-window-open', action='store_true')
    parser.add_argument('--binding', required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    io = BoundIO(); binding, qualification = gate_operation(args, io)
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        resources = resource_gate(args.mode, binding, io)
        out = absolute(args.out)
        need(ROOT/'analysis' in out.parents and out.parent.is_dir()
             and out.parent.resolve() == out.parent and not out.exists(),
             'output is not a fresh exact analysis destination')
        # Bind original reference evidence; never rewrite or automatically import
        # new216 into original960, and never treat these as evaluation admission.
        for ref in binding['references']:
            io.file_ref(ref['path'], ref['sha256'])
        io.file_ref(ROOT/'analysis/evaluate_v2_feasible_safe_fill_v4.py',
                    PINS['analysis/evaluate_v2_feasible_safe_fill_v4.py'])
        out.mkdir()
        write_json(out/'RESOURCE_OBSERVATIONS.json', resources)
        if args.mode == 'cap-window':
            delivery = load_pinned(io, 'finite_existing_delivery',
                'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py')
            lineage = load_pinned(io, 'finite_existing_lineage', 'analysis/feasible_reference_v1.py')
            return 0 if prepare_cap_window(binding, io, out, delivery, lineage) else 2
        adapter_path = HERE/'native216_orchestrator_v1.py'
        adapter_ref = io.file_ref(adapter_path, qualification['native_adapter_sha256'])
        spec = importlib.util.spec_from_file_location('finite_native216_orchestrator', adapter_path)
        adapter = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = adapter
        spec.loader.exec_module(adapter)
        io.file_ref(ROOT.parent/'evalkit/evalkit.py', CHECKER_SHA)
        inv = load_pinned(io, 'finite_existing_native_inventory',
                          'analysis/summarize_native_auxiliary_v1.py')
        audit = None
        if args.mode == 'native-feasibility-window':
            audit = load_pinned(io, 'finite_existing_native_audit', 'analysis/audit_native_transit_v1.py')
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
