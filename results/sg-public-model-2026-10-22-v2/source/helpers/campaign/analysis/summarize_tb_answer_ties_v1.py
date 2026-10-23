#!/usr/bin/env python3
"""Hash-bound TB tune projection, not a new feasibility/reference oracle."""
import argparse
import collections
import fcntl
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT.parent / 'setup/campaign.lock'
BASE = 'tb-capped-storage-r2-control'
CANDIDATE = 'tb-capped-answer-walk-ties'


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def read(p, inputs):
    p = Path(p).resolve(strict=True)
    inputs[str(p)] = digest(p)
    return json.loads(p.read_text())


def dist(values):
    v = sorted(values)
    return {'count': len(v), 'p50': v[math.ceil(.5 * len(v)) - 1] if v else None,
            'p95': v[math.ceil(.95 * len(v)) - 1] if v else None,
            'p99': v[math.ceil(.99 * len(v)) - 1] if v else None,
            'max': v[-1] if v else None,
            'method': 'empirical nearest rank from actual ordinary rows, not averaged quantiles or production tails'}


def selected(row):
    q = row['recommendation_quality']['choices']
    assert q['complete'] is True
    choices = [s for g in q['groups'] for s in g['selections'] if s['limit'] == 3]
    assert len(choices) == 1 and choices[0]['complete'] is True
    by = {v['identity']: v for v in row['final']}
    ids = choices[0]['selected']
    assert len(ids) <= 3 and len(ids) == len(set(ids)) and all(i in by for i in ids)
    return [by[i] for i in ids]


def score(v, q, w):
    m = v['metrics']
    return (m['arrival'] - q['departure'] +
            w['transfer_seconds'] * m['transfers'] +
            w['extra_walk_weight'] * m['walking_seconds'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--campaign', type=Path, required=True)
    ap.add_argument('--evaluation', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    with LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        inputs = {}
        report = read(a.evaluation / 'REPORT.json', inputs)
        assert report['independent_reconstruction_errors'] == report['native_contract_counterexamples'] == 0
        assert report['oracle_offered_slots'] == 432 and report['oracle_complete_slots'] == 414
        plan = read(a.campaign / 'plan.json', inputs)
        assert len(plan['runs']) == 16
        aggregate = read(a.evaluation / 'QUALITY_AGGREGATE.json', inputs)
        weights = read(ROOT / 'selector-quality/configs/heldout393.json', inputs)
        stress = read(ROOT / 'selector-quality/configs/outside_rectangle_stress257.json', inputs)
        assert len(weights) == 393 and len(stress) == 257
        runs = {}
        by_variant = collections.defaultdict(list)
        complete_ids = set()
        with (a.evaluation / 'QUALITY_ROWS.jsonl').open() as f:
            for line in f:
                r = json.loads(line)
                if r['variant_id'] in (BASE, CANDIDATE) and r['stage'] == 'final':
                    assert r['complete'] is True
                    complete_ids.add((r['run'], r['query_id']))
        for spec in plan['runs']:
            assert spec['variant_id'] in (BASE, CANDIDATE)
            directory = a.campaign / spec['id']
            summary_path = directory / 'artifact/summary.json'
            summary = read(summary_path, inputs)
            supervisor = read(directory / 'result.json', inputs)
            for p in (summary_path, directory / 'result.json', directory / 'command.json'):
                assert report['inputs'][str(p.resolve())] == digest(p)
            assert supervisor['ok'] and summary['preparation']['complete']
            ordinary = [p for p in summary['passes'] if not p.get('warmup') and not p.get('forced')]
            assert len(ordinary) == 1
            pass_path = directory / 'artifact' / ordinary[0]['file']
            payload = read(pass_path, inputs)
            assert digest(pass_path) == ordinary[0]['sha256'] == report['inputs'][str(pass_path.resolve())]
            rows = {r['query']['id']: r for r in payload['records']}
            assert len(rows) == 60
            for qid, row in rows.items():
                assert (spec['id'], qid) in complete_ids and row['attempted'] and row['completed']
            run = {'id': spec['id'], 'block': spec['block'], 'window': spec['window'],
                   'rows': rows, 'variant_id': spec['variant_id'],
                   'response_ns': [r['response_ns'] for r in rows.values()],
                   'quality_ns': [r['quality_ns'] for r in rows.values()],
                   'preparation_ns': summary['preparation']['elapsed_ns'],
                   'rss_bytes': supervisor['sampled_peak_process_group_rss_bytes'],
                   'launch_ns': supervisor['launch_to_first_available_answer_ns']}
            key = (spec['block'], spec['window'], spec['variant_id'])
            assert key not in runs
            runs[key] = run
            by_variant[spec['variant_id']].append(run)
        assert len(complete_ids) == 960
        comparisons = []
        totals = collections.Counter()
        for block, window, variant in sorted(runs):
            if variant != CANDIDATE:
                continue
            left, right = runs[(block, window, BASE)], runs[(block, window, CANDIDATE)]
            assert set(left['rows']) == set(right['rows'])
            count = collections.Counter()
            for qid in left['rows']:
                arow, brow = left['rows'][qid], right['rows'][qid]
                assert arow['query'] == brow['query']
                def vectors(row):
                    out = {}
                    for v in row['final']:
                        m = v['metrics']; k = (m['arrival'], m['boardings'])
                        out[k] = min(out.get(k, m['walking_seconds']), m['walking_seconds'])
                    return out
                av, bv = vectors(arow), vectors(brow)
                if set(av) != set(bv):
                    raise ValueError('native arrival/boarding vector set changed: ' + qid)
                count['offered_queries'] += 1
                count['native_vectors'] += len(av)
                for v in av:
                    count['walking_improved_vectors'] += bv[v] < av[v]
                    count['walking_regressed_vectors'] += bv[v] > av[v]
                    count['walking_saved_seconds'] += av[v] - bv[v]
                count['walking_improved_queries'] += any(bv[v] < av[v] for v in av)
                for label, panel in [('in_rectangle393', weights), ('wider_stress257', stress)]:
                    aa, bb = selected(arow), selected(brow)
                    if not aa or not bb:
                        assert not aa and not bb
                        count[label + '_empty_or_unknown_queries'] += 1
                        continue
                    for w in panel:
                        x = min(score(v, arow['query'], w) for v in aa)
                        y = min(score(v, brow['query'], w) for v in bb)
                        tol = 1e-7 * max(1, abs(x))
                        count[label + '_scored_slots'] += 1
                        count[label + '_improved_slots'] += y < x - tol
                        count[label + '_regressed_slots'] += y > x + tol
            totals.update(count)
            comparisons.append({'block': block, 'window': window, **count,
                                'p95_response_ratio': dist(right['response_ns'])['p95'] / dist(left['response_ns'])['p95']})
        assert totals['offered_queries'] == 480 and totals['walking_regressed_vectors'] == 0
        variants = {}
        for variant, vv in by_variant.items():
            stages = {}
            for stage in ('raw', 'final', 'display'):
                cells = [r for r in aggregate if r['variant_id'] == variant and r['stage'] == stage and r['panel'] == 'full']
                eligible = sum(r['eligible'] for r in cells)
                stages[stage] = {'eligible_repeated_preference_slots': eligible,
                                 'covered': sum(r['covered'] for r in cells),
                                 'exact_coverage': sum(r['covered'] for r in cells) / eligible if eligible else None,
                                 'worst_regret_score_seconds': max(r['regret_score_seconds']['max'] for r in cells if r['regret_score_seconds']['max'] is not None)}
            variants[variant] = {'offered': sum(len(r['rows']) for r in vv), 'quality': stages,
                                 'pooled_response_ns_by_block': {str(b): dist([x for r in vv if r['block'] == b for x in r['response_ns']]) for b in (0, 1)},
                                 'median_preparation_ns': statistics.median(r['preparation_ns'] for r in vv),
                                 'max_sampled_rss_bytes': max(r['rss_bytes'] for r in vv),
                                 'median_raw_native_launch_ns': statistics.median(r['launch_ns'] for r in vv)}
        output = {'schema': 'tb-answer-ties-tune-projection-v1', 'inputs': inputs,
                  'analysis_source_sha256': digest(__file__), 'variants': variants,
                  'same_native_vector_walking_and_display_comparisons': comparisons,
                  'comparison_totals': dict(totals),
                  'limits': ['Feasibility/native qualification is inherited only through exact accepted independent evaluator/pass hashes, not re-established by this projection.',
                             '240 unique requests repeated in two timing blocks; preference slots are not distinct passenger demand.',
                             'Raw/native cap vectors and local same-vector walking do not establish complete3D walking discovery.',
                             'All common/LOFO quality remains incomplete-pool diagnostic; original18 scalar unknown slots retained.',
                             'No same-contract source-only speedup claim: this is a separately named quality refinement.',
                             'Exact stream/pass/receipt equivalence still requires the independent actual16-process receipt audit.']}
        with a.out.open('x') as f:
            json.dump(output, f, sort_keys=True, indent=2); f.write('\n')
        print(json.dumps({'out': str(a.out), 'comparison_totals': dict(totals), 'variants': variants}))


if __name__ == '__main__':
    main()
