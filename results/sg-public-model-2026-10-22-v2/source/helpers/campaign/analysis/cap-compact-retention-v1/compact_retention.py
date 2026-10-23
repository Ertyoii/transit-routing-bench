#!/usr/bin/env python3
"""Create-only compact retention. No evaluator, scoring, model, archive or retirement.

Actual execution requires separate owner release and independent exact input/output
review. The checked-in template is not execution or storage acceptance authority.
"""
import argparse
import collections
import fcntl
import hashlib
import json
from pathlib import Path
import shutil

READER_SOURCE_SHA256 = '708e4984dff98e7cf8959880f11edafe9006e29e2451ad389851bf1d6e9606c5'
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
MAX_OUTPUT_BYTES = 5_000_000
RESERVE_BYTES = 1_000_000_000
PHASES = ('preparation', 'checker_preparation', 'quality_preparation')
PHASE_FIELDS = ('complete', 'elapsed_ns', 'allocated_bytes', 'error', 'reason')
CLOCKS = ('response_ns', 'published_response_ns', 'quality_ns',
          'validation_rank_ns', 'serialization_ns', 'core_ns')
V4_FILES = ('METRICS_BY_RUN.json', 'CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl',
    'ORACLE_COMPARISONS.json', 'QUALITY_ROWS.jsonl', 'QUALITY_AGGREGATE.json',
    'INDEPENDENT_ORACLE_SLOTS.json', 'NATIVE_COUNTEREXAMPLES.json',
    'VALIDATION_ERRORS.json', 'REPORT.json', 'FEASIBLE_REFERENCE_IMPORT.json',
    'FEASIBLE_REFERENCE_PROVENANCE.json')
METADATA = ('run_roles', 'view_report', 'accepted_binding', 'resource_observations',
            'input_reader_acceptance', 'v4_acceptance')
REQUIRED_METRIC = ('id', 'campaign', 'delivery_k', 'window', 'offered',
                   'completed', 'statuses', *PHASES)

class Stop(RuntimeError):
    pass

def need(ok, message):
    if not ok:
        raise Stop(message)

def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')

def reference(path, data=None):
    path = Path(path).absolute()
    h = hashlib.sha256()
    if data is None:
        with path.open('rb') as stream:
            while part := stream.read(1024*1024):
                h.update(part)
        size = path.stat().st_size
    else:
        h.update(data)
        size = len(data)
    return dict(path=str(path), sha256=h.hexdigest(), bytes=size)

def bound(ref):
    need(isinstance(ref, dict) and set(ref) == {'path', 'sha256', 'bytes'},
         'Exact path/SHA256/bytes reference required')
    need(type(ref['bytes']) is int and ref['bytes'] >= 0
         and isinstance(ref['sha256'], str) and len(ref['sha256']) == 64
         and Path(ref['path']).is_absolute(), 'Invalid file reference')
    need(reference(ref['path']) == ref, 'Changed bound input: '+ref['path'])
    return Path(ref['path'])

def read_ref(ref):
    return json.loads(bound(ref).read_text())

# Verbatim accepted linear reader; AST equivalence is covered by fixture tests.
def iter_array(path):
    """Strict one-record reader: linear boundary scan, one JSON decode/record."""
    import re
    decoder=json.JSONDecoder();tokens=re.compile(r'["\\{}\[\]]')
    with Path(path).open() as file:
        chunk='';position=0;offset=0
        def next_nonspace():
            nonlocal chunk,position,offset
            while True:
                while position<len(chunk) and chunk[position].isspace():position+=1
                if position<len(chunk):return chunk[position]
                offset+=len(chunk);chunk=file.read(65536);position=0
                need(bool(chunk),'Truncated metrics JSON array')
        need(next_nonspace()=='[','Metrics must be JSON array');position+=1
        if next_nonspace()!=']':
            while True:
                need(next_nonspace()=='{','Metric element must be an object')
                pieces=[];stack=[];quoted=False;escaped_at=None;start=position
                while True:
                    closed=False
                    for match in tokens.finditer(chunk,position):
                        token=match.group();absolute=offset+match.start()
                        if quoted:
                            if escaped_at is not None:
                                if absolute==escaped_at:
                                    escaped_at=None;continue
                                if absolute>escaped_at:escaped_at=None
                            if token=='\\':escaped_at=absolute+1
                            elif token=='"':quoted=False
                        elif token=='"':quoted=True
                        elif token in '{[':stack.append('}' if token=='{' else ']')
                        elif token in '}]':
                            need(bool(stack) and stack.pop()==token,'Mismatched metrics JSON nesting')
                            if not stack:
                                position=match.end();pieces.append(chunk[start:position]);closed=True;break
                    if closed:break
                    pieces.append(chunk[start:]);offset+=len(chunk);chunk=file.read(65536);position=0;start=0
                    need(bool(chunk),'Truncated/invalid metrics JSON')
                record=''.join(pieces)
                try:value,end=decoder.raw_decode(record)
                except json.JSONDecodeError as error:raise Stop('Invalid metrics JSON record') from error
                need(end==len(record) and isinstance(value,dict),'Invalid/non-object metrics element')
                yield value
                record=None;pieces=None;value=None
                token=next_nonspace()
                if token==']':break
                need(token==',','Missing metrics comma');position+=1
                need(next_nonspace()!=']','Trailing metrics comma')
        position+=1
        need(not chunk[position:].strip(),'Trailing metrics bytes')
        while True:
            trailing=file.read(65536)
            if not trailing:return
            need(not trailing.strip(),'Trailing metrics bytes')

def compact_metric(metric, source):
    need(isinstance(metric, dict) and all(k in metric for k in REQUIRED_METRIC),
         'Missing required metric field')
    need('_source_metrics' not in metric, 'Reserved metric pointer collision')
    result = dict(metric)
    pointer = dict(source, run_id=metric['id'])
    result['_source_metrics'] = pointer
    for phase in PHASES:
        raw = metric[phase]
        need(raw is None or isinstance(raw, dict), 'Invalid preparation object')
        if raw is not None:
            result[phase] = {k: raw.get(k) for k in PHASE_FIELDS}
            result[phase]['_source_metrics'] = dict(pointer, phase=phase,
                fields_present=[k for k in PHASE_FIELDS if k in raw])
    return result


def build(request_ref, out):
    """Only read named proof/output files and bound original summary/ordinary passes.

    Never follow any dataset/model/native-reference paths appearing in provenance.
    Fully serialize/precount all outputs before mkdir/write. Failure preserves all
    existing inputs, and any partial new output is never removed or overwritten.
    """
    request = read_ref(request_ref)
    need(request.get('schema') == 'sg-cap-compact-retention-request-v1', 'Bad request schema')
    need(set(request.get('outputs', {})) == set(V4_FILES), 'Exactly all eleven V4 refs required')
    need(set(request.get('metadata', {})) == set(METADATA), 'Missing exact provenance refs')
    outputs = request['outputs']; metadata = request['metadata']; window = request['window']
    out = Path(out).absolute()
    need(not out.exists(), 'Create-only output must be absent')
    need(out.parent.is_dir(), 'Output parent must already exist')
    need(shutil.disk_usage(out.parent).free >= RESERVE_BYTES+MAX_OUTPUT_BYTES,
         'Insufficient admitted 1GB reserve plus 5MB output allowance')
    for name, ref in outputs.items():
        need(Path(ref['path']).name == name, 'V4 basename changed')
        bound(ref)
    docs = {name: read_ref(ref) for name, ref in metadata.items()}
    roles_doc = docs['run_roles']; roles = roles_doc['rows']
    need(roles_doc.get('all_metric_processes') == 50
         and roles_doc.get('all_metric_offers') == 3000, 'Role denominator changed')
    need(len(roles) == 50 and len({r['id'] for r in roles}) == 50, 'Duplicate/missing original role id')
    receipt = docs['input_reader_acceptance']
    need(receipt.get('status') == 'INDEPENDENTLY_ACCEPTED_INPUT_READER_ONLY'
         and receipt.get('window') == window and receipt.get('all_processes') == 50
         and receipt.get('ordinary_offers') == 3000, 'Accepted input reader scope changed')
    accepted = {r['run_id']: r for r in receipt['runs']}
    need(len(receipt['runs']) == len(accepted) == 50, 'Duplicate accepted original id')
    by_role = {r['id']: r for r in roles}
    need(set(by_role) == set(accepted), 'Exact original50 id set changed')
    for rid, r in by_role.items():
        a = accepted[rid]
        need(r['window'] == window and r['offered'] == a['ordinary_offers'] == 60
             and r['role'] == a['role']
             and str(Path(r['original_campaign'])/rid) == a['original'],
             'Original role/source/offer locator changed')
    report = read_ref(outputs['REPORT.json'])
    need(report.get('schema') == 'sg-independent-v2-feasible-safe-fill-v4'
         and report.get('runs') == 50 and report.get('offered_run_rows') == 3000,
         'V4 report denominator/schema changed')
    authoritative = report['inputs']
    compact = []; metric_by_id = {}; original_order = []
    for metric in iter_array(Path(outputs['METRICS_BY_RUN.json']['path'])):
        row = compact_metric(metric, outputs['METRICS_BY_RUN.json']); rid = row['id']
        need(rid not in metric_by_id, 'Duplicate V4 metric id')
        need(rid in accepted and row['offered'] == 60 and row['window'] == window
             and row['delivery_k'] == accepted[rid]['delivery_k']
             and str(Path(row['campaign'])/rid) == accepted[rid]['view'],
             'V4 original ID, view locator, offers or delivery cohort changed')
        metric_by_id[rid] = row; original_order.append(rid); compact.append(row)
    need(set(metric_by_id) == set(accepted) and len(compact) == 50,
         'Do not filter any original V4 contributor')
    cohorts = {str(k): sum(r['offered'] for r in compact if r['delivery_k'] == k) for k in (3, 5)}
    need(report.get('serving_cohort_offered') == cohorts, 'V4 per-k denominator changed')
    quality = collections.defaultdict(dict)
    with Path(outputs['QUALITY_ROWS.jsonl']['path']).open() as stream:
        for line in stream:
            q = json.loads(line); rid = q['run']; qid = q['query_id']; stage = q['stage']
            need(rid in accepted and stage in ('raw', 'final', 'display')
                 and stage not in quality[(rid, qid)]
                 and q['delivery_k'] == accepted[rid]['delivery_k'], 'Changed/duplicate authoritative quality slot')
            quality[(rid, qid)][stage] = {k: q[k] for k in ('complete', 'status', 'common_pool_cohort')}
    qids_by_run = {rid: {qid for rr, qid in quality if rr == rid} for rid in original_order}
    need(all(len(ids) == 60 for ids in qids_by_run.values()), 'All original50 must keep all60 offered qids')
    need(all(len(stages) == 3 and stages['raw'] == stages['final'] == stages['display']
             for stages in quality.values()), 'Missing quality stage or independent outcome/cohort mismatch')
    sources = []; source_indexes = {}; ordinary = []
    def source_index(ref):
        key = (ref['path'], ref['sha256'], ref['bytes'])
        if key not in source_indexes:
            source_indexes[key] = len(sources); sources.append(ref)
        return source_indexes[key]
    for rid in original_order:
        role = by_role[rid]; metric = metric_by_id[rid]; a = accepted[rid]
        original_artifact = Path(role['original_campaign'])/rid/'artifact'
        alias_artifact = Path(metric['campaign'])/rid/'artifact'
        summary_ref = role['original_summary_state']['summary']
        need(summary_ref is not None and summary_ref == a['summary']
             and summary_ref['path'] == str(original_artifact/'summary.json')
             and authoritative.get(str(alias_artifact/'summary.json')) == summary_ref['sha256'],
             'Original summary is not exactly input-reader and V4-bound')
        summary = read_ref(summary_ref); source_index(summary_ref); records = {}
        for desc in summary.get('passes', []):
            if desc.get('forced') or desc.get('warmup'):
                continue
            name = desc['file']
            need(Path(name).name == name and name not in ('', '.', '..'), 'Unsafe ordinary pass name')
            need(authoritative.get(str(alias_artifact/name)) == desc['sha256'],
                 'Ordinary pass not V4-bound')
            path = original_artifact/name; ref = reference(path)
            need(ref['sha256'] == desc['sha256'], 'Original ordinary pass changed')
            index = source_index(ref); payload = json.loads(path.read_text())
            for r in payload['records']:
                qid = r['query']['id']
                need(qid in qids_by_run[rid] and qid not in records, 'Unknown/duplicate ordinary query')
                records[qid] = ({k: r.get(k) for k in (*CLOCKS, 'attempted', 'completed', 'transit', 'valid_empty')}, index)
        need(metric['completed'] == sum(quality[(rid, qid)]['display']['complete'] for qid in qids_by_run[rid]),
             'Independent metric completion differs from authoritative display-stage rows')
        for qid in sorted(qids_by_run[rid]):
            q = quality[(rid, qid)]['display']; r, index = records.get(qid, ({}, None))
            ordinary.append(dict(run=rid, query_id=qid, delivery_k=metric['delivery_k'],
                ordinary_record_present=qid in records, attempted=r.get('attempted'),
                emitter_completed=r.get('completed'), emitter_transit=r.get('transit'),
                emitter_valid_empty=r.get('valid_empty'), independently_complete=q['complete'],
                independent_status=q['status'], common_pool_cohort=q['common_pool_cohort'],
                original_record_source_index=index, **{k: r.get(k) for k in CLOCKS}))
    need(len(ordinary) == 3000, 'Exact50x60 ordinary offer denominator changed')
    metrics_data = encoded(compact)
    ordinary_data = b''.join(encoded(row) for row in ordinary)
    files = {'COMPACT_METRICS_BY_RUN.json': metrics_data, 'ORDINARY_ACTUAL_ROWS.jsonl': ordinary_data}
    manifest = dict(schema='sg-cap-compact-retention-v1', window=window,
        scope='Retention only; unchanged V4 remains scientific authority. No archive or retirement authority.',
        request=request_ref, outputs=outputs, metadata=metadata,
        original_run_ids_in_metrics_order=original_order, all_metric_processes=50,
        all_metric_offers=3000, serving_cohort_offered=cohorts,
        original_roles_and_offers=roles_doc, original_record_sources=sources,
        authoritative_ordinary_quality=dict(source=outputs['QUALITY_ROWS.jsonl'], stage='display',
            selector_fields=['run', 'query_id', 'stage']),
        accepted_input_provenance=docs['accepted_binding'], original_view_provenance=docs['view_report'],
        resource_observations=docs['resource_observations'], v4_report=report,
        compact_outputs={name: reference(out/name, data) for name, data in files.items()},
        prospective_total_output_cap_bytes=MAX_OUTPUT_BYTES, reserve_bytes=RESERVE_BYTES,
        raw_ordinary_passes_remain_intact=True, raw_metrics_recovery_requires_separate_verified_gzip=True,
        no_native_model_reads=True, no_scoring_or_oracle_changes=True)
    files['RETENTION_MANIFEST.json'] = encoded(manifest)
    total = sum(map(len, files.values()))
    need(total <= MAX_OUTPUT_BYTES,
         'Exact prospective compact output needs '+str(total)+' bytes, above admitted '
         +str(MAX_OUTPUT_BYTES)+'; wrote nothing')
    need(shutil.disk_usage(out.parent).free >= RESERVE_BYTES+total, 'Reserve changed before create')
    out.mkdir()
    for name, data in files.items():
        need(shutil.disk_usage(out).free-len(data) >= RESERVE_BYTES, 'Reserve changed while writing; preserve partials')
        with (out/name).open('xb') as stream:
            stream.write(data)
    return dict(outputs={name: reference(out/name, data) for name, data in files.items()},
                total_bytes=total, runs=50, offers=3000, serving_cohort_offered=cohorts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--request-sha256', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--quiet-window-open', action='store_true')
    args = parser.parse_args()
    need(args.quiet_window_open, 'Owner-admitted quiet slot is required')
    path = Path(args.request).absolute()
    request_ref = dict(path=str(path), sha256=args.request_sha256, bytes=path.stat().st_size)
    with LOCK.open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(build(request_ref, args.out_dir), sort_keys=True))

if __name__ == '__main__':
    main()
