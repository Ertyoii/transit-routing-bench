#!/usr/bin/env python3
"""Strict byte parity of two fresh offline evaluations, except evaluator binding."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk := f.read(1024 * 1024): h.update(chunk)
    return h.hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--original', type=Path, required=True)
p.add_argument('--bounded', type=Path, required=True)
p.add_argument('--report', type=Path, required=True)
a = p.parse_args()
here = Path(__file__).resolve().parent
old_source, new_source = here / 'evaluate_v2.py', here / 'evaluate_v2_bounded_memory.py'
expected_files = {'REPORT.json', 'METRICS_BY_RUN.json', 'QUALITY_AGGREGATE.json', 'QUALITY_ROWS.jsonl',
                  'INDEPENDENT_ORACLE_SLOTS.json', 'ORACLE_COMPARISONS.json',
                  'NATIVE_COUNTEREXAMPLES.json', 'VALIDATION_ERRORS.json'}
for directory in [a.original, a.bounded]:
    assert {x.name for x in directory.iterdir()} == expected_files, ('output file set changed', str(directory))
checks = []
for name in sorted(expected_files - {'REPORT.json'}):
    old, new = a.original / name, a.bounded / name
    old_hash, new_hash = sha(old), sha(new)
    checks.append({'name': name, 'original_sha256': old_hash, 'bounded_sha256': new_hash,
                   'bytes': old.stat().st_size, 'byte_exact': old_hash == new_hash})
old_report = json.loads((a.original / 'REPORT.json').read_text())
new_report = json.loads((a.bounded / 'REPORT.json').read_text())
old_inputs, new_inputs = old_report['inputs'], new_report['inputs']
assert old_inputs.pop(str(old_source)) == sha(old_source), 'original evaluator binding wrong'
assert new_inputs.pop(str(new_source)) == sha(new_source), 'bounded evaluator binding wrong'
report_equal = old_report == new_report
result = {'schema': 'sg-evaluator-memory-revision-parity-v1',
          'original_evaluator': {'path': str(old_source), 'sha256': sha(old_source)},
          'bounded_evaluator': {'path': str(new_source), 'sha256': sha(new_source)},
          'original_output': str(a.original.resolve()), 'bounded_output': str(a.bounded.resolve()),
          'files': checks, 'report_equal_except_evaluator_binding': report_equal,
          'all_exact': report_equal and all(x['byte_exact'] for x in checks),
          'offered_run_rows': new_report['offered_run_rows'], 'runs': new_report['runs'],
          'independent_reconstruction_errors': new_report['independent_reconstruction_errors'],
          'native_contract_counterexamples': new_report['native_contract_counterexamples'],
          'oracle_offered_slots': new_report['oracle_offered_slots'],
          'oracle_complete_slots': new_report['oracle_complete_slots']}
a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps(result, sort_keys=True))
raise SystemExit(not result['all_exact'])
