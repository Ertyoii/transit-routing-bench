#!/usr/bin/env python3
"""Immutable positive-cost OSM-node passenger anchors, not independent stop-pair batching.

No router is called. Inputs remain unchanged. prepare fixes actual anchor locations,
build computes exact bounded directed OSM attachment paths, and materialize/bind
produce native finite-model inputs with a common dataset for every routing family.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys
import time

SCHEMA = 'sg-positive-osm-passenger-anchors-v1'
CAP = 600
PREFIX = 'passenger-v1:'


def canonical(x):
    return (json.dumps(x, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, obj, compact=False):
    data = (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode() if compact else canonical(obj)
    with Path(path).open('xb') as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def source(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def checked_source(ref):
    if sha(ref['path']) != ref['sha256']:
        raise ValueError('source changed: '+ref['path'])
    return read(ref['path'])


def distance(a, b):
    x, y = math.radians(a[0]), math.radians(b[0])
    h = math.sin((y-x)/2)**2 + math.cos(x)*math.cos(y)*math.sin(math.radians(b[1]-a[1])/2)**2
    return 6371000*2*math.asin(min(1, math.sqrt(max(0, h))))


def anchor_id(role, node):
    return f'{PREFIX}{role}:osm:{node}'


def select_anchors(plan, graph, bindings):
    """Topology/coordinate-only rule; does not inspect any route or timing outcome."""
    nodes = {n['id']: n for n in graph['nodes']}
    bs = {b['transit_stop_id']: b for b in bindings['bindings']}
    forbidden = {(nodes[b['osm_graph_node_id']]['lat'], nodes[b['osm_graph_node_id']]['lon']) for b in bs.values()}
    adjacent = defaultdict(set)
    for e in graph['edges']:
        if e['seconds'] <= 0:
            raise ValueError('OSM graph requires positive edge costs')
        adjacent[e['from']].add(e['to'])
        adjacent[e['to']].add(e['from'])
    wanted = sorted({c[k] for c in plan['clusters'] for k in ('origin', 'destination')})
    used, anchors, missing = set(), [], []
    for sid in wanted:
        b = bs.get(sid)
        if b is None:
            missing.append({'source_stop_id': sid, 'status': 'unsupported_no_conservative_stop_binding'})
            continue
        original = (b['gtfs_lat'], b['gtfs_lon'])
        choices = []
        for nid in adjacent[b['osm_graph_node_id']]:
            n = nodes[nid]
            pos = (n['lat'], n['lon'])
            if pos in forbidden or pos in used or distance(pos, original) == 0:
                continue
            choices.append((distance(pos, original), nid, pos))
        if not choices:
            missing.append({'source_stop_id': sid, 'status': 'unsupported_no_distinct_adjacent_positive_point'})
            continue
        metres, nid, pos = min(choices)
        used.add(pos)
        anchors.append({'source_stop_id': sid, 'osm_graph_node_id': nid, 'lat': pos[0], 'lon': pos[1],
            'source_stop_lat': original[0], 'source_stop_lon': original[1], 'displacement_metres': round(metres, 6),
            'source_binding_graph_node_id': b['osm_graph_node_id'], 'origin_anchor': anchor_id('origin', nid),
            'destination_anchor': anchor_id('destination', nid), 'accessible': 'unknown'})
    return anchors, missing


def prepare(args):
    plan_path = Path(args.plan).resolve()
    plan = read(plan_path)
    commit = read(plan_path.parent/'HASH_COMMITMENT.json')
    if commit['planned_workload_sha256'] != sha(plan_path):
        raise ValueError('original plan hash commitment mismatch')
    graph, bindings = read(args.graph), read(args.bindings)
    selected = dict(plan)
    selected['clusters'] = [c for c in plan['clusters'] if not args.stage or c['stage'] in args.stage]
    anchors, missing = select_anchors(selected, graph, bindings)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    doc = {'schema': SCHEMA, 'seed': plan['seed'], 'selected_stages': args.stage or plan['parameters']['stages'], 'source_status': 'provisional_research_only_not_latest_official_LTA_qualified', 'sources': {'workload_plan': source(args.plan),
        'osm_graph': source(args.graph), 'stop_bindings': source(args.bindings)}, 'cap_seconds': CAP,
        'selection': 'In sorted original endpoint stop-ID order, select the coordinate-nearest incident OSM neighbor of its conservative binding graph node, tie by node ID; exclude coordinates shared by any stop binding or an earlier chosen anchor. No reachability, router, quality or latency outcomes are consulted. Missing points are never replaced.',
        'query_relationship': 'Different physical request from original stop-coordinate workload; original OD clusters, splits, departure offsets and caps retained as provenance.',
        'coverage': 'restricted shifted OSM-node bus-anchor pilot, not arbitrary points or all Singapore; unbound and rail endpoints remain unsupported, not physically unreachable',
        'anchors': anchors, 'unavailable_endpoints': missing,
        'identity_policy': 'Stable macro footpath IDs; one canonical shortest OSM witness per directed endpoint pair; not enumeration of all physical pedestrian paths or strict physical-path identity top-k.'}
    ph = write(out/'anchor-plan.json', doc)
    write(out/'HASH_COMMITMENT.json', {'schema': SCHEMA+'-commitment', 'anchor_plan_sha256': ph,
        'generator_sha256': sha(__file__), 'selected_without_routing_outcomes': True,
        'anchors': len(anchors), 'unavailable_endpoints': len(missing)})
    print(json.dumps({'anchor_plan_sha256': ph, 'anchors': len(anchors), 'unavailable_endpoints': len(missing)}))


def load_plan(path):
    doc = read(path)
    if doc['schema'] != SCHEMA or read(Path(path).parent/'HASH_COMMITMENT.json')['anchor_plan_sha256'] != sha(path):
        raise ValueError('anchor plan schema/hash mismatch')
    return doc


class Graph:
    def __init__(self, raw):
        self.nodes = {n['id']: n for n in raw['nodes']}
        self.edges = raw['edges']
        self.forward, self.reverse = defaultdict(list), defaultdict(list)
        ids = set()
        for i, e in enumerate(self.edges):
            if e['id'] in ids or e['seconds'] <= 0 or e['from'] not in self.nodes or e['to'] not in self.nodes:
                raise ValueError('invalid OSM graph edge')
            ids.add(e['id'])
            self.forward[e['from']].append((e['to'], e['seconds'], i))
            self.reverse[e['to']].append((e['from'], e['seconds'], i))
        for adj in (self.forward, self.reverse):
            for es in adj.values():
                es.sort(key=lambda x: (x[0], x[1], self.edges[x[2]]['id']))

    def search(self, node, reverse=False, cap=CAP):
        adj = self.reverse if reverse else self.forward
        dist, prev, queue = {node: 0}, {}, [(0, node)]
        while queue:
            du, u = heapq.heappop(queue)
            if du != dist[u]:
                continue
            for v, sec, i in adj.get(u, ()):
                nd = du+sec
                if nd <= cap and nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, (u, i)
                    heapq.heappush(queue, (nd, v))
        return dist, prev

    def witness(self, src, dst, prev, reverse=False):
        # Reverse search prev points along original edges toward src (the anchor).
        edges, nodes, at = [], [dst], dst
        while at != src:
            after, i = prev[at]
            edges.append(self.edges[i]['id'])
            nodes.append(after)
            at = after
        if not reverse:
            edges.reverse()
            nodes.reverse()
        return edges, nodes


def build_links(plan, graph, bindings):
    targets = defaultdict(list)
    for b in sorted(bindings['bindings'], key=lambda b: b['transit_stop_id']):
        if b['connector_seconds'] < 0:
            raise ValueError('negative stop connector')
        targets[b['osm_graph_node_id']].append(b)
    anchor_nodes = {a['osm_graph_node_id']: a for a in plan['anchors']}
    links, witnesses, stats = [], [], []
    gh = plan['sources']['osm_graph']['sha256']
    bh = plan['sources']['stop_bindings']['sha256']
    def add(role, from_id, to_id, duration, edges, nodes, connector, binding=None):
        if not 0 < duration <= CAP:
            raise ValueError('zero/over-cap passenger edge; location cannot be padded')
        fid = f'{PREFIX}{role}:{from_id}:{to_id}'
        links.append({'id': fid, 'from': from_id, 'to': to_id, 'duration': duration, 'accessible': 'unknown',
            'provenance': f'passenger-anchor-v1;OSM:{gh};bindings:{bh};raw-connector-seconds-no-padding;ODbL-1.0'})
        witnesses.append({'footpath_id': fid, 'role': role, 'from': from_id, 'to': to_id, 'duration': duration,
            'osm_edge_ids': edges, 'osm_node_ids': nodes, 'osm_seconds': duration-connector,
            'connector_seconds': connector, 'connector_stop_id': binding['transit_stop_id'] if binding else None,
            'connector_method': binding['method'] if binding else None, 'connector_assumed': bool(connector),
            'graph_sha256': gh, 'bindings_sha256': bh, 'physical_verification': False})
    for a in plan['anchors']:
        nid = a['osm_graph_node_id']
        counts = Counter()
        for reverse in (False, True):
            dist, prev = graph.search(nid, reverse=reverse)
            for node in sorted(dist):
                for b in targets.get(node, ()):
                    duration = dist[node]+b['connector_seconds']
                    if duration > CAP:
                        continue
                    edge_ids, node_ids = graph.witness(nid, node, prev, reverse)
                    if reverse:
                        add('egress', b['transit_stop_id'], a['destination_anchor'], duration,
                            edge_ids, node_ids, b['connector_seconds'], b)
                    else:
                        add('access', a['origin_anchor'], b['transit_stop_id'], duration,
                            edge_ids, node_ids, b['connector_seconds'], b)
                    counts['egress' if reverse else 'access'] += 1
                if not reverse and node != nid and node in anchor_nodes:
                    edge_ids, node_ids = graph.witness(nid, node, prev)
                    add('direct', a['origin_anchor'], anchor_nodes[node]['destination_anchor'], dist[node], edge_ids, node_ids, 0)
                    counts['direct'] += 1
            counts['reverse_settled' if reverse else 'forward_settled'] = len(dist)
        stats.append({'source_stop_id': a['source_stop_id'], 'osm_node_id': nid, **dict(counts)})
    links.sort(key=lambda x: x['id'])
    witnesses.sort(key=lambda x: x['footpath_id'])
    return links, witnesses, stats


def check_anchor_isolation(dataset, anchors):
    sources = {a['origin_anchor'] for a in anchors}
    sinks = {a['destination_anchor'] for a in anchors}
    if sources & sinks:
        raise ValueError('source and sink roles overlap')
    if len({s['id'] for s in dataset['stops']}) != len(dataset['stops']):
        raise ValueError('duplicate stop ID')
    for c in dataset['connections']:
        if c['from'] in sources|sinks or c['to'] in sources|sinks:
            raise ValueError('anchor has transit service')
    for r in dataset.get('transfers', []):
        if r['from_stop'] in sources|sinks or r['to_stop'] in sources|sinks:
            raise ValueError('anchor has transfer rule')
    for w in dataset['footpaths']:
        if w['duration'] <= 0 or w['from'] in sinks or w['to'] in sources:
            raise ValueError('anchor direction/cost violated')
    return {'source_incoming': 0, 'sink_outgoing': 0, 'anchor_transit_connections': 0,
        'proof': 'No anchor can be an interior vertex: origins have indegree zero, destinations outdegree zero. Therefore adding other queries anchors cannot introduce transit-to-transit shortcuts.'}


def build(args):
    started = time.perf_counter()
    plan = load_plan(args.anchor_plan)
    raw = checked_source(plan['sources']['osm_graph'])
    bindings = checked_source(plan['sources']['stop_bindings'])
    graph = Graph(raw)
    links, witnesses, stats = build_links(plan, graph, bindings)
    closure = read(args.transfer_footpaths) if args.transfer_footpaths else []
    if any(w['id'].startswith(PREFIX) for w in closure):
        raise ValueError('transfer closure collides with anchor namespace')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    stops = [{'id': a[r], 'accessible': 'unknown'} for a in plan['anchors'] for r in ('origin_anchor', 'destination_anchor')]
    delta = {'schema': SCHEMA+'-delta', 'anchor_plan_sha256': sha(args.anchor_plan), 'stops_to_add': stops,
        'footpaths_to_add': closure+links, 'note': 'Transfer closure retained unchanged, including its disclosed max(1,connector_seconds) legacy policy. Passenger anchor links use raw connector seconds with no padding. Original dataset footpaths remain separate and unchanged.'}
    dh = write(out/'enrichment-delta.json', delta, compact=True)
    wh = hashlib.sha256()
    with (out/'path-witnesses.jsonl').open('xb') as f:
        for w in witnesses:
            data = (json.dumps(w, sort_keys=True, separators=(',', ':'))+'\n').encode()
            f.write(data)
            wh.update(data)
    stath = write(out/'anchor-candidate-counts.json', stats)
    manifest = {'schema': SCHEMA+'-build', 'anchor_plan': source(args.anchor_plan),
        'sources': {**plan['sources'], **({'transfer_footpaths': source(args.transfer_footpaths)} if args.transfer_footpaths else {})},
        'generator_sha256': sha(__file__), 'enrichment_delta_sha256': dh, 'witnesses_sha256': wh.hexdigest(),
        'candidate_counts_sha256': stath, 'anchors': len(plan['anchors']), 'added_stops': len(stops),
        'transfer_footpaths_added': len(closure), 'passenger_links_by_role': dict(Counter(w['role'] for w in witnesses)),
        'access_egress_stop_scope': 'all conservative-bound bus stops with shortest directed OSM cost plus raw explicit stop connector <=600 seconds; unbound stops not proven unreachable',
        'direct_scope': 'all distinct inventory anchor pairs with directed OSM shortest path <=600 seconds; same physical endpoint zero-distance requests unsupported by native positive-edge model',
        'common_dataset_requirement': 'Materialize once per service window; every family must consume identical bytes/hash and report enlarged input/preparation costs.',
        'duration_policy': 'No added passenger seconds, no zero native edges. Positive OSM path + raw connector. Access/egress/direct role and full total budgets remain native query/checker constraints.',
        'claims': {'true_joint_multi_seed_target_finite_model': True, 'all_singapore_anchors': False, 'arbitrary_point_requests': False,
            'rail_access_verified': False, 'wheelchair_accessibility_verified': False, 'real_world_walkability_verified': False,
            'all_physical_walking_path_identities_enumerated': False},
        'elapsed_data_preparation_seconds_not_latency': time.perf_counter()-started}
    write(out/'build-manifest.json', manifest)
    print(json.dumps({k: manifest[k] for k in ('anchors', 'added_stops', 'transfer_footpaths_added', 'passenger_links_by_role', 'enrichment_delta_sha256')}))


def materialize(args):
    manifest_path = Path(args.build)/'build-manifest.json'
    manifest = read(manifest_path)
    delta_path = Path(args.build)/'enrichment-delta.json'
    if sha(delta_path) != manifest['enrichment_delta_sha256']:
        raise ValueError('delta hash mismatch')
    plan = load_plan(manifest['anchor_plan']['path'])
    if sha(manifest['anchor_plan']['path']) != manifest['anchor_plan']['sha256']:
        raise ValueError('build anchor plan changed')
    refs = read(args.datasets)
    refs = refs.get('datasets', refs)
    delta = read(delta_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    outputs, missing = {}, []
    for window, input_path in sorted(refs.items()):
        base_ref = source(input_path)
        base = read(input_path)
        if not base.get('connections'):
            missing.append({'window': window, 'status': 'unsupported_input_profile_no_service_connections', 'source': base_ref})
            continue
        stop_ids = {s['id'] for s in base['stops']}
        foot_ids = {f['id'] for f in base['footpaths']}
        if any(s['id'] in stop_ids for s in delta['stops_to_add']) or any(f['id'] in foot_ids for f in delta['footpaths_to_add']):
            raise ValueError('delta already applied or identity collision')
        all_ids = stop_ids | {s['id'] for s in delta['stops_to_add']}
        if any(f['from'] not in all_ids or f['to'] not in all_ids for f in delta['footpaths_to_add']):
            raise ValueError('delta stop not in base dataset')
        base['stops'].extend(delta['stops_to_add'])
        base['footpaths'].extend(delta['footpaths_to_add'])
        base['id'] += '-passenger-'+sha(delta_path)[:12]
        isolation = check_anchor_isolation(base, plan['anchors'])
        path = out/(window+'.dataset.json')
        dh = write(path, base, compact=True)
        outputs[window] = {'path': str(path.resolve()), 'sha256': dh, 'source': base_ref,
            'stops': len(base['stops']), 'connections': len(base['connections']), 'footpaths': len(base['footpaths']), 'isolation': isolation}
    write(out/'datasets.json', {'datasets': {k: v['path'] for k, v in outputs.items()}})
    write(out/'materialization-manifest.json', {'schema': SCHEMA+'-materialized', 'build_manifest': source(manifest_path),
        'delta': source(delta_path), 'generator_sha256': sha(__file__), 'datasets': outputs, 'unavailable_windows': missing})
    print(json.dumps({'windows': list(outputs), 'unavailable_windows': missing}))


def bind(args):
    anchor_plan = load_plan(args.anchor_plan)
    original = checked_source(anchor_plan['sources']['workload_plan'])
    by_stop = {a['source_stop_id']: a for a in anchor_plan['anchors']}
    refs = read(args.datasets)
    refs = refs.get('datasets', refs)
    materialized = read(Path(args.datasets).parent/'materialization-manifest.json')
    materialized_build = checked_source(materialized['build_manifest'])
    if materialized_build['anchor_plan']['sha256'] != sha(args.anchor_plan):
        raise ValueError('materialized dataset belongs to a different anchor plan')
    for window, dp in refs.items():
        if window not in materialized['datasets'] or sha(dp) != materialized['datasets'][window]['sha256']:
            raise ValueError('materialized dataset hash mismatch')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    files, exclusions, records, unavailable = [], [], [], []
    for w in original['windows']:
        if w['id'] not in refs:
            unavailable.append({'window': w['id'], 'status': 'not_bound_input_unavailable'})
            continue
        dp = refs[w['id']]
        dataset = read(dp)
        if not dataset.get('connections'):
            unavailable.append({'window': w['id'], 'status': 'unsupported_input_profile_no_service_connections'})
            continue
        if dataset['service_date'] != w['service_date'] or dataset['time_zone'] != 'Asia/Singapore' or dataset['window'] != {'start': w['start'], 'end': w['end']}:
            raise ValueError('bound dataset date/time window mismatch')
        check_anchor_isolation(dataset, anchor_plan['anchors'])
        dataset_ids = {s['id'] for s in dataset['stops']}
        if any(a[r] not in dataset_ids for a in anchor_plan['anchors'] for r in ('origin_anchor', 'destination_anchor')):
            raise ValueError('dataset missing anchor inventory')
        dsha = sha(dp)
        for stage in anchor_plan['selected_stages']:
            for split in ('tune', 'validation', 'test'):
                clusters = [c for c in original['clusters'] if c['stage'] == stage and c['split'] == split]
                for profile_name, p in original['profiles'].items():
                    items, metadata = [], []
                    for c in clusters:
                        reason = None
                        if c['origin'] not in by_stop or c['destination'] not in by_stop:
                            reason = 'unsupported_anchor_endpoint_mapping'
                        elif by_stop[c['origin']]['osm_graph_node_id'] == by_stop[c['destination']]['osm_graph_node_id']:
                            reason = 'unsupported_zero_distance_native_anchor_request'
                        for i, offset in enumerate(c['departure_offsets'][w['id']]):
                            departure = w['departures_start']+offset
                            qid = f"{c['cluster_id']}|{w['id']}|d{i}|{profile_name}|passenger-anchor-v1"
                            if reason or departure+p['horizon_seconds'] > w['end']:
                                exclusions.append({'query_id': qid, 'cluster_id': c['cluster_id'], 'stage': stage, 'split': split,
                                    'window': w['id'], 'profile': profile_name, 'status': reason or 'not_applicable_horizon_not_fully_loaded'})
                                continue
                            q = {'id': qid, 'origin': by_stop[c['origin']]['origin_anchor'],
                                'destination': by_stop[c['destination']]['destination_anchor'], 'departure': departure,
                                'latest_arrival': departure+p['horizon_seconds'], 'transfer_buffer': original['parameters']['transfer_buffer'],
                                'max_walk_seconds': p['max_walk_seconds'], 'max_boardings': original['parameters']['max_boardings'],
                                'max_legs': original['parameters']['max_legs'], 'accessible_only': False, 'walking_limits': p['walking_limits']}
                            items.append({'stratum': c['construction_stratum'], 'query': q})
                            labels = [stage, w['id'], profile_name, c['construction_stratum'], c['distance_band'], 'restricted_shifted_osm_node_anchors', 'joint_multi_seed_target', 'unknown_accessibility']
                            metadata.append({'query_id': qid, 'od_cluster': c['cluster_id'], 'split': split, 'workload_cohort': 'model_coverage', 'labels': labels})
                            records.append({'query_id': qid, 'od_cluster': c['cluster_id'], 'split': split, 'stage': stage, 'window': w['id'], 'profile': profile_name,
                                'source_origin_stop': c['origin'], 'source_destination_stop': c['destination'], 'origin_anchor': q['origin'], 'destination_anchor': q['destination']})
                    if not items:
                        continue
                    filename = f"{w['id']}.{stage}.{split}.{profile_name}.json"
                    qsha = write(out/filename, {'seed': original['seed'], 'method': 'frozen shifted OSM-node anchors; genuine joint candidate-stop search; restricted conservative bus-anchor scope; no routing-outcome selection', 'dataset_sha256': dsha, 'items': items})
                    msha = write(out/(filename[:-5]+'.metadata.json'), {'schema_version': 'sg-coldstart-evalkit-v1', 'dataset_sha256': dsha, 'queries_sha256': qsha, 'items': metadata})
                    files.append({'path': filename, 'sha256': qsha, 'query_metadata_sha256': msha, 'dataset_sha256': dsha,
                        'window': w['id'], 'stage': stage, 'split': split, 'profile': profile_name, 'queries': len(items)})
    sidehash = write(out/'split-sidecar.json', {'schema': SCHEMA+'-splits', 'anchor_plan_sha256': sha(args.anchor_plan), 'records': records,
        'not_applicable_or_unsupported': exclusions, 'unavailable_windows': unavailable})
    result = {'schema': SCHEMA+'-bound', 'anchor_plan': source(args.anchor_plan), 'generator_sha256': sha(__file__),
        'split_sidecar_sha256': sidehash, 'files': files, 'queries_bound': len(records), 'excluded_by_reason': dict(Counter(x['status'] for x in exclusions)),
        'unavailable_windows': unavailable, 'note': 'Input-only build. No algorithms, test outcomes, quality or latency were run. Unsupported endpoints are not counted as valid-empty routes; full planned denominator retained in sidecar.'}
    write(out/'bound-manifest.json', result)
    print(json.dumps({k: result[k] for k in ('queries_bound', 'excluded_by_reason', 'unavailable_windows')}))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--plan', required=True); p.add_argument('--graph', required=True); p.add_argument('--bindings', required=True); p.add_argument('--out', required=True); p.add_argument('--stage', action='append', help='Select immutable input stage(s), e.g. smoke; never selected from outcomes'); p.set_defaults(func=prepare)
    p = sub.add_parser('build'); p.add_argument('--anchor-plan', required=True); p.add_argument('--transfer-footpaths', help='Existing witnessed closure to add unchanged; omit for anchor-only pilot delta'); p.add_argument('--out', required=True); p.set_defaults(func=build)
    p = sub.add_parser('materialize'); p.add_argument('--build', required=True); p.add_argument('--datasets', required=True); p.add_argument('--out', required=True); p.set_defaults(func=materialize)
    p = sub.add_parser('bind'); p.add_argument('--anchor-plan', required=True); p.add_argument('--datasets', required=True); p.add_argument('--out', required=True); p.set_defaults(func=bind)
    args = ap.parse_args(); args.func(args)

if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as e:
        print('passenger anchor error: '+str(e), file=sys.stderr)
        raise SystemExit(1)
