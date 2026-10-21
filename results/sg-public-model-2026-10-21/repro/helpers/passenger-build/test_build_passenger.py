import copy
import json
from pathlib import Path
import tempfile
import unittest
import build_passenger as b


def fixture():
    raw = {'nodes': [{'id': i, 'lat': 1.3, 'lon': 103+i/10000} for i in range(1, 8)],
           'edges': [{'id': name, 'from': x, 'to': y, 'seconds': cost, 'metres': cost}
                     for name, x, y, cost in [('12',1,2,9),('23',2,3,11),('32',3,2,14),
                        ('34',3,4,7),('45',4,5,590),('51',5,1,3),('26',2,6,1),('71',7,1,2)]]}
    bindings = {'bindings': [{'transit_stop_id': sid, 'osm_graph_node_id': nid, 'connector_seconds': c,
        'gtfs_lat': 1.3, 'gtfs_lon': 103+nid/10000, 'method': 'identity' if not c else 'assumed'}
        for sid, nid, c in [('A',2,0),('B',3,4),('C',4,0),('D',5,1)]], 'unbound': []}
    anchors = [{'source_stop_id': 'A', 'osm_graph_node_id': 1, 'origin_anchor': b.anchor_id('origin',1), 'destination_anchor': b.anchor_id('destination',1)},
               {'source_stop_id': 'C', 'osm_graph_node_id': 7, 'origin_anchor': b.anchor_id('origin',7), 'destination_anchor': b.anchor_id('destination',7)}]
    plan = {'anchors': anchors, 'sources': {'osm_graph': {'sha256': 'g'}, 'stop_bindings': {'sha256': 'b'}}}
    return raw, bindings, plan


class PassengerTests(unittest.TestCase):
    def test_all_directed_shortest_candidates_exhaustive_floyd_reference(self):
        raw, bindings, plan = fixture()
        paths, witnesses, stats = b.build_links(plan, b.Graph(raw), bindings)
        ids = [n['id'] for n in raw['nodes']]
        d = {(i,j): 0 if i == j else float('inf') for i in ids for j in ids}
        for e in raw['edges']:
            d[e['from'],e['to']] = min(d[e['from'],e['to']], e['seconds'])
        for k in ids:
            for i in ids:
                for j in ids:
                    d[i,j] = min(d[i,j], d[i,k]+d[k,j])
        expected = {}
        for a in plan['anchors']:
            for target in bindings['bindings']:
                n, t, c = a['osm_graph_node_id'], target['osm_graph_node_id'], target['connector_seconds']
                for role, x, y, sec in [('access',a['origin_anchor'],target['transit_stop_id'],d[n,t]+c),
                                       ('egress',target['transit_stop_id'],a['destination_anchor'],d[t,n]+c)]:
                    if sec <= 600:
                        expected[role,x,y] = sec
            for z in plan['anchors']:
                sec = d[a['osm_graph_node_id'],z['osm_graph_node_id']]
                if a is not z and sec <= 600:
                    expected['direct',a['origin_anchor'],z['destination_anchor']] = sec
        self.assertEqual(expected, {(w['role'],w['from'],w['to']): w['duration'] for w in witnesses})
        self.assertEqual(len(paths), len(witnesses))
        # Zero target connector remains exactly zero: 9 seconds, not 10.
        self.assertEqual(9, expected['access',b.anchor_id('origin',1),'A'])
        # Directed asymmetry and the 600-second cutoff are not geometric proxies.
        self.assertNotEqual(d[1,3],d[3,1])
        self.assertNotIn(('access',b.anchor_id('origin',1),'D'), expected)
        self.assertIn(('direct',b.anchor_id('origin',7),b.anchor_id('destination',1)), expected)
        self.assertNotIn(('direct',b.anchor_id('origin',1),b.anchor_id('destination',7)), expected)

    def test_independent_witness_direction_and_exact_cost(self):
        raw, bindings, plan = fixture()
        paths, witnesses, stats = b.build_links(plan, b.Graph(raw), bindings)
        edges = {e['id']: e for e in raw['edges']}
        bs = {x['transit_stop_id']: x for x in bindings['bindings']}
        for w in witnesses:
            ns = w['osm_node_ids']
            self.assertGreater(len(w['osm_edge_ids']), 0)
            self.assertEqual(len(ns), len(w['osm_edge_ids'])+1)
            total = 0
            for x,y,eid in zip(ns,ns[1:],w['osm_edge_ids']):
                e = edges[eid]
                self.assertEqual((x,y), (e['from'],e['to']))
                total += e['seconds']
            self.assertEqual(total, w['osm_seconds'])
            self.assertEqual(total+w['connector_seconds'], w['duration'])
            if w['role'] == 'access':
                self.assertEqual(ns[-1], bs[w['connector_stop_id']]['osm_graph_node_id'])
            elif w['role'] == 'egress':
                self.assertEqual(ns[0], bs[w['connector_stop_id']]['osm_graph_node_id'])

    def test_anchor_purity_and_mutation_rejection(self):
        raw, bindings, plan = fixture()
        links, _, _ = b.build_links(plan,b.Graph(raw),bindings)
        ids = ['A','B','C','D']+[a[r] for a in plan['anchors'] for r in ('origin_anchor','destination_anchor')]
        dataset = {'stops': [{'id': x} for x in ids], 'connections': [], 'footpaths': links}
        self.assertEqual(0,b.check_anchor_isolation(dataset,plan['anchors'])['source_incoming'])
        for edge in [{'from':'A','to':plan['anchors'][0]['origin_anchor'],'duration':1},
                     {'from':plan['anchors'][0]['destination_anchor'],'to':'A','duration':1},
                     {'from':'A','to':'B','duration':0}]:
            changed = copy.deepcopy(dataset)
            changed['footpaths'].append(edge)
            with self.assertRaises(ValueError):
                b.check_anchor_isolation(changed,plan['anchors'])

    def test_locations_are_deterministic_topology_only(self):
        raw, bindings, _ = fixture()
        plan = {'clusters':[{'origin':'A','destination':'C'},{'origin':'X','destination':'A'}]}
        one = b.select_anchors(plan,raw,bindings)
        changed = copy.deepcopy(plan)
        changed['clusters'].reverse()
        self.assertEqual(one,b.select_anchors(changed,raw,bindings))
        forbidden = {(n['lat'],n['lon']) for n in raw['nodes'] if n['id'] in [x['osm_graph_node_id'] for x in bindings['bindings']]}
        for a in one[0]:
            self.assertNotIn((a['lat'],a['lon']),forbidden)
            self.assertGreater(a['displacement_metres'],0)
        self.assertTrue(any(x['source_stop_id']=='X' for x in one[1]))

    def test_colocated_anchor_does_not_receive_padding(self):
        raw, bindings, plan = fixture()
        plan['anchors'][0]['osm_graph_node_id'] = 2
        with self.assertRaisesRegex(ValueError,'zero/over-cap'):
            b.build_links(plan,b.Graph(raw),bindings)

    def test_write_is_immutable(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)/'out.json'
            b.write(p,{'x':1})
            with self.assertRaises(FileExistsError):
                b.write(p,{'x':2})
            self.assertEqual({'x':1},b.read(p))

if __name__ == '__main__':
    unittest.main(verbosity=2)
