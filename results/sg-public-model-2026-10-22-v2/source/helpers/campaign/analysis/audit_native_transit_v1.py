#!/usr/bin/env python3
"""Create-only independent native transit witness audit; never timetable search.

Run ONLY after the campaign owner grants a quiet CPU slot. The coordinator holds
campaign.lock across bounded subprocesses, each loading exactly one model/window.
No production profile At/Reanchor, no CSA, no new oracle, no certified-loader edit.
"""
from __future__ import annotations
import argparse
import collections
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
ORACLE = ROOT / 'selector-quality/results/oracle-tune-full1h-48x9'
ORIGINAL_SOURCE = 'a4047f42518a33812e210061ef4ac88ac265c1dc2a2b0e667229d418738fedc7'
ORIGINAL_BINARY = '3c1f76803ed06ce2c7bf0f51cf4c0994d92fff298195ce69be330f614e07cc13'
INFINITY = 4611686018427387904
FAMILIES = {'tad', 'range_raptor', 'trip_based'}
CHILD_AS_BYTES = 4 * 1024 ** 3
CHILD_CPU_SECONDS = 300
CHILD_WALL_SECONDS = 600
ERRORS = (ValueError, KeyError, TypeError, OSError, StopIteration, IndexError)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


legacy = module('native_audit_evalkit', ROOT.parent / 'evalkit/evalkit.py')
inv = module('native_audit_inventory', ROOT / 'analysis/summarize_native_auxiliary_v1.py')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def bytes_sha(value):
    return hashlib.sha256(value).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def read(path, bindings):
    value, sha = legacy.read_json(path)
    bindings[str(Path(path).resolve())] = sha
    return value


def put(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


class Sink:
    def __init__(self, path):
        self.stream = Path(path).open('x')
        self.count = 0

    def append(self, value):
        self.stream.write(canonical(value) + '\n')
        self.count += 1

    def close(self):
        self.stream.close()


def object_slices(text, start=0):
    """Return exact value substring bounds for one small workload JSON object."""
    decoder = json.JSONDecoder()
    def ws(i):
        while i < len(text) and text[i].isspace():
            i += 1
        return i
    pos = ws(start)
    require(text[pos] == '{', 'workload object required')
    pos = ws(pos + 1)
    out = {}
    while text[pos] != '}':
        key, pos = decoder.raw_decode(text, pos)
        pos = ws(pos)
        require(text[pos] == ':', 'invalid object delimiter')
        begin = ws(pos + 1)
        _, end = decoder.raw_decode(text, begin)
        require(key not in out, 'duplicate workload key')
        out[key] = (begin, end)
        pos = ws(end)
        if text[pos] == ',':
            pos = ws(pos + 1)
        else:
            require(text[pos] == '}', 'invalid object delimiter')
    return out


def query_fragments(path, workload):
    text = Path(path).read_bytes().decode('utf-8')
    begin, end = object_slices(text)['items']
    pos = begin + 1
    result = {}
    decoder = json.JSONDecoder()
    for item in workload['items']:
        while text[pos].isspace() or text[pos] == ',':
            pos += 1
        bounds = object_slices(text, pos)
        a, b = bounds['query']
        fragment = text[a:b]
        require(json.loads(fragment) == item['query'], 'exact query slice differs')
        qid = item['query']['id']
        require(qid not in result, 'duplicate workload query')
        result[qid] = fragment
        _, pos = decoder.raw_decode(text, pos)
    return result


def point_query(base, ready):
    q = copy.deepcopy(base)
    q['departure'] = ready  # Latest-arrival is intentionally NOT shifted.
    return q


def initial_walk_duration(checker, journey):
    duration = 0
    for leg in journey['legs']:
        if leg['kind'] != 'walk':
            break
        duration += checker.walks[leg['ref']]['duration']
    return duration


def independent_reanchor(checker, journey, ready):
    """Use independently indexed footpath durations; touch only the prefix."""
    result = copy.deepcopy(journey)
    now = ready
    for leg in result['legs']:
        if leg['kind'] != 'walk':
            break
        duration = checker.walks[leg['ref']]['duration']
        leg['departure'], leg['arrival'] = now, now + duration
        now += duration
    return result


def validate_source_walk_anchor(checker, journey, ready):
    """Do not repair malformed source timestamps while calling it reanchor."""
    require(type(ready) is int and ready >= 0, 'source readiness requires nonnegative strict integer')
    now = ready
    for leg in journey['legs']:
        if leg['kind'] != 'walk':
            break
        duration = checker.walks[leg['ref']]['duration']
        require(type(leg.get('departure')) is int and type(leg.get('arrival')) is int and
                leg['departure'] == now and leg['arrival'] == now + duration,
                'source initial walking prefix is not anchored at emitted readiness/model durations')
        now += duration


def independently_eligible_end(checker, profile, journey):
    """Saved transit itinerary feasibility domain, NOT profile-search truth."""
    first = next((leg for leg in journey['legs'] if leg['kind'] == 'ride'), None)
    require(first is not None, 'transit point has no ride')
    return min(profile['ready_window_end_inclusive'],
               checker.rides[first['ref']]['departure'] - initial_walk_duration(checker, journey))


def validate_point(checker, profile, point, final=False):
    base = profile['base']
    ready = point['latest_ready']
    require(type(ready) is int and base['departure'] <= ready <= profile['ready_window_end_inclusive'],
            'point latest_ready outside profile')
    claim = point['validated'] if final else point['journey']
    checked = checker.check(point_query(base, ready), claim)
    require(checked['metrics']['boardings'] > 0, 'transit point has zero boardings')
    if not final:
        require(type(point.get('arrival')) is int and type(point.get('boardings')) is int,
                'point arrival/boardings require strict integers')
        require(point['arrival'] == checked['metrics']['arrival'] and
                point['boardings'] == checked['metrics']['boardings'], 'point arrival/boardings metadata differs')
    cutoff = independently_eligible_end(checker, profile, checked['journey'])
    # LatestReady is a propagated departure-iteration boundary, not a promise of
    # maximal physical eligibility for this one itinerary. A smaller bound is
    # valid metadata; a larger bound is not. Extensions are audited separately.
    require(ready <= cutoff, 'point latest_ready exceeds independent feasible boundary')
    return checked, cutoff


def materializations(checker, profile, points, direct, final=False, physical_extension=False):
    """Check EVERY compatible saved witness, not just the production winners."""
    base, end = profile['base'], profile['ready_window_end_inclusive']
    checked_points = [(validate_point(checker, profile, p, final), p['latest_ready']) for p in points]
    checked_direct, direct_duration = None, None
    if direct is not None:
        obj = direct if final else direct['journey_at_window_start']
        checked_direct = checker.check(base, obj)
        m = checked_direct['metrics']
        require(m['boardings'] == 0 and all(x['kind'] == 'walk' for x in checked_direct['journey']['legs']),
                'direct branch is not zero-boarding all-walk')
        direct_duration = m['arrival'] - base['departure']
        if not final:
            require(type(direct.get('duration')) is int and direct['duration'] == direct_duration,
                    'direct affine duration differs')
    grid, by_ready, occurrence_count = [], {}, 0
    for ready in range(base['departure'], end + 1):
        q, candidates = point_query(base, ready), []
        for (checked, physical_cutoff), claimed_cutoff in checked_points:
            cutoff = physical_cutoff if physical_extension else claimed_cutoff
            if ready <= cutoff:
                j = independent_reanchor(checker, checked['journey'], ready)
                candidates.append(checker.check(q, j))
                occurrence_count += 1
        if checked_direct is not None and ready + direct_duration <= base['latest_arrival']:
            j = independent_reanchor(checker, checked_direct['journey'], ready)
            checked = checker.check(q, j)
            require(checked['metrics']['arrival'] == ready + direct_duration and checked['metrics']['boardings'] == 0,
                    'direct affine materialization differs')
            candidates.append(checked)
            occurrence_count += 1
        vector = [INFINITY] * (base['max_boardings'] + 1)
        for checked in candidates:
            m = checked['metrics']
            for cap in range(m['boardings'], len(vector)):
                vector[cap] = min(vector[cap], m['arrival'])
        grid.append({'ready': ready, 'arrival_under_boarding_caps': vector})
        by_ready[ready] = candidates
    return grid, by_ready, occurrence_count


def audit_profile(checker, row):
    profile, raw = row['query'], row['raw']
    checker.query(profile['base'])
    end, start = profile['ready_window_end_inclusive'], profile['base']['departure']
    require(type(end) is int and start <= end <= profile['base']['latest_arrival'], 'invalid profile window')
    require(raw.get('query') == profile, 'Raw.Query differs from offered profile')
    require(type(raw.get('complete')) is bool and type(row.get('complete')) is bool,
            'profile Complete booleans missing')
    if row['complete']:
        require(raw['complete'] and not raw.get('error') and not row.get('error'), 'Raw.Complete/record Complete inconsistent')
    raw_points, final_points = raw.get('transit_points', []), row.get('final_points', [])
    require(isinstance(raw_points, list) and isinstance(final_points, list), 'profile points not arrays')
    require(len(raw_points) == len(final_points), 'raw/final profile point counts differ')
    for a, b in zip(raw_points, final_points):
        require(a['latest_ready'] == b['latest_ready'] and a['journey'] == b['validated']['journey'],
                'raw/final profile points differ')
    direct, final_direct = raw.get('direct_walking'), row.get('final_direct')
    require((direct is None) == (final_direct is None), 'raw/final direct presence differs')
    if direct is not None:
        require(direct['journey_at_window_start'] == final_direct['journey'], 'raw/final direct journeys differ')
    # Claimed-bound reconstruction audits presentation parity. The independent
    # physical extension never silently changes the meaning of that parity.
    raw_grid, raw_ready, raw_occurrences = materializations(checker, profile, raw_points, direct)
    final_grid, final_ready, final_occurrences = materializations(checker, profile, final_points, final_direct, True)
    extended_grid, _, extended_occurrences = materializations(checker, profile, raw_points, direct, physical_extension=True)
    extension_counterexamples = []
    if row['complete']:
        for claimed, extended in zip(raw_grid, extended_grid):
            for cap, (got, feasible) in enumerate(zip(claimed['arrival_under_boarding_caps'], extended['arrival_under_boarding_caps'])):
                if feasible < got:
                    extension_counterexamples.append({'ready': claimed['ready'], 'boarding_cap': cap,
                                                       'emitted_claimed_bound_arrival': got, 'independent_saved_witness_arrival': feasible})
    require(raw_grid == final_grid, 'independent raw/final profile cap vectors differ')
    if row['complete']:
        require(row.get('every_integer_ready_time') == raw_grid,
                'recorded full integer readiness/cap grid differs from all saved independently feasible witnesses')
    else:
        # Any recorded partial grid still must be an exact prefix, not arbitrary points.
        grid = row.get('every_integer_ready_time', [])
        require(grid == raw_grid[:len(grid)], 'incomplete recorded grid differs')
    return {'raw': raw_ready[start], 'final': final_ready[start],
            'grid_cells_checked_per_stage': len(raw_grid) * (profile['base']['max_boardings'] + 1),
            'saved_witness_materializations_checked': raw_occurrences + final_occurrences + extended_occurrences,
            'readiness_observations': len(raw_grid), 'direct_branch': direct is not None,
            'physical_extension_counterexamples': extension_counterexamples,
            'conservative_point_boundary_count': sum(p['latest_ready'] < independently_eligible_end(checker, profile, p['journey']) for p in raw_points)}


def audit_point(checker, row, driver):
    q = row['query']
    checker.query(q)
    raw = [checker.check(q, j) for j in row.get('raw', [])]
    final = [checker.check(q, j) for j in row.get('final', [])]
    if driver == 'tadbench':
        require(len(raw) <= 1 and len(final) <= 1, 'TAD is not one earliest-arrival witness')
        require([j['journey'] for j in raw] == [j['journey'] for j in final], 'TAD raw/final witnesses differ')
    return {'raw': raw, 'final': final, 'grid_cells_checked_per_stage': 0,
            'saved_witness_materializations_checked': len(raw) + len(final), 'readiness_observations': 0}


def score(checked, weight):
    return checked['duration_seconds'] + weight['transfer_seconds'] * checked['metrics']['transfers'] + weight['extra_walk_weight'] * checked['metrics']['walking_seconds']


def comparison(candidates, slot):
    """A feasible candidate beating COMPLETE scalar truth is a contradiction."""
    if not slot['complete']:
        return {'status': 'unknown_original_scalar_slot'}
    if not slot['found']:
        return {'status': 'contradiction_candidate_in_complete_empty_scalar' if candidates else 'agree_complete_empty'}
    if not candidates:
        return {'status': 'missing_native_witness_against_complete_scalar', 'scalar_score': slot['score_seconds']}
    got = min(score(j, slot['weight']) for j in candidates)
    delta = got - slot['score_seconds']
    return {'status': 'contradiction_candidate_beats_complete_scalar' if delta < -1e-7 else 'agree_exact_scalar' if abs(delta) <= 1e-7 else 'native_gap_to_complete_scalar',
            'native_score': got, 'scalar_score': slot['score_seconds'], 'signed_gap_seconds': delta}


def source_fingerprint(root):
    """Independent implementation of experiment.SourceHash, no Go execution."""
    root = Path(root)
    files = []
    for parent, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in {'.git', '.cache', 'artifacts'}]
        for name in names:
            path = Path(parent) / name
            if name.endswith('.go') or name in {'go.mod', 'routing.lock.json'} or path == root / 'vendor/modules.txt':
                files.append(path)
    h = hashlib.sha256()
    for path in sorted(files):
        rel = str(path.relative_to(root)).encode()
        data = path.read_bytes()
        h.update(str(len(rel)).encode() + b':' + rel + b':' + str(len(data)).encode() + b':')
        h.update(data)
    require(files, 'empty original scalar source snapshot')
    return h.hexdigest()


def plan_freeze_reference(freeze, campaign, bindings):
    plan = read(campaign / 'plan.json', bindings)
    reference = plan['auxiliary_input_source_freeze']
    require(inv.resolve_reference(reference, campaign, bindings) == freeze, 'native input/source freeze changed')
    return reference


def load_scalar(window, checker, dataset_sha, bindings, scalar_sink):
    recipe = read(ORACLE / 'RECIPE.json', bindings)
    summary = read(ORACLE / 'SUMMARY.json', bindings)
    require(summary['recipe_sha256'] == bindings[str((ORACLE / 'RECIPE.json').resolve())], 'original scalar recipe digest differs')
    require(recipe['binary_sha256'] == summary['binary_sha256'] == ORIGINAL_BINARY and
            summary['build_source_sha256'] == ORIGINAL_SOURCE, 'not original scalar source/binary')
    require(digest(recipe['binary']) == ORIGINAL_BINARY, 'original scalar binary bytes differ')
    bindings[str(Path(recipe['binary']).resolve())] = ORIGINAL_BINARY
    job = next(x for x in recipe['jobs'] if x['window'] == window)
    workload = read(job['queries'], bindings)
    require(bindings[str(Path(job['queries']).resolve())] == job['queries_sha256'] and
            workload['dataset_sha256'] == dataset_sha, 'original scalar workload/dataset bytes differ')
    weights = read(job['weights'], bindings)
    require(bindings[str(Path(job['weights']).resolve())] == job['weights_sha256'], 'scalar weights bytes differ')
    qmap = {x['query']['id']: x['query'] for x in workload['items']}
    require(len(qmap) == len(workload['items']), 'duplicate scalar offered query')
    require(all(q.get('walking_limits') == {'access_seconds': 600, 'egress_seconds': 600,
                 'transfer_seconds': 600, 'direct_seconds': 600} for q in qmap.values()),
            'original scalar unequal-role-cap bug exclusion no longer applies')
    output = Path(job['output'])
    output_sha = digest(output)
    bindings[str(output.resolve())] = output_sha
    original_window = summary['per_window'][window]
    require(output_sha == original_window['jsonl_sha256'], 'original scalar output bytes differ')
    slots = {}
    with output.open() as stream:
        header = json.loads(next(stream))
        require(header == original_window['metadata'], 'original scalar header differs')
        require(header['kind'] == 'metadata' and header['dataset_sha256'] == dataset_sha and
                header['workload_sha256'] == job['queries_sha256'] and header['weights_sha256'] == job['weights_sha256'] and
                header['build_source_sha256'] == ORIGINAL_SOURCE and header['max_labels'] == recipe['limits']['max_labels'] and
                header['max_transitions'] == recipe['limits']['max_transitions'] and header['timeout'] == '1m0s',
                'original scalar metadata/cap/source binding differs')
        for line_number, line in enumerate(stream, 2):
            z = json.loads(line)
            require(z.get('kind') == 'scalar_result', 'unexpected scalar output kind')
            q, wi, result = z['query'], z['weight_index'], z['result']
            require(q['id'] in qmap and q == qmap[q['id']], 'original scalar query bytes/fields differ')
            require(type(wi) is int and 0 <= wi < len(weights) and z['weight'] == weights[wi], 'original scalar weight/index differs')
            key = (q['id'], wi)
            require(key not in slots, 'duplicate original scalar offer')
            slot = {'query': q, 'query_canonical_sha256': bytes_sha(canonical(q).encode()), 'weight_index': wi, 'weight': weights[wi],
                    'complete': result.get('complete') is True and not z.get('error'), 'found': result.get('found') is True,
                    'emitted_complete': result.get('complete'), 'error': z.get('error'), 'source': str(output),
                    'source_sha256': output_sha, 'line_number': line_number, 'original_header': header,
                    'original_binary_sha256': ORIGINAL_BINARY, 'original_source_sha256': ORIGINAL_SOURCE,
                    'dataset_sha256': dataset_sha, 'workload_sha256': job['queries_sha256'],
                    'original_result_status': {k: result.get(k) for k in ('complete', 'found', 'score_seconds', 'labels', 'transitions', 'settled', 'contract')}}
            if slot['complete'] and slot['found']:
                checked = checker.check(q, result['journey'])
                if z.get('validated') is not None:
                    checker.check(q, z['validated'])
                require(abs(score(checked, weights[wi]) - result['score_seconds']) <= 1e-7, 'original scalar score differs from reconstructed witness')
                slot['score_seconds'] = result['score_seconds']
            slots[key] = slot
    for qid, q in qmap.items():
        for wi, weight in enumerate(weights):
            key = qid, wi
            if key not in slots:
                slots[key] = {'query': q, 'weight_index': wi, 'weight': weight, 'complete': False, 'found': False,
                              'error': 'unresolved_missing_original_scalar_output', 'source': str(output),
                              'source_sha256': output_sha, 'dataset_sha256': dataset_sha,
                              'workload_sha256': job['queries_sha256'], 'original_header': header,
                              'original_binary_sha256': ORIGINAL_BINARY, 'original_source_sha256': ORIGINAL_SOURCE,
                              'query_canonical_sha256': bytes_sha(canonical(q).encode())}
    for slot in slots.values():
        scalar_sink.append(slot)
    require(len(slots) == original_window['offered_slots'], 'original scalar offered denominator differs')
    require(sum(x['complete'] for x in slots.values()) == original_window['complete'], 'original scalar completeness denominator differs')
    return slots


def base_donations(checker, row, driver):
    """Reference-only gate, independent of native completeness or row acceptance.

    Preserve every independently feasible occurrence, including duplicates and
    partial native output. Never donate a later-ready claim/metric unchanged.
    """
    q = row['query'].get('base', row['query'])
    checker.query(q)
    result, failures = {'raw': [], 'final': []}, []
    for stage in ('raw', 'final'):
        candidates = []
        if driver == 'profilebench':
            require(row['raw'].get('query') == row['query'], 'donation Raw.Query differs from offered profile')
            points = row['raw'].get('transit_points', []) if stage == 'raw' else row.get('final_points', [])
            if not isinstance(points, list):
                failures.append({'stage': stage, 'scope': 'stage_container', 'error': 'profile points are not an array'})
            else:
                candidates.extend((p, {'source_point_index': index, 'source_branch': 'transit_point'}) for index, p in enumerate(points))
            direct = row['raw'].get('direct_walking') if stage == 'raw' else row.get('final_direct')
            if direct is not None:
                candidates.append((direct, {'source_point_index': None, 'source_ready': q['departure'], 'source_branch': 'direct_walking'}))
        else:
            points = row.get(stage, [])
            if not isinstance(points, list):
                failures.append({'stage': stage, 'scope': 'stage_container', 'error': 'point stage is not an array'})
            else:
                candidates = [(obj, {'source_point_index': index, 'source_ready': q['departure'], 'source_branch': 'point_journey'})
                              for index, obj in enumerate(points)]
        for source, provenance in candidates:
            try:
                require(isinstance(source, dict), 'saved source occurrence is not an object')
                if provenance['source_branch'] == 'transit_point':
                    require(type(source.get('latest_ready')) is int, 'source latest_ready requires strict integer')
                    provenance['source_ready'] = provenance['source_latest_ready'] = source['latest_ready']
                    obj = source['journey'] if stage == 'raw' else source['validated']
                elif provenance['source_branch'] == 'direct_walking':
                    obj = source['journey_at_window_start'] if stage == 'raw' else source
                else:
                    obj = source
                require(isinstance(obj, dict), 'saved journey/validated occurrence is not an object')
                journey = obj.get('journey', obj)
                saved_hash = bytes_sha(canonical(journey).encode())
                validate_source_walk_anchor(checker, journey, provenance['source_ready'])
                transformed = independent_reanchor(checker, journey, q['departure']) if driver == 'profilebench' else copy.deepcopy(journey)
                # Passing the raw journey avoids importing source-ready metrics.
                checked = checker.check(q, transformed)
                source_error = None
                try:
                    checker.check(point_query(q, provenance['source_ready']), obj)
                except ERRORS as exc:
                    source_error = type(exc).__name__ + ': ' + str(exc)
                provenance.update(source_saved_journey_canonical_sha256=saved_hash,
                                  source_feasible_at_emitted_ready=source_error is None,
                                  source_ready_validation_error=source_error,
                                  transformation='reanchor only initial contiguous walking prefix from model footpath durations; ride/intermediate/egress events fixed' if driver == 'profilebench' else 'identity; independently rechecked under full base query',
                                  transformed_journey_canonical_sha256=bytes_sha(canonical(transformed).encode()),
                                  source_initial_walking_seconds=initial_walk_duration(checker, journey),
                                  source_ready_query=point_query(q, provenance['source_ready']),
                                  transform_kind='reanchor_initial_contiguous_walks' if driver == 'profilebench' else 'identity',
                                  transformed_initial_leg_count=next((i for i, leg in enumerate(journey['legs']) if leg['kind'] != 'walk'), len(journey['legs'])) if driver == 'profilebench' else 0)
                result[stage].append((checked, provenance))
            except ERRORS as exc:
                failures.append({'stage': stage, **provenance, 'error': type(exc).__name__ + ': ' + str(exc)})
    return result, failures


def export_occurrence(sink, checked, q, fragment, context, stage, index, transformation):
    sink.append({'schema': 'sg-feasible-reference-witness-v1', 'kind': 'independently_feasible_saved_native_witness',
                 'reference_only': True, 'scalar_optimality_claim': False, 'search_completeness_claim': False,
                 'dataset_sha256': context['dataset_sha256'], 'query': q,
                 'query_canonical_json_utf8': canonical(q), 'query_canonical_sha256': bytes_sha(canonical(q).encode()),
                 'query_exact_workload_json_utf8': fragment, 'query_exact_workload_bytes_sha256': bytes_sha(fragment.encode()),
                 'native_family': context['family'], 'donor_family': context['donor_family'],
                 'provenance': {**context, **transformation, 'native_stage': stage, 'saved_witness_occurrence_index': index,
                                'materialized_ready': q['departure'], 'readiness_contract': 'original base query readiness; fixed latest arrival'},
                 'validated': checked})


def bound_ordinary_pass(manifest, artifact, algorithm, bindings):
    """Bind pass bytes/identity without rejecting unrelated row presentation.

    The inventory's stricter whole-pass validator remains unchanged. This audit
    needs independently feasible partial witnesses even when another row/grid
    is malformed. Row identity and integrity are gated below, one offer at a
    time. Warmup and forced passes never become ordinary candidate sources.
    """
    selected, discarded = [], []
    for desc in manifest.get('passes', manifest.get('summaries', [])):
        name = desc.get('file')
        require(isinstance(name, str) and Path(name).name == name and name not in {'.', '..'}, 'unsafe native pass filename')
        path = artifact / name
        payload = read(path, bindings)
        require(bindings[str(path.resolve())] == desc.get('sha256'), 'native pass digest differs')
        require(payload.get('algorithm') == desc.get('algorithm', algorithm) == algorithm and 'csa' not in algorithm.lower(),
                'unrequested native pass algorithm')
        require(type(payload.get('warmup')) is bool and payload['warmup'] == desc.get('warmup') and
                payload.get('repetition') == desc.get('repetition'), 'native pass repetition/warmup differs')
        require(isinstance(payload.get('records'), list), 'native pass records not an array')
        if payload['warmup'] or desc.get('forced'):
            discarded.append({'file': name, 'reason': 'forced_or_warmup_diagnostic_not_ordinary'})
            continue
        require(type(payload.get('repetition')) is int and payload['repetition'] == 0, 'unexpected ordinary native repetition')
        selected.append((desc, payload))
    require(len(selected) <= 1, 'multiple ordinary native passes')
    return (selected[0] if selected else None), discarded


def bind_offered_rows(payload, expected):
    """Fail closed per locator; retain valid unrelated rows and every offer."""
    rows, indices, failures, seen = {}, {}, [], set()
    for index, row in enumerate(payload['records']):
        try:
            require(isinstance(row, dict) and isinstance(row.get('query'), dict), 'native row/query is not an object')
            full = row['query']
            qid = full.get('base', full)['id']
            require(qid in expected, 'native row does not identify an offered query')
            # A recognisable offered ID establishes locator ambiguity even if
            # that duplicate later fails the full query/cap/stratum check.
            if qid in seen:
                rows.pop(qid, None); indices.pop(qid, None)
                raise ValueError('duplicate native query locator')
            seen.add(qid)
            require(full == expected[qid]['query'] and row.get('stratum') == expected[qid]['stratum'],
                    'native full query/stratum differs from offered bytes')
            rows[qid], indices[qid] = row, index
        except ERRORS as exc:
            failures.append({'native_record_index': index, 'error': type(exc).__name__ + ': ' + str(exc)})
    return rows, indices, failures


def audit_window(window, campaigns, out):
    out.mkdir()  # create-only, including interrupted attempts
    bindings, run_reports, errors = {}, [], []
    offers = Sink(out / 'OFFERED_NATIVE_ROWS.jsonl')
    witnesses = Sink(out / 'FEASIBLE_REFERENCE_WITNESSES.jsonl')
    scalar_sink = Sink(out / 'ORIGINAL_SCALAR_SLOTS.jsonl')
    comparisons = Sink(out / 'SCALAR_COMPARISONS.jsonl')
    counterexamples = Sink(out / 'SAVED_WITNESS_COUNTEREXAMPLES.jsonl')
    donation_failures = Sink(out / 'DONATION_RECONSTRUCTION_FAILURES.jsonl')
    selected = []
    for campaign in campaigns:
        plan = read(campaign / 'plan.json', bindings)
        freeze = inv.resolve_reference(plan['auxiliary_input_source_freeze'], campaign, bindings)
        require(plan.get('evaluation_mode') == 'diagnostic' and freeze.get('all_csa_execution_excluded') is True,
                'wrong native diagnostic non-CSA plan')
        for spec in plan['runs']:
            if spec.get('window') == 'weekday-' + window + '-20261020' and spec.get('family') in FAMILIES:
                selected.append((campaign, spec, freeze))
    require(selected, 'no selected native offers for window')
    datasets = {inv.flag(spec['argv'], '-dataset') for _, spec, _ in selected}
    require(len(datasets) == 1, 'bounded process requires exactly one model/window')
    dataset_path = Path(next(iter(datasets)))
    dataset = read(dataset_path, bindings)
    dataset_sha = bindings[str(dataset_path.resolve())]
    checker = legacy.Checker(dataset)
    slots = load_scalar('weekday-' + window + '-20261020', checker, dataset_sha, bindings, scalar_sink)
    original_inventory = read(ROOT / 'analysis/native-tune-v5-inventory-attempt01.json', bindings)
    scalar_by_query = collections.defaultdict(list)
    for slot in slots.values():
        scalar_by_query[slot['query']['id']].append(slot)
    for campaign, spec, freeze in selected:
        run_dir = campaign / spec['id']
        workload_path = Path(inv.flag(spec['argv'], '-queries'))
        workload = read(workload_path, bindings)
        fragments = query_fragments(workload_path, workload)
        driver = inv.driver_for(spec['argv'])
        expected = inv.expected_items(workload, driver, spec['argv'])
        context = {'campaign': str(campaign), 'run_id': spec['id'], 'family': spec['family'], 'window': window,
                   'donor_family': {'range_raptor': 'RAPTOR', 'tad': 'TAD', 'trip_based': 'TripBased'}[spec['family']],
                   'dataset_path': str(dataset_path), 'dataset_sha256': dataset_sha,
                   'dataset_schema_version': dataset['schema_version'], 'dataset_id': dataset['id'],
                   'workload_path': str(workload_path), 'workload_sha256': bindings[str(workload_path.resolve())],
                   'frozen_plan_path': str(campaign / 'plan.json'), 'frozen_plan_sha256': bindings[str((campaign / 'plan.json').resolve())]}
        rr = {**context, 'offered': len(expected), 'driver': driver, 'complete_independent_rows': 0,
              'native_complete_rows': 0, 'validation_failed_rows': 0, 'independent_empty_rows': 0,
              'readiness_observations_checked': 0, 'grid_cells_checked_per_stage': 0,
              'saved_witness_materializations_checked': 0, 'physical_extension_counterexample_cells': 0,
              'conservative_point_boundary_count': 0, 'feasible_reference_witness_occurrences': 0}
        rows, record_indices = {}, {}
        try:
            inventory_row = next(r for r in original_inventory['runs'] if r['campaign'] == str(campaign) and r['id'] == spec['id'])
            rr['inventory'] = inventory_row
            command = read(run_dir / 'command.json', bindings)
            result = read(run_dir / 'result.json', bindings) if (run_dir / 'result.json').exists() else None
            argv, driver, role, inputs = inv.validate_envelope(spec, command, result, freeze, run_dir, campaign)
            require(dataset_sha == inputs[str(dataset_path)]['sha256'] == workload['dataset_sha256'] and
                    context['workload_sha256'] == inputs[str(workload_path)]['sha256'], 'current native model/workload bytes differ from frozen process inputs')
            require(digest(argv[0]) == command['binary']['sha256'], 'current native binary differs from frozen measured binary')
            bindings[str(Path(argv[0]).resolve())] = command['binary']['sha256']
            context.update(native_source_sha256=role['go_source_hash_sha256'], native_routing_sha256=role['routing_file_list_sha256'],
                           native_algorithm=inv.algorithm(argv, driver), native_driver=driver,
                           native_binary_sha256=command['binary']['sha256'], command_path=str(run_dir / 'command.json'),
                           command_sha256=bindings[str((run_dir / 'command.json').resolve())],
                           result_path=str(run_dir / 'result.json'),
                           result_sha256=bindings.get(str((run_dir / 'result.json').resolve())),
                           source_process_status={key: (result or {}).get(key) for key in ('ok', 'returncode', 'termination', 'timed_out', 'source_contents_unchanged')},
                           source_input_freeze=plan_freeze_reference(freeze, campaign, bindings))
            artifact = run_dir / 'artifact'
            manifest_path = artifact / ('manifest.json' if driver in {'tadbench', 'profilebench'} else 'summary.json')
            if manifest_path.exists():
                manifest = read(manifest_path, bindings)
                inv.validate_manifest(manifest, command, role, driver, inv.algorithm(argv, driver), dataset_sha, context['workload_sha256'])
                chosen, discarded = bound_ordinary_pass(manifest, artifact, inv.algorithm(argv, driver), bindings)
                rr.update(excluded_diagnostic_passes=discarded, additional_control_passes=0,
                          native_manifest_sha256=bindings[str(manifest_path.resolve())])
                if chosen:
                    descriptor, payload = chosen
                    context.update(native_pass_file=descriptor['file'], native_pass_sha256=descriptor['sha256'],
                                   native_pass_path=str(artifact / descriptor['file']),
                                   native_repetition=descriptor['repetition'], native_warmup=False,
                                   native_manifest_path=str(manifest_path), native_manifest_sha256=bindings[str(manifest_path.resolve())])
                    rows, record_indices, row_binding_failures = bind_offered_rows(payload, expected)
                    rr['row_binding_failures'] = row_binding_failures
                    for failure in row_binding_failures:
                        errors.append({**context, 'scope': 'individual_row_binding', **failure})
            rr['binding_status'] = 'freeze_command_runtime_manifest_pass_bound' if rows else 'freeze_command_bound_no_ordinary_rows'
        except ERRORS as exc:
            rr['binding_status'] = 'invalid_or_unresolved'
            rr['binding_error'] = type(exc).__name__ + ': ' + str(exc)
            errors.append({**context, 'scope': 'run_binding', 'error': rr['binding_error']})
            rows = {}  # never export an unbound witness
        rr.update(context)
        statuses = collections.Counter()
        for qid, offer in expected.items():
            q = offer['query'].get('base', offer['query'])
            row = rows.get(qid)
            item = {**context, 'query': q, 'stratum': offer['stratum'], 'offered_native_query': offer['query'],
                    'native_row_present': row is not None, 'native_complete': False, 'independent_witness_integrity': False,
                    'original_native_status': inv.row_status(row, driver) if row else None,
                    'original_native_error': row.get('error') if row else None}
            result, donated = None, {'raw': [], 'final': []}
            if row is None:
                item['status'] = 'unavailable_native_row_or_binding'
            else:
                complete_key = 'completed' if driver == 'familybench' else 'complete'
                item['native_complete'] = row.get(complete_key) is True and not row.get('error')
                rr['native_complete_rows'] += item['native_complete']
                try:
                    result = audit_profile(checker, row) if driver == 'profilebench' else audit_point(checker, row, driver)
                    item['independent_witness_integrity'] = True
                    item['status'] = 'feasible_materialization_integrity_complete_native_row' if item['native_complete'] else 'feasible_saved_witnesses_native_incomplete'
                    item.update(raw_witnesses_at_base=len(result['raw']), final_witnesses_at_base=len(result['final']),
                                readiness_observations_checked=result['readiness_observations'],
                                grid_cells_checked_per_stage=result['grid_cells_checked_per_stage'],
                                saved_witness_materializations_checked=result['saved_witness_materializations_checked'])
                    extension = result.get('physical_extension_counterexamples', [])
                    if extension:
                        item['status'] = 'complete_native_profile_saved_witness_counterexample'
                    item['saved_witness_counterexample_cells'] = len(extension)
                    for counterexample in extension:
                        counterexamples.append({**context, 'query_id': qid, **counterexample})
                    rr['physical_extension_counterexample_cells'] += len(extension)
                    rr['conservative_point_boundary_count'] += result.get('conservative_point_boundary_count', 0)
                    rr['complete_independent_rows'] += item['native_complete'] and not extension
                    rr['independent_empty_rows'] += item['native_complete'] and not result['final']
                    for key in ('grid_cells_checked_per_stage', 'saved_witness_materializations_checked'):
                        rr[key] += result[key]
                    rr['readiness_observations_checked'] += result['readiness_observations']
                except ERRORS as exc:
                    rr['validation_failed_rows'] += 1
                    item['status'] = 'independent_witness_integrity_failed'
                    item['error'] = type(exc).__name__ + ': ' + str(exc)
                    errors.append({**context, 'query_id': qid, 'scope': 'row_witness_integrity', 'error': item['error']})
                # Donation is a separate per-witness feasibility gate. Neither
                # a native row error nor a saved-witness counterexample can
                # turn a feasible partial witness into a complete serving row.
                try:
                    donated, failures = base_donations(checker, row, driver)
                    lineage = dict(context)
                    lineage['native_record_index'] = record_indices[qid]
                    lineage['source_native_query'] = row['query']
                    lineage['source_native_complete'] = item['native_complete']
                    lineage['source_independent_row_status'] = item['status']
                    for stage in ('raw', 'final'):
                        for index, (checked, transformation) in enumerate(donated[stage]):
                            export_occurrence(witnesses, checked, q, fragments[qid], lineage, stage, index, transformation)
                            rr['feasible_reference_witness_occurrences'] += 1
                    for failure in failures:
                        donation_failures.append({**lineage, 'query_id': qid, **failure})
                except ERRORS as exc:
                    donation_failures.append({**context, 'query_id': qid, 'scope': 'donation_gate', 'error': type(exc).__name__ + ': ' + str(exc)})
            statuses[item['status']] += 1
            offers.append(item)
            if driver in {'tadbench', 'profilebench'}:
                for slot in scalar_by_query.get(qid, []):
                    require(q == slot['query'], 'native/base query differs from scalar reference query')
                    supported = slot['weight']['extra_walk_weight'] == 0 and (driver == 'profilebench' or slot['weight']['transfer_seconds'] == 0)
                    for stage in ('raw', 'final'):
                        candidates = [x[0] for x in donated[stage]]
                        compared = comparison(candidates, slot) if supported and (candidates or result) else {'status': 'unsupported_native_objective' if not supported else 'native_witness_unavailable_or_invalid'}
                        comparisons.append({**context, 'query_id': qid, 'query_canonical_sha256': bytes_sha(canonical(q).encode()),
                                            'stage': stage, 'weight_index': slot['weight_index'], 'weight': slot['weight'],
                                            'scalar_complete': slot['complete'], 'scalar_found': slot['found'], 'scalar_error': slot['error'],
                                            'readiness': q['departure'], 'native_complete': item['native_complete'],
                                            'independent_row_status': item['status'], **compared})
        rr['statuses'] = dict(statuses)
        run_reports.append(rr)
    offers.close(); witnesses.close(); scalar_sink.close(); comparisons.close(); counterexamples.close(); donation_failures.close()
    put(out / 'VALIDATION_ERRORS.json', errors)
    report = {'schema': 'sg-native-transit-independent-window-audit-v1', 'window': window,
              'model_count': 1, 'runs': run_reports, 'offered_native_rows': sum(x['offered'] for x in run_reports),
              'original_scalar_offered_slots': len(slots), 'original_scalar_complete_slots': sum(x['complete'] for x in slots.values()),
              'original_scalar_unknown_slots': sum(not x['complete'] for x in slots.values()),
              'feasible_reference_witness_occurrences': witnesses.count, 'validation_errors': len(errors),
              'physical_extension_counterexample_cells': counterexamples.count,
              'donation_reconstruction_failures': donation_failures.count, 'inputs': bindings}
    put(out / 'REPORT.json', report)
    print(canonical({k: report[k] for k in ('window', 'offered_native_rows', 'original_scalar_offered_slots', 'original_scalar_unknown_slots', 'feasible_reference_witness_occurrences', 'validation_errors')}), flush=True)


def child_limits():
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_AS_BYTES, CHILD_AS_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CHILD_CPU_SECONDS, CHILD_CPU_SECONDS + 1))


def coordinator(campaigns, out):
    with LOCK.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        out.mkdir()
        source = ROOT / 'evidence/scalar-original-source-a4047f4'
        require(source_fingerprint(source) == ORIGINAL_SOURCE, 'original scalar snapshot source fingerprint differs')
        schema_path = ROOT / 'analysis/feasible_reference_schema_v1.json'
        helper_paths = [Path(__file__), ROOT.parent / 'evalkit/evalkit.py', ROOT / 'analysis/summarize_native_auxiliary_v1.py', schema_path]
        helper_hashes = {str(p): digest(p) for p in helper_paths}
        with (out / 'FEASIBLE_REFERENCE_SCHEMA.json').open('xb') as target:
            target.write(schema_path.read_bytes())
        put(out / 'HELPER_AND_ORIGINAL_REFERENCE_FREEZE.json', {'helper_files': helper_hashes, 'original_scalar_source_snapshot': str(source),
             'original_scalar_source_sha256': ORIGINAL_SOURCE, 'original_scalar_binary_sha256': ORIGINAL_BINARY,
             'execution': 'global flock held across one exact-model/window subprocess at a time; offline audit only',
             'per_window_bounds': {'address_space_bytes': CHILD_AS_BYTES, 'cpu_soft_seconds': CHILD_CPU_SECONDS,
                                   'cpu_hard_seconds': CHILD_CPU_SECONDS + 1, 'wall_timeout_seconds': CHILD_WALL_SECONDS}})
        for window in ('evening', 'midday', 'morning', 'overnight'):
            cmd = [sys.executable, str(Path(__file__).resolve()), '--window', window, '--inherited-lock-fd', str(lock.fileno()), '--out', str(out / window)]
            for campaign in campaigns:
                cmd += ['--campaign', str(campaign)]
            try:
                subprocess.run(cmd, check=True, pass_fds=(lock.fileno(),), timeout=CHILD_WALL_SECONDS,
                               start_new_session=True, preexec_fn=child_limits)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
                put(out / 'WINDOW_PROCESS_FAILURE.json', {'window': window, 'error': str(exc), 'type': type(exc).__name__,
                    'returncode': getattr(exc, 'returncode', None), 'wall_timeout_seconds': CHILD_WALL_SECONDS,
                    'address_space_bytes': CHILD_AS_BYTES, 'cpu_soft_seconds': CHILD_CPU_SECONDS,
                    'status': 'attempt_incomplete_no_final_audit_report; partial outputs retained, no successful denominator inferred'})
                raise
        require(all(digest(p) == sha for p, sha in helper_hashes.items()), 'audit helper changed during execution')
        bindings, windows = {}, []
        for window in ('evening', 'midday', 'morning', 'overnight'):
            windows.append(read(out / window / 'REPORT.json', bindings))
        for name in ('FEASIBLE_REFERENCE_WITNESSES.jsonl', 'OFFERED_NATIVE_ROWS.jsonl', 'ORIGINAL_SCALAR_SLOTS.jsonl', 'SCALAR_COMPARISONS.jsonl', 'SAVED_WITNESS_COUNTEREXAMPLES.jsonl', 'DONATION_RECONSTRUCTION_FAILURES.jsonl'):
            with (out / name).open('xb') as target:
                for window in windows:
                    path = out / window['window'] / name
                    bindings[str(path)] = digest(path)
                    with path.open('rb') as stream:
                        for line in stream:
                            target.write(line)
        runs = [r for w in windows for r in w['runs']]
        inventory_path = ROOT / 'analysis/native-tune-v5-inventory-attempt01.json'
        original_inventory = read(inventory_path, bindings)
        put(out / 'NATIVE_CAMPAIGN_INVENTORY_SCOPE.json', {'source_path': str(inventory_path),
            'source_sha256': bindings[str(inventory_path.resolve())],
            'scope': 'All original native attempts preserved; only TAD/range_raptor/trip_based receive transit witness audit here.',
            'runs': [{'campaign': r.get('campaign'), 'id': r['id'], 'family': r.get('family'),
                      'offered': r.get('offered'), 'original_status': r['status'],
                      'transit_audit_selected': r.get('family') in FAMILIES} for r in original_inventory['runs']]})
        families = []
        for family in sorted(FAMILIES):
            members = [r for r in runs if r['family'] == family]
            families.append({'family': family, 'runs': len(members),
                **{key: sum(r[key] for r in members) for key in ('offered', 'native_complete_rows', 'complete_independent_rows',
                    'validation_failed_rows', 'independent_empty_rows', 'readiness_observations_checked',
                    'grid_cells_checked_per_stage', 'saved_witness_materializations_checked',
                    'physical_extension_counterexample_cells', 'conservative_point_boundary_count', 'feasible_reference_witness_occurrences')},
                'completion_scope': 'independent saved-witness feasibility/materialization integrity only, not search completeness or point-serving denominator'})
        counts = collections.Counter()
        with (out / 'SCALAR_COMPARISONS.jsonl').open() as stream:
            for line in stream:
                row = json.loads(line)
                counts[(row['family'], row['stage'], row['status'])] += 1
        report = {'schema': 'sg-native-transit-independent-audit-v1', 'runs': runs,
                  'families': families,
                  'offered_native_rows': sum(w['offered_native_rows'] for w in windows),
                  'original_scalar_offered_slots': sum(w['original_scalar_offered_slots'] for w in windows),
                  'original_scalar_complete_slots': sum(w['original_scalar_complete_slots'] for w in windows),
                  'original_scalar_unknown_slots': sum(w['original_scalar_unknown_slots'] for w in windows),
                  'feasible_reference_witness_occurrences': sum(w['feasible_reference_witness_occurrences'] for w in windows),
                  'validation_errors': sum(w['validation_errors'] for w in windows),
                  'physical_extension_counterexample_cells': sum(w['physical_extension_counterexample_cells'] for w in windows),
                  'donation_reconstruction_failures': sum(w['donation_reconstruction_failures'] for w in windows),
                  'scalar_comparisons': [{'family': f, 'stage': s, 'status': t, 'count': n} for (f, s, t), n in sorted(counts.items())],
                  'limitations': ['All profile claims are saved-witness feasibility/materialization integrity, not missing-witness or whole-profile completeness.',
                    'TAD is one earliest-arrival witness, not a Pareto frontier or displayed portfolio.',
                    'Native whole profiles remain whole profile requests; 61 readiness observations are not independent point timings.',
                    'Scalar optimality comparisons use only the original complete exact-query slots at original readiness. TAD supports weight(0,0); range supports extra_walk_weight=0 only.',
                    'Original scalar empty and unknown slots and every native unavailable/preparation failure remain explicit.',
                    'Native source provenance binds freeze, emitted runtime/build, and supervisor before/after records, not signed attestation.',
                    'Feasible reference exports are additive witnesses only; they do not mint scalar proofs or alter the certified point loader.',
                    'Range witnesses use RAPTOR donor family; TAD is separate; legacy trip-based witnesses use TripBased.',
                    'Native source-domain TP queries are different OD offers and are excluded from this primary-query export.',
                    'CoreCH graph rows are not transit and are outside this audit; their mandatory Bellman-Ford graph audit is separate.'],
                  'inputs': bindings, 'helper_files': helper_hashes}
        report['feasible_reference_schema_sha256'] = helper_hashes[str(schema_path)]
        put(out / 'REPORT.json', report)
        put(out / 'ARTIFACT_SHA256.json', {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file()})
        print(canonical({k: report[k] for k in ('offered_native_rows', 'original_scalar_offered_slots', 'original_scalar_complete_slots', 'original_scalar_unknown_slots', 'feasible_reference_witness_occurrences', 'validation_errors')}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--campaign', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--window', choices=('evening', 'midday', 'morning', 'overnight'))
    parser.add_argument('--inherited-lock-fd', type=int)
    args = parser.parse_args()
    if args.window:
        require(args.inherited_lock_fd is not None, 'window child requires inherited campaign lock')
        require(os.fstat(args.inherited_lock_fd).st_ino == LOCK.stat().st_ino, 'wrong inherited campaign lock')
        require(resource.getrlimit(resource.RLIMIT_AS) == (CHILD_AS_BYTES, CHILD_AS_BYTES) and
                resource.getrlimit(resource.RLIMIT_CPU) == (CHILD_CPU_SECONDS, CHILD_CPU_SECONDS + 1),
                'bounded window child limits missing')
        audit_window(args.window, args.campaign, args.out)
    else:
        coordinator(args.campaign, args.out)


if __name__ == '__main__':
    main()
