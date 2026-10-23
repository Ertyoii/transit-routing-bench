#!/usr/bin/env python3
"""Explicitly released metadata-only census; no views/restore/evaluator/helpers."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).absolute().parent
SPEC = importlib.util.spec_from_file_location('finite_operational_inert_census',
                                              HERE/'read_old_control_census_v2.py')
old = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(old)
v1 = old.v1
A = v1.ROOT.parent/'campaign-v2-audit-20261021'
Q = v1.ROOT/'qualification/cap96-native216-v1-bindings'


def metrics_paths(payload):
    found = set()
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(key); walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
        elif isinstance(value, str) and value.startswith('/') and value.endswith('/METRICS_BY_RUN.json'):
            found.add(value)
    walk(payload)
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet-metadata-open', action='store_true')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    v1.need(args.quiet_metadata_open, 'owner metadata slot missing')
    out = v1.absolute(args.out)
    v1.need(out.parent == HERE and not out.exists(), 'fresh own metadata root required')
    out.mkdir()
    io = v1.BoundIO()
    numeric_ref = dict(path=str(A/'RUNTIME8_NUMERIC_OWNER_REQUEST_ACCEPTANCE_V1.json'),
        sha256='d36f23fa060fec6050c321352085603833e0de0b4d9bdd43b609f7063ee1af88', bytes=3911)
    numeric = io.read_ref(numeric_ref)
    v1.need(numeric['status'] == 'INDEPENDENTLY_ACCEPTED'
        and numeric['unchanged_v4']['sha256'] == v1.PINS['analysis/evaluate_v2_feasible_safe_fill_v4.py'],
        'prior empirical policy is not accepted unchanged V4')
    owner_ref = numeric['owner_request']
    owner = io.read_ref(owner_ref)
    request_ref = dict(path=str(Q/'STORAGE_REQUEST_ALL320.json'),
        sha256='1b218f7d3bfbe686464bc19e8acf369845217f97fcddd70bfecea328ac68580b', bytes=662769)
    admission_ref = dict(path=str(Q/'STORAGE_ADMISSION_ALL320.json'),
        sha256='ce43004fd965b04f6655f1b6b2830ab3936c20e76694d0a9f2b8ba0df0277ab0', bytes=679533)
    request, admission = io.read_ref(request_ref), io.read_ref(admission_ref)
    request_paths, admission_paths = metrics_paths(request), metrics_paths(admission)
    v1.need(len(request_paths) == 8 and request_paths == admission_paths,
        'original prospective eight-METRICS path census differs')
    method_root = v1.ROOT/'experiments/certified-k3k5-all240-methodology-v1-run'
    paths = sorted(method_root.glob('*/artifact/summary.json'))
    v1.need(len(paths) == 8, 'old methodology summary census differs from eight')
    rows = []
    with (out/'METHODOLOGY_PREPARATION_FIELDS.partial.jsonl').open('x') as partial:
        for path in paths:
            ref = io.file_ref(path, max_bytes=8*1024*1024)
            summary = io.read_ref(ref)
            matches = [window for window in v1.WINDOWS if window in str(path)]
            v1.need(len(matches) == 1, 'methodology window identity ambiguous')
            row = dict(role='methodology_control', id=path.parents[1].name,
                window=matches[0], source=ref, raw_bytes=ref['bytes'],
                fields=old.prep_passthrough_bytes(summary))
            rows.append(row)
            partial.write(v1.canonical(row)+'\n'); partial.flush()
            del summary
    v1.need(all(sum(row['window'] == window for row in rows) == 2 for window in v1.WINDOWS),
            'methodology two-per-window partition differs')
    result = dict(schema='finite-operational-resource-metadata-census-v1',
        status='SOURCE_METADATA_ONLY_NOT_NEW_NUMERIC_AUTHORITY', inputs=io.bindings,
        prior_numeric_acceptance=numeric_ref, prior_accepted_owner_request=owner_ref,
        prior_numeric_acceptance_source=numeric, prior_owner_request_source=owner,
        original_storage_request=request_ref, original_storage_admission=admission_ref,
        original_future_metrics_paths=request_paths, methodology_preparation_rows=rows,
        unchanged_v4=numeric['unchanged_v4'],
        methodology_per_window={window:dict(summaries=2,
            raw_bytes=sum(row['raw_bytes'] for row in rows if row['window'] == window),
            preparation_value_bytes_at_metric_array_depth=sum(field['value_bytes_at_metric_array_depth']
                for row in rows if row['window'] == window for field in row['fields'].values()))
            for window in v1.WINDOWS},
        new_views_restores_evaluation_helper_execution_or_models=False)
    v1.write_json(out/'REPORT.json', result)
    print(json.dumps(dict(status=result['status'], original_future_metrics_paths=request_paths,
        methodology_per_window=result['methodology_per_window'],
        prior_owner_request_keys=list(owner), original_storage_request_keys=list(request),
        original_storage_admission_keys=list(admission)), sort_keys=True))


if __name__ == '__main__':
    main()
