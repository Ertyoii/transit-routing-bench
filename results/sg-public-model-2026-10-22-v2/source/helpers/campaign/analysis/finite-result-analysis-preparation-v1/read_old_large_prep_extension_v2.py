#!/usr/bin/env python3
"""Owner-released16-old-summary limit correction. No helpers/models/seed maps.

Fresh partials survive any CPU/AS/wall failure. Uses the accepted seed manifest
only for16 original SHA identities; all scientific union results are inherited
from the preserved attempt01 receipt, not recomputed or weakened.
"""
from __future__ import annotations
import argparse
import gc
import importlib.util
import json
from pathlib import Path
import resource
import sys

HERE = Path(__file__).absolute().parent
SPEC = importlib.util.spec_from_file_location('finite_extension_inert_census',
                                              HERE/'read_old_control_census_v2.py')
old = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(old)
v1 = old.v1
ATTEMPT01 = HERE/'read-only-census-attempt01-20261022T0227Z'
INITIAL = v1.ROOT/'experiments/initial-source-quality-tune-v3-seed'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet-old-prep-extension-open', action='store_true')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    v1.need(args.quiet_old_prep_extension_open, 'owner prep-extension slot missing')
    out = v1.absolute(args.out)
    v1.need(out.parent == HERE and not out.exists(), 'fresh own result root required')
    out.mkdir()
    # These are newly created own results, not newly read scientific payloads.
    prior = v1.strict_json((ATTEMPT01/'OLD_CONTROL_PREPARATION_FIELD_CENSUS.json').read_text())
    cap = v1.strict_json((ATTEMPT01/'CAP96_GZIP_PREPARATION_FIELD_CENSUS.json').read_text())
    draft = v1.strict_json((ATTEMPT01/'RESOURCE_DRAFT.json').read_text())
    pending = prior['unresolved']
    v1.need(len(pending) == 16 and all(row['role'] == 'initial11_controls'
        and row['status'] == 'UNRESOLVED_SUMMARY_OVER_BOUNDED16MiB_PARSE' for row in pending),
        'extension differs from exact16 previously census-budget-only terms')
    io = v1.BoundIO()
    seed = io.read_path(v1.ROOT/'analysis/selector-tune-v3-manifest-attempt02/MANIFEST.json',
                         v1.SEED_MANIFEST_SHA)
    authority = seed['inputs']
    del seed
    extension = []
    with (out/'COMPLETED_PREPARATION_FIELDS.partial.jsonl').open('x', encoding='utf-8') as partial:
        for expected in pending:
            path = INITIAL/expected['id']/'artifact/summary.json'
            sha = authority[str(path)]
            # Stream SHA before parse. No feature/candidate map is retained.
            ref = io.file_ref(path, sha, max_bytes=50*1024*1024)
            v1.need(ref['bytes'] == expected['raw_bytes'], 'previously observed16-file size changed')
            with path.open(encoding='utf-8') as stream:
                summary = json.load(stream, object_pairs_hook=v1._pairs,
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite: '+value)))
            row = dict(role=expected['role'], id=expected['id'], window=expected['window'],
                path=str(path), source_sha256=sha, raw_bytes=ref['bytes'],
                fields=old.prep_passthrough_bytes(summary),
                prior_status='UNRESOLVED_SOLELY_CENSUS_READER16MiB_BUDGET',
                peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            extension.append(row)
            partial.write(v1.canonical(row)+'\n')
            partial.flush()
            del summary
            gc.collect()
            print(json.dumps(dict(completed=len(extension), id=row['id'],
                raw_bytes=row['raw_bytes'], peak_rss_kib=row['peak_rss_kib'])), flush=True)
    combined = prior['rows'] + extension
    v1.need(len(combined) == 96 and len({(row['role'],row['id']) for row in combined}) == 96,
            'full96 old-control prep census differs')
    v1.write_json(out/'OLD_CONTROL_PREPARATION_FIELD_CENSUS_COMPLETE.json',
        dict(schema='finite-old-control-preparation-field-census-complete-v2',
             rows=combined, unresolved=[], full_metric_size_claim=False,
             corrected_reader_budget_only_terms=16, inputs=io.bindings))
    all_rows = combined + cap['rows']
    for window, entry in draft['windows'].items():
        rows = [row for row in all_rows if row['window'] == window]
        v1.need(len(rows) == 48, '24 old controls +24 cap summaries/window differ')
        entry.update(summaries_counted=len(rows), raw_summary_bytes=sum(row['raw_bytes'] for row in rows),
            preparation_value_bytes_at_actual_metric_depth=sum(field['value_bytes_at_metric_array_depth']
                for row in rows for field in row['fields'].values()),
            original_path_cap_target_restore_bytes=sum(row['raw_bytes'] for row in rows
                if row['role'] == 'cap_target'),
            why_pending='Exact all96 old-control plus96 cap preparation-value census complete. The8 methodology summaries and full metric non-preparation constructor, all ten other V4 outputs/projections, reference companions and partial-overlap upper bounds are not authorized/censused by this16-file slot. No guessed margin is a proven bound.')
    draft.update(status='COMPLETE_ALLOWED_PREPARATION_CENSUS_NOT_FULL_NUMERIC_AUTHORITY',
        old_control_summaries_counted=96, old_control_summaries_unresolved=0,
        reader_budget_only_terms_resolved=16, extension_inputs=io.bindings,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    v1.write_json(out/'RESOURCE_PROPOSAL_PENDING_COMPLETE_OUTPUT_BOUNDS.json', draft)
    v1.write_json(out/'REPORT.json', draft)
    print(json.dumps(dict(status=draft['status'], old_control_summaries_counted=96,
        old_control_summaries_unresolved=0, cap_summary_count=96,
        windows={name:{key:entry[key] for key in ('summaries_counted', 'raw_summary_bytes',
            'preparation_value_bytes_at_actual_metric_depth', 'original_path_cap_target_restore_bytes')}
            for name,entry in draft['windows'].items()}, peak_rss_kib=draft['peak_rss_kib'])), flush=True)


if __name__ == '__main__':
    main()
