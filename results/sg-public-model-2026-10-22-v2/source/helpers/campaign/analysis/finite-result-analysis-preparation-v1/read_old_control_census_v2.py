#!/usr/bin/env python3
"""Narrow read-only old-seed/control census. No model/helper/view/restore/V4.

Run only in an explicitly released bounded slot. Imports the inert new v1 source
for its pure union checks and bounded JSON reader, not its CLI/resource gate.
The preliminary3.1GB estimate is NOT an adopted gate. Output is a draft, never
numeric authority. The only writes are fresh census logs/partials under --out.
"""
from __future__ import annotations
import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).absolute().parent
SPEC = importlib.util.spec_from_file_location('finite_old_census_pure_v1', HERE/'finite_result_analysis_v1.py')
v1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v1)
ROOT = v1.ROOT
LINEAGE_PATH = ROOT.parent/'campaign-v2-audit-20261021/DONOR_ANCESTRY_ALGORITHMS_V2.json'
LINEAGE_SHA = '2603ef345f56a311477097e540ca1eae8d254ad512518f67642e8b0aa8733f7c'
CAP_CLOSURE_PATH = ROOT/'analysis/lossless-storage-v1/finite-four-stage-preservation-v1/CAPS96_LOSSLESS_OPERATION_CLOSURE_ATTEMPT01.json'
CAP_CLOSURE_SHA = '24bf3617a8fbe33c04dde47ed8e073e28365d1699181d563577221220e1555b5'
CAP_ARCHIVE_ACCEPTANCE_PATH = ROOT.parent/'campaign-v2-audit-20261021/CAP96_ARCHIVE_RECONSTRUCTION_INDEPENDENT_ACCEPTANCE_V1.json'
CAP_ARCHIVE_ACCEPTANCE_SHA = 'f5463cd3ab41ad8d4590b75faad0f14481af51df4b318a5f8098a21c75dba009'


class FrozenLineageLabels:
    """Read already accepted labels only; no source-evidence/helper execution."""
    def __init__(self, payload):
        v1.need(payload.get('schema') == 'sg-donor-ancestry-algorithms-v1', 'wrong frozen lineage schema')
        self.payload = payload
    def group(self, algorithm, family=None):
        entry = self.payload['algorithms'][algorithm]
        v1.need(entry['adapter_family'] == family, 'frozen donor-family alias differs')
        labels = entry['ancestry_groups']
        v1.need(isinstance(labels, list) and labels and len(labels) == len(set(labels)),
                'invalid frozen ancestry labels')
        return tuple(sorted(labels))


def record_array_bytes(records):
    encoder = json.JSONEncoder(indent=2, sort_keys=True)
    body, count = 0, 0
    for record in records:
        for chunk in encoder.iterencode(record):
            body += len(chunk.replace('\n', '\n  ').encode('utf-8'))
        count += 1
    return body + 4 * count + 3 if count else 3


def prep_passthrough_bytes(summary):
    """Exact serialized preparation VALUES, not a whole-METRICS estimate."""
    encoder = json.JSONEncoder(indent=2, sort_keys=True)
    result = {}
    for name in ('preparation', 'checker_preparation', 'quality_preparation'):
        value = summary.get(name)
        size = newlines = 0
        for chunk in encoder.iterencode(value):
            size += len(chunk.encode('utf-8')); newlines += chunk.count('\n')
        # Values are nested one level inside each array record. Each encoded
        # newline receives four spaces (object key indent2 + array indent2).
        result[name] = {'json_value_bytes': size, 'encoded_newlines': newlines,
                       'value_bytes_at_metric_array_depth': size + 4 * newlines}
    return result


def _json_ref(path, sha):
    return {'path': str(path), 'sha256': sha}


def cap_gzip_preparation_census(io):
    """Verified immutable gzip reads only. No raw path is created or changed."""
    io.read_path(CAP_ARCHIVE_ACCEPTANCE_PATH, CAP_ARCHIVE_ACCEPTANCE_SHA)
    closure = io.read_path(CAP_CLOSURE_PATH, CAP_CLOSURE_SHA)
    v1.need(closure['archives'] == 96 and closure['raw_bytes'] == 910863,
            'wrong independently accepted cap retention census')
    rows, seen = [], set()
    for stage in closure['stages']:
        for entry in stage['evidence']:
            manifest = io.read_ref(entry['archive_manifest'])
            raw = entry['raw']
            v1.need(manifest['kind'] == 'immutable-lossless-archive-manifest'
                and manifest['archive_path'] == entry['archive_path']
                and manifest['raw_path'] == raw['path']
                and manifest['raw_sha256'] == raw['sha256']
                and manifest['raw_bytes'] == raw['bytes'], 'cap immutable archive identity mismatch')
            v1.need(raw['path'] not in seen and 0 <= raw['bytes'] <= 1024 * 1024,
                    'duplicate/unbounded cap summary')
            seen.add(raw['path'])
            io.file_ref(entry['archive_path'], manifest['gzip_sha256'], max_bytes=1024 * 1024)
            with gzip.open(entry['archive_path'], 'rb') as stream:
                data = stream.read(raw['bytes'] + 1)
                v1.need(stream.read(1) == b'', 'cap gzip decompression exceeds declared size')
            v1.need(len(data) == raw['bytes'] and hashlib.sha256(data).hexdigest() == raw['sha256'],
                    'cap gzip reconstructed bytes/SHA mismatch')
            summary = v1.strict_json(data.decode('utf-8'))
            matches = [window for window in v1.WINDOWS if window in raw['path']]
            v1.need(len(matches) == 1, 'cap archive window ambiguous')
            rows.append(dict(role='cap_target', window=matches[0],
                id=Path(raw['path']).parents[1].name, raw_bytes=len(data),
                source_sha256=raw['sha256'], archive_manifest=entry['archive_manifest'],
                fields=prep_passthrough_bytes(summary)))
    v1.need(len(rows) == 96 and sum(row['raw_bytes'] for row in rows) == 910863
        and Counter(row['window'] for row in rows) == Counter({window:24 for window in v1.WINDOWS}),
        'cap96 archive census/window partition differs')
    return rows


def census(out):
    io = v1.BoundIO()
    initial_path = ROOT/'experiments/initial-source-quality-tune-v3-seed/plan.json'
    initial = io.read_path(initial_path, v1.INITIAL_PLAN_SHA)
    source_b_path = ROOT/'experiments/source-B-12policy-serving-v1-run/plan.json'
    source_b = io.read_path(source_b_path, v1.SOURCE_B_PLAN_SHA)
    seed_root = ROOT/'analysis/selector-tune-v3-manifest-attempt02'
    manifest = io.read_path(seed_root/'MANIFEST.json', v1.SEED_MANIFEST_SHA)
    lineage = FrozenLineageLabels(io.read_path(LINEAGE_PATH, LINEAGE_SHA))
    candidates_ref = _json_ref(seed_root/'CANDIDATE_ROWS.jsonl', manifest['outputs']['CANDIDATE_ROWS.jsonl'])
    members_ref = _json_ref(seed_root/'POOL_MEMBERS.jsonl', manifest['outputs']['POOL_MEMBERS.jsonl'])
    members = list(io.jsonl_ref(members_ref))
    initial_ids = v1.stable_variant_ids(initial, v1.DEFAULT_INITIAL_CONTROLS)
    initial_union, original_states = v1.seed_union_check(initial, initial_ids, manifest,
        io.jsonl_ref(candidates_ref), members, lineage)
    v1.write_json(out/'ORIGINAL192_DONOR_UNION_CHECK.json', initial_union)
    with (out/'ORIGINAL192_OFFER_LEDGER.jsonl').open('x') as stream:
        for row in original_states:
            stream.write(v1.canonical(row) + '\n')
    original_statuses = Counter(row['independent_status'] for row in original_states)
    original_unknown = sum(not row['independent_complete'] for row in original_states)
    del original_states
    frontier_root = ROOT/'analysis/source-B-96-frontier-v1-attempt01'
    projection = io.read_path(frontier_root/'REPORT.json', v1.SOURCE_B_PROJECTION_REPORT_SHA)
    coverage = io.read_path(frontier_root/'COVERAGE_REFERENCE_ACCEPTANCE.json', v1.SOURCE_B_COVERAGE_SHA)
    parity = io.read_path(frontier_root/'NATIVE_POLICY_PARITY_88.json', v1.SOURCE_B_PARITY_SHA)
    source_b_ids = v1.stable_variant_ids(source_b, ['finite20-lean-k3'])
    v1.check_source_B_reduction(source_b, coverage, parity, source_b_ids)
    # This is the already accepted Source-B outcome/feature-map binding, not a
    # pass reader and not a reconstruction. All three stage states must agree.
    quality_path = ROOT/'analysis/source-B-96-native-ancestry-v1-attempt01/QUALITY_ROWS.jsonl'
    quality_sha = projection['inputs'][str(quality_path)]
    source_b_states, source_b_stages = {}, {}
    source_b_runs = v1.source_runs(source_b)
    for row in io.jsonl_ref(_json_ref(quality_path, quality_sha)):
        key = row['run'], row['query_id']
        v1.need(row['run'] in source_b_runs, 'unoffered Source-B state')
        state = (row['complete'], row['status'], row['dataset_sha256'], row['window'])
        v1.need(key not in source_b_states or source_b_states[key] == state, 'Source-B stages disagree')
        source_b_states[key] = state
        stages = source_b_stages.setdefault(key, set())
        v1.need(row['stage'] not in stages, 'duplicate Source-B state stage')
        stages.add(row['stage'])
    v1.need(len(source_b_states) == 5760 and all(stages == {'raw', 'final', 'display'}
         for stages in source_b_stages.values()), 'Source-B full5760 state census differs')
    source_b_per_run = Counter(key[0] for key in source_b_states)
    v1.need(len(source_b_per_run) == 96 and all(count == 60 for count in source_b_per_run.values()),
            'Source-B full96 process offer census differs')
    with (out/'SOURCE_B96_OFFER_LEDGER.jsonl').open('x') as stream:
        for (rid, qid), (complete, status, dataset, window) in sorted(source_b_states.items()):
            stream.write(v1.canonical(dict(run=rid, query_id=qid, complete=complete,
                status=status, dataset_sha256=dataset, window=window)) + '\n')
    source_b_report_path = ROOT/'analysis/source-B-96-native-ancestry-v1-attempt01/REPORT.json'
    source_b_report = io.read_path(source_b_report_path, projection['evaluator_report_sha256'])
    prep_rows, prep_failures = [], []
    for role, plan, campaign, ids, authority in (
        ('initial11_controls', initial, initial_path.parent, initial_ids, manifest['inputs']),
        ('source_B_finite20_controls', source_b, source_b_path.parent, source_b_ids, source_b_report['inputs'])):
        runs = v1.source_runs(plan)
        for rid in ids:
            path = campaign/rid/'artifact/summary.json'
            if not path.is_file():
                prep_failures.append(dict(role=role, id=rid, window=runs[rid]['window'],
                    status='UNRESOLVED_ORIGINAL_SUMMARY_NOT_PRESENT_NO_RESTORE_AUTHORIZED'))
                continue
            expected = authority.get(str(path))
            v1.need(expected is not None, 'old control summary absent from accepted source binding')
            # Cap parsing cost before allocation; larger fields stay unknown.
            size = path.stat().st_size
            if size > 16 * 1024 * 1024:
                prep_failures.append(dict(role=role, id=rid, window=runs[rid]['window'],
                    raw_bytes=size, status='UNRESOLVED_SUMMARY_OVER_BOUNDED16MiB_PARSE'))
                continue
            summary = io.read_path(path, expected, max_bytes=16 * 1024 * 1024)
            prep_rows.append(dict(role=role, id=rid, window=runs[rid]['window'],
                raw_bytes=size, source_sha256=expected, fields=prep_passthrough_bytes(summary)))
            del summary
    cap_prep_rows = cap_gzip_preparation_census(io)
    v1.write_json(out/'CAP96_GZIP_PREPARATION_FIELD_CENSUS.json',
        dict(schema='finite-cap96-verified-gzip-preparation-field-census-v2',
             rows=cap_prep_rows, raw_restore_performed=False, raw_bytes=910863))
    v1.write_json(out/'OLD_CONTROL_PREPARATION_FIELD_CENSUS.json',
        dict(schema='finite-old-control-preparation-field-census-v2', rows=prep_rows,
             unresolved=prep_failures, full_metric_size_claim=False))
    windows = {}
    all11 = ['METRICS_BY_RUN.json', 'CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl',
        'ORACLE_COMPARISONS.json', 'QUALITY_ROWS.jsonl', 'QUALITY_AGGREGATE.json',
        'INDEPENDENT_ORACLE_SLOTS.json', 'NATIVE_COUNTEREXAMPLES.json',
        'VALIDATION_ERRORS.json', 'REPORT.json', 'FEASIBLE_REFERENCE_IMPORT.json',
        'FEASIBLE_REFERENCE_PROVENANCE.json']
    for window in v1.WINDOWS:
        rows = [row for row in prep_rows + cap_prep_rows if row['window'] == window]
        windows[window] = dict(
            selected_old_control_processes=sum(run['window'] == window for run in initial['runs'] if run['id'] in set(initial_ids)) + 2,
            summaries_counted=len(rows),
            raw_summary_bytes=sum(row['raw_bytes'] for row in rows),
            preparation_value_bytes_at_actual_metric_depth=sum(field['value_bytes_at_metric_array_depth']
                for row in rows for field in row['fields'].values()),
            original_path_restore_peak_bytes=None,
            v4_file_upper_bytes={name: None for name in all11},
            projection_and_metadata_upper_bytes=None, failure_partial_peak_bytes=None,
            gzip_workspace_upper_bytes=None, original_reserve_bytes=1_000_000_000,
            total_required_free_bytes=None,
            why_pending='Counted exact old preparation passthrough values only. Cap fields, full metric skeleton, all ten other outputs/projections and overlaps need source-matched bounds; no compact/newline or max-observation extrapolation.')
    draft = dict(schema='finite-analysis-source-census-resource-draft-v2',
        status='CENSUS_ONLY_NOT_NUMERIC_AUTHORITY_OR_OPERATION_ADMISSION',
        original192_processes=192, original192_offers=11520,
        original192_unknown_offers=original_unknown, original192_statuses=dict(original_statuses),
        original192_retained_controls=len(initial_ids),
        donor_union_status=initial_union['status'], donor_union_differences=len(initial_union['differences']),
        source_B_original_processes=96, source_B_original_offers=5760,
        source_B_retained_control_processes=8, source_B_exact_parity_links=88,
        source_B_complete_offers=sum(state[0] for state in source_b_states.values()),
        old_control_summaries_counted=len(prep_rows), old_control_summaries_unresolved=len(prep_failures),
        preliminary_3_1GB_is_adopted_authority=False,
        gzip_workspace_rule='M + M//100 + 1048576, additional to original1000000000 reserve',
        windows=windows, inputs=io.bindings,
        cap_summary_archives_read=True, cap_summary_raw_bytes_verified=910863,
        datasets_models_or_native216_payloads_read=False,
        native_helpers_or_v4_executed=False, views_or_restores_created=False)
    v1.write_json(out/'RESOURCE_DRAFT.json', draft)
    v1.write_json(out/'REPORT.json', draft)
    return draft


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet-old-census-open', action='store_true')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    v1.need(args.quiet_old_census_open, 'explicit old read-only census release required')
    out = v1.absolute(args.out)
    v1.need(out.parent == HERE and not out.exists(), 'fresh own census directory required')
    out.mkdir()
    result = census(out)
    print(json.dumps({key: result[key] for key in (
        'status', 'original192_processes', 'original192_offers', 'original192_unknown_offers',
        'original192_retained_controls', 'donor_union_status', 'donor_union_differences',
        'source_B_original_processes', 'source_B_original_offers', 'source_B_exact_parity_links',
        'old_control_summaries_counted', 'old_control_summaries_unresolved')}, sort_keys=True))


if __name__ == '__main__':
    main()
