#!/usr/bin/env python3
"""Independent witness-chain/cost audit; does not use the generator path finder."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(plan_path, build_path):
    plan = json.loads(Path(plan_path).read_bytes())
    folder = Path(build_path)
    manifest = json.loads((folder/'build-manifest.json').read_bytes())
    assert digest(plan_path) == manifest['anchor_plan']['sha256']
    graph_ref, bind_ref = plan['sources']['osm_graph'], plan['sources']['stop_bindings']
    assert digest(graph_ref['path']) == graph_ref['sha256']
    assert digest(bind_ref['path']) == bind_ref['sha256']
    graph = json.loads(Path(graph_ref['path']).read_bytes())
    bindings = json.loads(Path(bind_ref['path']).read_bytes())
    edges = {e['id']: e for e in graph['edges']}
    bs = {x['transit_stop_id']: x for x in bindings['bindings']}
    origins = {a['origin_anchor']: a['osm_graph_node_id'] for a in plan['anchors']}
    destinations = {a['destination_anchor']: a['osm_graph_node_id'] for a in plan['anchors']}
    delta_path, witness_path = folder/'enrichment-delta.json', folder/'path-witnesses.jsonl'
    assert digest(delta_path) == manifest['enrichment_delta_sha256']
    assert digest(witness_path) == manifest['witnesses_sha256']
    delta = json.loads(delta_path.read_bytes())
    paths = {p['id']: p for p in delta['footpaths_to_add'] if p['id'].startswith('passenger-v1:')}
    witnessed, roles, original_edge_traversals, zero_connectors = set(), {}, 0, 0
    for line in witness_path.read_text().splitlines():
        w = json.loads(line)
        p = paths[w['footpath_id']]
        assert w['footpath_id'] not in witnessed
        witnessed.add(w['footpath_id'])
        assert (p['from'],p['to'],p['duration']) == (w['from'],w['to'],w['duration'])
        ns, es = w['osm_node_ids'], w['osm_edge_ids']
        assert len(ns) == len(es)+1 and len(es)>0
        seconds = 0
        for frm,to,eid in zip(ns,ns[1:],es):
            e = edges[eid]
            assert (frm,to) == (e['from'],e['to'])
            seconds += e['seconds']
        assert seconds == w['osm_seconds']
        assert 0 < seconds+w['connector_seconds'] == w['duration'] <= 600
        if w['role'] == 'access':
            binding = bs[w['connector_stop_id']]
            assert ns[0] == origins[w['from']] and ns[-1] == binding['osm_graph_node_id']
            assert w['to'] == binding['transit_stop_id']
        elif w['role'] == 'egress':
            binding = bs[w['connector_stop_id']]
            assert ns[0] == binding['osm_graph_node_id'] and ns[-1] == destinations[w['to']]
            assert w['from'] == binding['transit_stop_id']
        else:
            assert w['role'] == 'direct'
            assert ns[0] == origins[w['from']] and ns[-1] == destinations[w['to']]
            binding = None
        assert w['connector_seconds'] == (binding['connector_seconds'] if binding else 0)
        original_edge_traversals += len(es)
        zero_connectors += int(w['connector_seconds']==0)
        roles[w['role']] = roles.get(w['role'],0)+1
    assert witnessed == paths.keys()
    return {'schema':'sg-passenger-independent-witness-chain-audit-v1','pass':True,'anchor_plan_sha256':digest(plan_path),
        'delta_sha256':digest(delta_path),'witnesses_sha256':digest(witness_path),'witnesses':len(witnessed),
        'roles':roles,'original_directed_edge_traversals_checked':original_edge_traversals,
        'zero_connector_paths_without_padding':zero_connectors,
        'scope':'Every emitted pilot path direction, OSM edge chain, endpoint mapping, raw connector cost and <=600 total is independently reconstructed. This is not an independent large-graph completeness or real-world accessibility certificate.'}

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',required=True);p.add_argument('--build',required=True);p.add_argument('--out',required=True)
    a=p.parse_args(); result=run(a.plan,a.build)
    with Path(a.out).open('x') as f: json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(result,sort_keys=True))
