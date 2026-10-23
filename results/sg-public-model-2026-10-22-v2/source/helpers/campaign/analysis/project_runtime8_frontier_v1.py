#!/usr/bin/env python3
"""Create-only projection of FOUR independently accepted full-closure V4 views.

STATIC DRAFT: do not import/test/run during a measurement stage. This is not an
evaluator, selector, source method, acceptance authority, or winner selector.
No models, router binaries or campaign modules are loaded. Both commands require
an explicit quiet slot and acquire campaign.lock themselves (never outer-wrap).
Window inputs must be independently accepted, hash-bound closure manifests.
"""
import argparse
import collections
import fcntl
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
READY_SHA = 'df73087ae90637ebcdde2b1348b06109f700fa8d751a661cd28d7717d0bc2acb'
V4_SHA = 'b75ff1d989896d411fa33d39f70ccc995a2af25f5b2d598c23fa0004c1dc37b0'
SELECTOR_SHA = 'e15b386211fd5002a37d13076dd5577b95da1c27aafe6043eaa8ab876f9ea612'
SOURCE_BINDINGS = {
    'source_B': ('8f13517d8a75df4c155e735eb1a03bbfd80012f3cd0de7e32827d1cb13b3628f',
                 '549b16803348c97df08e37c880e9ec2f43fdea9a7e5f5e92bc8db3a9dd9d0e8f'),
    'old_native': ('05a41ecd0b4687e83b57d8a548835137c2d049755815dcbef01bb92590a17800',
                   'c9a9b5fc28c5696f89418e29261269497222cc4a8981482426e1ce5a73324d15')}
WINDOWS = tuple('weekday-' + s + '-20261020' for s in ('morning', 'midday', 'evening', 'overnight'))
CELLS = tuple((str(gc), heap) for gc in (50, 100, 200) for heap in ('4GiB', '7GiB'))
PRODUCTS = (
    'raptor-local-walk-ties', 'raptor-early-local-walk-ties', 'mc-qualified-top3',
    'mc-early-qualified-top3', 'ultra-capped-local-walk-ties',
    'ultra-subset-local-walk-ties', 'tb-compact-native-capped',
    'tb-compact-answer-walk-ties', 'old-native-raptor-control',
    'old-native-raptor-early-control', 'old-native-mc-control',
    'old-native-mc-early-control', 'old-native-ultra-capped-control',
    'old-native-ultra-subset-control')
# Exactly the accepted compare_native_outputs.py FIELDS, including witness order.
NATIVE_FIELDS = ('query', 'stratum', 'raw', 'final', 'completed', 'attempted',
                 'valid_empty', 'transit', 'status', 'error', 'certificates')
CLOCK_FIELDS = ('response_ns', 'published_response_ns', 'quality_ns',
                'validation_rank_ns', 'serialization_ns', 'core_ns')
PROCESS_FIELDS = ('startup_phase_sum_ns', 'process_wall_s',
                 'launch_to_first_available_answer_ns',
                 'accepted_native_launch_to_first_available_answer_ns',
                 'sampled_peak_rss_bytes', 'supervisor_ok',
                 'first_published_native_row_accepted',
                 'first_answer_unavailable_reason', 'first_published_query_id',
                 'first_offered_query_id', 'first_offered_independent_status',
                 'first_offered_native_complete', 'first_offered_batch_query_ids',
                 'first_marker_matches_first_offered_query', 'first_answer_acceptance_scope',
                 'published_deadline_misses', 'preparation',
                 'checker_preparation', 'quality_preparation')
OUTPUTS = ('REPORT.json', 'METRICS_BY_RUN.json', 'QUALITY_ROWS.jsonl',
           'QUALITY_AGGREGATE.json', 'ORACLE_COMPARISONS.json')
SOURCE_PAIRS = (('old-native-mc-control', 'mc-qualified-top3'),
                ('old-native-mc-early-control', 'mc-early-qualified-top3'))
TRADEOFF_PAIRS = (('old-native-raptor-control', 'raptor-local-walk-ties'),
                 ('old-native-raptor-early-control', 'raptor-early-local-walk-ties'),
                 ('old-native-ultra-capped-control', 'ultra-capped-local-walk-ties'),
                 ('old-native-ultra-subset-control', 'ultra-subset-local-walk-ties'),
                 ('tb-compact-native-capped', 'tb-compact-answer-walk-ties'))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identity(path):
    # Preserve the exact lexical pathname bound by V4, including archive links.
    path = Path(path).absolute()
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return {'path': str(path), 'sha256': h.hexdigest(), 'bytes': path.stat().st_size}


def bound(ref, bindings):
    if not isinstance(ref, dict) or not ref.get('path') or not ref.get('sha256'):
        raise ValueError('Exact path+SHA256 reference required')
    actual = identity(ref['path'])
    if any(actual[k] != ref[k] for k in ('sha256', 'bytes') if k in ref):
        raise ValueError('Bound input changed: ' + actual['path'])
    bindings[actual['path']] = actual['sha256']
    return Path(actual['path'])


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    with Path(path).open() as stream:
        for line in stream:
            yield json.loads(line)


def array_rows(path):
    """Stream a JSON array; never retain other contributors' preparation blobs."""
    decoder = json.JSONDecoder()
    with Path(path).open() as stream:
        buffer = ''
        eof = False
        started = False
        expect_value = True
        seen = False
        while True:
            buffer = buffer.lstrip()
            if not buffer and not eof:
                chunk = stream.read(65536)
                eof = not chunk
                buffer += chunk
                continue
            if not started:
                if not buffer.startswith('['):
                    raise ValueError('Expected a JSON array')
                buffer = buffer[1:]
                started = True
                continue
            if buffer.startswith(']'):
                if expect_value and seen:
                    raise ValueError('Trailing comma in JSON array')
                if buffer[1:].strip() or stream.read().strip():
                    raise ValueError('Trailing data after JSON array')
                return
            if not expect_value:
                if not buffer.startswith(','):
                    raise ValueError('Missing JSON array separator')
                buffer = buffer[1:]
                expect_value = True
                continue
            try:
                row, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if eof:
                    raise ValueError('Truncated JSON array')
                chunk = stream.read(65536)
                eof = not chunk
                buffer += chunk
                continue
            yield row
            buffer = buffer[end:]
            expect_value = False
            seen = True


def compact_process(metric):
    value = {k: metric.get(k) for k in PROCESS_FIELDS}
    for phase in ('preparation', 'checker_preparation', 'quality_preparation'):
        raw = metric.get(phase)
        value[phase] = ({k: raw.get(k) for k in ('complete', 'elapsed_ns', 'allocated_bytes', 'error', 'reason')}
                        if isinstance(raw, dict) else None)
    return value


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def distribution(values):
    xs = sorted(values)
    if any(type(x) is not int or x < 0 for x in xs):
        raise ValueError('Actual ordinary clocks must be nonnegative integers; missing is null')
    n = len(xs)
    return {'count': n, 'p50': xs[math.ceil(.5*n)-1] if n else None,
            'p95': xs[math.ceil(.95*n)-1] if n else None,
            'p99': xs[math.ceil(.99*n)-1] if n else None,
            'max': xs[-1] if n else None,
            'method': 'empirical nearest rank of pooled actual ordinary observations; never averaged quantiles'}


def expected_slots():
    return {f'b{b}-runtime-{p}-{w}-gc{gc}-{heap}':
            {'id': f'b{b}-runtime-{p}-{w}-gc{gc}-{heap}', 'block': b,
             'product': p, 'window': w, 'runtime': {'GOGC': gc, 'GOMEMLIMIT': heap}}
            for b, p, w, (gc, heap) in itertools.product((0, 1), PRODUCTS, WINDOWS, CELLS)}


def ready_rows(value):
    rows = value['all672_state_rows']
    expected = expected_slots()
    if len(rows) != 672 or {r['id'] for r in rows} != set(expected):
        raise ValueError('READY must preserve the exact unique 672-slot Cartesian denominator')
    counts = collections.Counter(r['state'] for r in rows)
    if counts != {'PLANNED_UNSTARTED': 640, 'NOT_OFFERED_MEMORY_FORECAST': 32}:
        raise ValueError('READY must bind 640 runnable +32 forecast-refused slots')
    return {r['id']: dict(expected[r['id']], global_position=i, initial_state_row=r)
            for i, r in enumerate(rows)}


def selected_output(row):
    """Hash requested finite20 output only, not clocks; no completion promotion."""
    choices = (row.get('recommendation_quality') or {}).get('choices')
    if not isinstance(choices, dict):
        return None
    groups = choices.get('groups')
    if not isinstance(groups, list) or len(groups) != 1:
        return None
    selections = groups[0].get('selections')
    if not isinstance(selections, list) or len(selections) != 1:
        return None
    s = selections[0]
    return {'choices_complete': choices.get('complete'), 'choices_error': choices.get('error'),
            **{k: s.get(k) for k in ('limit', 'method', 'complete', 'selected')}}


def project_window(manifest_ref, out):
    bindings = {}
    manifest_path = bound(manifest_ref, bindings)
    manifest = read(manifest_path)
    if (manifest.get('schema') != 'sg-runtime8-window-acceptance-v1'
            or manifest.get('status') != 'INDEPENDENTLY_ACCEPTED'
            or manifest.get('window') not in WINDOWS):
        raise ValueError('An independently accepted full-window closure manifest is required')
    if manifest['ready_receipt']['sha256'] != READY_SHA or manifest['evaluator']['sha256'] != V4_SHA:
        raise ValueError('Exact READY and unchanged FINALV4 identities required')
    slots = ready_rows(read(bound(manifest['ready_receipt'], bindings)))
    evaluator = bound(manifest['evaluator'], bindings)
    window = manifest['window']
    slots = {k: v for k, v in slots.items() if v['window'] == window}
    runnable = {k for k, v in slots.items() if v['initial_state_row']['state'] == 'PLANNED_UNSTARTED'}
    closure = manifest['closure']
    if (closure.get('all_stage_indexes') != list(range(8))
            or set(closure['runtime_run_ids']) != runnable
            or len(closure['runtime_run_ids']) != 160
            or any(closure.get(k) is not True for k in ('scalar432_bound', 'native_references_bound',
                       'donor_ancestry_bound', 'no_algorithm_success_filter'))):
        raise ValueError('Require all eight stages and unchanged scalar/native/ancestry full closure')
    if not closure.get('state_ledger_refs'):
        raise ValueError('Hash-bound observational stage ledgers are required')
    for ref in closure['state_ledger_refs']:
        bound(ref, bindings)
    states = {r['id']: r for r in manifest['runtime_state_rows']}
    if len(manifest['runtime_state_rows']) != 168 or set(states) != set(slots):
        raise ValueError('All 168 observational states, including eight refusals, must remain')
    for rid, slot in slots.items():
        if slot['initial_state_row']['state'] == 'NOT_OFFERED_MEMORY_FORECAST' and states[rid]['state'] != 'NOT_OFFERED_MEMORY_FORECAST':
            raise ValueError('A forecast refusal cannot become an executed/zero-cost offer')
    outputs = {name: bound(manifest['outputs'][name], bindings) for name in OUTPUTS}
    report = read(outputs['REPORT.json'])
    if report['inputs'].get(str(evaluator)) != V4_SHA or not report.get('donor_lineage', {}).get('enabled'):
        raise ValueError('V4 report must bind exact evaluator and ancestry')
    by_id = {}
    metric_ids = set()
    for metric in array_rows(outputs['METRICS_BY_RUN.json']):
        rid = metric['id']
        if rid in metric_ids:
            raise ValueError('Duplicate V4 metric id')
        metric_ids.add(rid)
        if rid in runnable:
            by_id[rid] = {k: metric[k] for k in ('id', 'campaign', 'completed', 'offered', 'statuses')}
            by_id[rid].update(compact_process(metric))
    contributors = closure['contributor_run_ids']
    if len(contributors) != len(set(contributors)) or metric_ids != set(contributors) or not runnable <= set(by_id):
        raise ValueError('Do not filter the accepted V4 contributor denominator')
    authoritative = report['inputs']

    def native_read(path):
        path = Path(path).absolute()
        return read(bound({'path': str(path), 'sha256': authoritative.get(str(path))}, bindings))

    quality = collections.defaultdict(dict)
    query_ids = None
    for row in lines(outputs['QUALITY_ROWS.jsonl']):
        if row['run'] not in runnable:
            continue
        key = (row['run'], row['query_id'])
        stage = row['stage']
        if stage not in ('raw', 'final', 'display') or stage in quality[key]:
            raise ValueError('Extra/duplicate authoritative quality stage')
        if row['dataset_sha256'] != manifest['dataset_sha256'] or row['delivery_k'] != 3:
            raise ValueError('Mixed dataset or requested selector budget')
        quality[key][stage] = row
    plans = {}
    projected = []
    processes = []
    for rid in sorted(runnable):
        metric = by_id[rid]
        campaign = Path(metric['campaign'])
        if campaign not in plans:
            plans[campaign] = {r['id']: r for r in native_read(campaign/'plan.json')['runs']}
        run = plans[campaign][rid]
        if run['env'] != slots[rid]['runtime'] or run['variant_id'] != slots[rid]['product'] or run['requested_selector_limit'] != 3:
            raise ValueError('Runtime/product/requested-k differs from frozen slot')
        source = run['source_policy_binding']
        role = 'old_native' if slots[rid]['product'].startswith('old-native-') else 'source_B'
        if (source['source']['go_source_hash_sha256'], source['binary']['sha256']) != SOURCE_BINDINGS[role]:
            raise ValueError('Runtime product changed its frozen source/native binding')
        config = Path(run['argv'][run['argv'].index('-preference-scenarios')+1]).absolute()
        if authoritative.get(str(config)) != SELECTOR_SHA:
            raise ValueError('All14 must retain the exact same finite20 top3 config')
        summary_path = campaign/rid/'artifact/summary.json'
        summary = native_read(summary_path) if summary_path.exists() else {}
        records = {}
        for desc in summary.get('passes', []):
            if desc.get('forced') or desc.get('warmup'):
                continue
            if Path(desc['file']).name != desc['file']:
                raise ValueError('Unsafe ordinary pass name')
            path = (campaign/rid/'artifact'/desc['file']).absolute()
            if authoritative.get(str(path)) != desc['sha256']:
                raise ValueError('Ordinary pass is not bound by V4 and summary')
            for row in native_read(path)['records']:
                qid = row['query']['id']
                if qid in records:
                    raise ValueError('Duplicate actual ordinary record')
                records[qid] = row
        qids = {qid for rr, qid in quality if rr == rid}
        if len(qids) != 60 or (query_ids is not None and qids != query_ids) or set(records)-qids:
            raise ValueError('Every admitted slot keeps the same all60 authoritative offers')
        query_ids = qids
        process = dict(slots[rid], observed_state_row=states[rid],
                       process=compact_process(metric),
                       source_policy_binding={'source_root': source['source']['path'],
                           'go_source_sha256': source['source']['go_source_hash_sha256'],
                           'binary': source['binary'], 'qualification': source['qualification']},
                       independently_complete=metric['completed'], offered=metric['offered'],
                       statuses=metric['statuses'])
        if metric['offered'] != 60:
            raise ValueError('Runtime offered denominator changed')
        processes.append(process)
        first = quality.get((rid, metric.get('first_published_query_id')), {}).get('final')
        process['first_publication_cohort'] = (first['common_pool_cohort'] if first is not None
            and metric.get('first_published_native_row_accepted') is True else None)
        first_record = records.get(metric.get('first_published_query_id'))
        first_accepted = (first is not None and first['complete'] is True and first_record is not None
                          and metric.get('first_published_native_row_accepted') is True)
        process['first_publication_outcome'] = {
            'independently_accepted': first_accepted,
            'emitter_transit': first_record.get('transit') if first_record is not None else None,
            'emitter_valid_empty': first_record.get('valid_empty') if first_record is not None else None,
            'transit': first_record.get('transit') if first_accepted else None,
            'valid_empty': first_record.get('valid_empty') if first_accepted else None,
            'first_offered_equal': metric.get('first_marker_matches_first_offered_query'),
            'independent_status': first['status'] if first is not None else None}
        for qid in sorted(qids):
            stages = quality[(rid, qid)]
            if set(stages) != {'raw', 'final', 'display'}:
                raise ValueError('Missing authoritative stage')
            state = stages['final']
            row = records.get(qid)
            selected = selected_output(row) if row is not None else None
            clocks = {k: row.get(k) if row is not None else None for k in CLOCK_FIELDS}
            distribution([v for v in clocks.values() if v is not None])
            qpayload = {s: {k: stages[s].get(k) for k in ('complete', 'status', 'common_pool_cohort',
                        'score', 'leave_donor_family_out_signed', 'leave_donor_lineage_out_signed',
                        'candidate_patterns')} for s in stages}
            projected.append({'run': rid, 'query_id': qid, 'ordinary_record_present': row is not None,
                'attempted': row.get('attempted') if row is not None else None,
                'emitter_completed': row.get('completed') if row is not None else None,
                'emitter_transit': row.get('transit') if row is not None else None,
                'emitter_valid_empty': row.get('valid_empty') if row is not None else None,
                'independently_complete': state['complete'], 'independent_status': state['status'],
                'independently_accepted_transit': row.get('transit') if row is not None and state['complete'] is True else None,
                'independently_accepted_valid_empty': row.get('valid_empty') if row is not None and state['complete'] is True else None,
                'common_pool_cohort': state['common_pool_cohort'], **clocks,
                'native_output_sha256': digest({k: row.get(k) for k in NATIVE_FIELDS}) if row is not None else None,
                'selected_output_sha256': digest(selected) if selected is not None else None,
                'authoritative_quality_sha256': digest(qpayload), 'display_quality': qpayload['display']})
        if metric['completed'] != sum(quality[(rid, q)]['final']['complete'] for q in qids):
            raise ValueError('V4 metric and independent row completion differ')
    for rid in sorted(set(slots)-runnable):
        processes.append(dict(slots[rid], observed_state_row=states[rid], process=None,
                              independently_complete=None, offered=60, statuses=None))
        for qid in sorted(query_ids):
            projected.append({'run': rid, 'query_id': qid, 'ordinary_record_present': False,
                'attempted': None, 'emitter_completed': None, 'independently_complete': None,
                'emitter_transit': None, 'emitter_valid_empty': None,
                'independently_accepted_transit': None, 'independently_accepted_valid_empty': None,
                'independent_status': states[rid]['state'], 'common_pool_cohort': None,
                **{k: None for k in CLOCK_FIELDS}, 'native_output_sha256': None,
                'selected_output_sha256': None, 'authoritative_quality_sha256': None, 'display_quality': None})
    out.mkdir(parents=True, exist_ok=False)
    rows_path = out/'ORDINARY_ACTUAL_ROWS.jsonl'
    with rows_path.open('x') as stream:
        for row in projected:
            stream.write(canonical(row).decode()+'\n')
    value = {'schema': 'sg-runtime8-window-projection-v1', 'window': window,
        'dataset_sha256': manifest['dataset_sha256'], 'ready_sha256': READY_SHA,
        'acceptance_manifest': identity(manifest_path), 'inputs': bindings,
        'ordinary_rows': identity(rows_path), 'processes': processes,
        'authoritative_quality_aggregate': manifest['outputs']['QUALITY_AGGREGATE.json'],
        'authoritative_scalar_comparisons': manifest['outputs']['ORACLE_COMPARISONS.json'],
        'independent_reconstruction_errors': report['independent_reconstruction_errors'],
        'native_contract_counterexamples': report['native_contract_counterexamples'],
        'scope': 'Projection only; accepted unchanged V4 remains quality and feasibility authority.'}
    write(out/'WINDOW_PROJECTION.json', value)
    return value


def ratio(a, b):
    return b/a if a is not None and b is not None and a > 0 else None


def compare_runs(left, right, rows):
    a, b = rows[left['id']], rows[right['id']]
    complete = len(a) == len(b) == 60 and set(a) == set(b) and all(
        a[q]['independently_complete'] is True and b[q]['independently_complete'] is True for q in a)
    def same(field):
        return complete and all(a[q][field] is not None and a[q][field] == b[q][field] for q in a)
    def clock(values):
        return [r['published_response_ns'] for r in values.values()
                if r['published_response_ns'] is not None]
    av, bv = clock(a), clock(b)
    ac = clock({q: r for q, r in a.items() if r['independently_complete'] is True})
    bc = clock({q: r for q, r in b.items() if r['independently_complete'] is True})
    return {'baseline': left['id'], 'candidate': right['id'], 'block': left['block'],
            'window': left['window'], 'complete_60_pair': complete,
            'native_parity': 'exact' if same('native_output_sha256') else 'mismatch' if complete else 'unknown',
            'selected_output_exact': same('selected_output_sha256'),
            'quality_exact': same('authoritative_quality_sha256'),
            'baseline_actual_clock_rows': len(av), 'candidate_actual_clock_rows': len(bv),
            'baseline_independently_complete_clock_rows': len(ac), 'candidate_independently_complete_clock_rows': len(bc),
            'p95_ratio': ratio(distribution(av)['p95'], distribution(bv)['p95']),
            'independently_complete_p95_ratio': ratio(distribution(ac)['p95'], distribution(bc)['p95'])}


def quality_counts(ordinary):
    """Existing V4 counts, weighted means and maxima only; no quality rescoring."""
    result = {}
    for panel in ('score', 'leave_donor_family_out_signed', 'leave_donor_lineage_out_signed'):
        known = [(r['display_quality'] or {}).get(panel) for r in ordinary]
        present = [q for q in known if q is not None]
        counts = {k: sum(q.get(k, 0) for q in present) for k in
                  ('eligible', 'covered', 'within30', 'within60', 'within120',
                   'within1percent', 'within5percent', 'counterexample_slots')}
        counts.update(observed_quality_rows=len(present), unknown_quality_rows=len(known)-len(present),
                      missing_observed_slots=sum(q.get('eligible', 0) for q in present if q.get('missing')))
        for field in ('regret_score_seconds', 'normalized_regret'):
            values = [q[field] for q in present if q.get(field, {}).get('count', 0)]
            n = sum(q['count'] for q in values)
            counts[field] = {'count': n,
                'mean': math.fsum(q['count']*q['mean'] for q in values)/n if n else None,
                'max': max((q['max'] for q in values), default=None)}
        result[panel] = counts
    return result


def contrast(kind, baseline, candidate, left, right, rows):
    cells = [compare_runs(a, b, rows) for a, b in zip(left, right)]
    blocks = {}
    for block in (0, 1):
        def pool(runs):
            return [r['published_response_ns'] for p in runs if p['block'] == block
                    for r in rows[p['id']].values() if r['published_response_ns'] is not None]
        blocks[str(block)] = ratio(distribution(pool(left))['p95'], distribution(pool(right))['p95'])
    def resource(runs, field, operation):
        values = [(p['process'] or {}).get(field) if field != 'preparation_ns' else
                  ((p['process'] or {}).get('preparation') or {}).get('elapsed_ns') for p in runs]
        return operation(values) if all(v is not None for v in values) else None
    rss = ratio(resource(left, 'sampled_peak_rss_bytes', max), resource(right, 'sampled_peak_rss_bytes', max))
    prep = ratio(resource(left, 'preparation_ns', statistics.median), resource(right, 'preparation_ns', statistics.median))
    comparable = (len(cells) == 8 and all(c['complete_60_pair'] and c['native_parity'] == 'exact'
        and c['selected_output_exact'] and c['quality_exact'] and c['baseline_actual_clock_rows'] == 60
        and c['candidate_actual_clock_rows'] == 60 for c in cells)
        and all((p['process'] or {}).get('supervisor_ok') is True for p in left+right))
    eligible = kind != 'quality_latency_tradeoff_not_source_speedup' and comparable
    gate = (eligible and all(v is not None and v <= .97 for v in blocks.values())
            and all(c['p95_ratio'] is not None and c['p95_ratio'] <= 1.03 for c in cells)
            and rss is not None and rss <= 1.05 and prep is not None and prep <= 1.05)
    return {'kind': kind, 'baseline': baseline, 'candidate': candidate, 'cells': cells,
            'pooled_actual_published_p95_ratio_by_block': blocks,
            'max_sampled_rss_ratio': rss, 'median_preparation_ratio': prep,
            'all_expected_cells_complete_exact_and_noninferior': comparable,
            'same_cost_gate_eligible': eligible, 'passes_frozen_same_cost_gate': bool(gate)}


def combine(refs, out):
    bindings = {}
    views = [read(bound(r, bindings)) for r in refs]
    if len(views) != 4 or {v['window'] for v in views} != set(WINDOWS) or any(
            v['schema'] != 'sg-runtime8-window-projection-v1' or v['ready_sha256'] != READY_SHA for v in views):
        raise ValueError('Exactly four accepted full-closure window projections required')
    processes = {}
    rows = collections.defaultdict(dict)
    for view in views:
        for p in view['processes']:
            if p['id'] in processes:
                raise ValueError('Duplicate global process slot')
            processes[p['id']] = p
        for row in lines(bound(view['ordinary_rows'], bindings)):
            if row['query_id'] in rows[row['run']]:
                raise ValueError('Duplicate projected ordinary row')
            rows[row['run']][row['query_id']] = row
    if set(processes) != set(expected_slots()) or set(rows) != set(processes) or any(len(v) != 60 for v in rows.values()):
        raise ValueError('Exact global672/all40320 ordinary-slot ledger required')
    for rid, expected in expected_slots().items():
        if any(processes[rid][key] != value for key, value in expected.items()):
            raise ValueError('Projected process metadata differs from its exact frozen slot')
    positions = [p['global_position'] for p in processes.values()]
    if sorted(positions) != list(range(672)):
        raise ValueError('Missing/duplicate global original position')
    # Runtime dict order is not an identity: JSON sorting must not change a cell.
    by_cell = {(p['product'], (p['runtime']['GOGC'], p['runtime']['GOMEMLIMIT']), p['block'], p['window']): p for p in processes.values()}
    def runs(product, cell):
        return [by_cell[(product, cell, b, w)] for b, w in itertools.product((0, 1), WINDOWS)]
    contrasts = []
    for product in PRODUCTS:
        for a, b in itertools.permutations(CELLS, 2):
            contrasts.append(contrast('same_source_same_product_runtime', [product, list(a)], [product, list(b)], runs(product, a), runs(product, b), rows))
    for kind, pairs in (('same_native_contract_source', SOURCE_PAIRS),
                        ('quality_latency_tradeoff_not_source_speedup', TRADEOFF_PAIRS)):
        for a, b in pairs:
            for cell in CELLS:
                contrasts.append(contrast(kind, [a, list(cell)], [b, list(cell)], runs(a, cell), runs(b, cell), rows))
    cohorts = []
    for product, cell in itertools.product(PRODUCTS, CELLS):
        group = runs(product, cell)
        ordinary = [r for p in group for r in rows[p['id']].values()]
        accepted_first = [(p['process'] or {}).get('accepted_native_launch_to_first_available_answer_ns')
                          for p in group if (p['process'] or {}).get('first_published_native_row_accepted') is True]
        cohorts.append({'product': product, 'runtime': dict(zip(('GOGC', 'GOMEMLIMIT'), cell)),
            'expected_process_slots': 8, 'expected_ordinary_slots': 480,
            'observed_states': dict(collections.Counter(p['observed_state_row']['state'] for p in group)),
            'independently_complete_rows': sum(r['independently_complete'] is True for r in ordinary),
            'unknown_or_unavailable_rows': sum(r['independently_complete'] is not True for r in ordinary),
            'independent_statuses': dict(collections.Counter(r['independent_status'] for r in ordinary)),
            'actual_ordinary_published_response_ns': distribution([r['published_response_ns'] for r in ordinary if r['published_response_ns'] is not None]),
            'independently_complete_published_response_ns': distribution([r['published_response_ns'] for r in ordinary if r['independently_complete'] is True and r['published_response_ns'] is not None]),
            'emitter_attempted_rows': sum(r['attempted'] is True for r in ordinary),
            'display_quality_counts_means_maxima': quality_counts(ordinary),
            'accepted_first_publication_launch_ns': distribution([v for v in accepted_first if v is not None]),
            'accepted_first_publication_missing_clock_count': sum(v is None for v in accepted_first),
            'first_publication_acceptance': dict(collections.Counter(
                'accepted_'+str(p.get('first_publication_cohort')) if (p['process'] or {}).get('first_published_native_row_accepted') is True
                else 'unaccepted' if (p['process'] or {}).get('first_published_native_row_accepted') is False
                else 'unavailable_unknown' for p in group)),
            'first_publication_transit_valid_empty': dict(collections.Counter(
                'accepted_valid_empty' if p.get('first_publication_outcome', {}).get('valid_empty') is True
                else 'accepted_transit' if p.get('first_publication_outcome', {}).get('transit') is True
                else 'accepted_walk_only' if p.get('first_publication_outcome', {}).get('independently_accepted') is True
                else 'unaccepted_or_unknown' for p in group)),
            'first_publication_matches_first_offered': dict(collections.Counter(
                str((p['process'] or {}).get('first_marker_matches_first_offered_query')) for p in group))})
    value = {'schema': 'sg-runtime8-global-frontier-v1', 'ready_sha256': READY_SHA,
        'inputs': bindings, 'expected_process_slots': 672, 'expected_ordinary_slots': 40320,
        'ledger': sorted(processes.values(), key=lambda p: p['global_position']),
        'runtime_cells': cohorts, 'comparisons': contrasts,
        'authoritative_quality_aggregates': [v['authoritative_quality_aggregate'] for v in views],
        'selection': 'NONE: descriptive frontier only; no winner from partial/incomplete comparisons',
        'limits': ['Full-closure FINALV4 is sole quality/feasibility authority.',
                   'Native and selected hashes preserve order; incomplete native parity is unknown.',
                   'Actual ordinary published-response samples are pooled, never quantiles of quantiles.',
                   'Local-walking-tie branches change preference-retention objectives, not a free source speedup.',
                   'Source-B12 selector96 is a separate already measured frontier; not rerun here.',
                   'No new evaluator, selector, hypothesis, execution, cap/runtime choice or validation promotion.']}
    out.mkdir(parents=True, exist_ok=False)
    write(out/'RUNTIME8_FRONTIER.json', value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet-window-open', action='store_true')
    parser.add_argument('--mode', choices=('window', 'combine'), required=True)
    parser.add_argument('--binding', action='append', type=Path, required=True)
    parser.add_argument('--binding-sha256', action='append', required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    if not args.quiet_window_open:
        raise SystemExit('Explicit later owner-allocated analysis slot required')
    if len(args.binding) != len(args.binding_sha256) or len(args.binding) != (1 if args.mode == 'window' else 4):
        raise SystemExit('One accepted manifest/window, or exactly four projection bindings/combine')
    refs = [{'path': str(p), 'sha256': s} for p, s in zip(args.binding, args.binding_sha256)]
    with LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.mode == 'window':
            project_window(refs[0], args.out_dir)
        else:
            combine(refs, args.out_dir)


if __name__ == '__main__':
    main()
