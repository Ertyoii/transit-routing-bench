import collections,json,math,time
from pathlib import Path
import build_walk as b
start=time.perf_counter();g=json.loads(Path('osm-pedestrian-graph.json').read_text());edges={x['id']:x for x in g['edges']};nodes={x['id'] for x in g['nodes']};bus={x['transit_stop_id']:x for x in json.loads(Path('stop-bindings.json').read_text())['bindings']};rail={x['transit_stop_id']:x for x in json.loads(Path('rail-sensitivity-bindings.json').read_text())['bindings']}
for e in edges.values():assert e['from'] in nodes and e['to'] in nodes and e['seconds']==b.cost(e['metres'])
result={'graph_nodes':len(nodes),'graph_edges':len(edges),'cost_model_checked_edges':len(edges),'layers':{}}
for layer in ['conservative600','rail-sensitivity600']:
 m=json.loads(Path(layer+'/closure-manifest.json').read_text());fps=json.loads(Path(layer+'/footpaths.json').read_text());assert b.sha(layer+'/footpaths.json')==m['footpaths_sha256'];assert b.sha(layer+'/path-witnesses.jsonl')==m['witnesses_sha256'];fmap={p['id']:p for p in fps};assert len(fmap)==len(fps);pairs=set();checked=0
 for line in open(layer+'/path-witnesses.jsonl'):
  x=json.loads(line);p=fmap[x['footpath_id']];assert x['from']==p['from'] and x['to']==p['to'] and x['duration']==p['duration'];assert 0<p['duration']<=600 and p['accessible']=='unknown';assert (p['from'],p['to']) not in pairs;pairs.add((p['from'],p['to']))
  ids=x['osm_node_ids'];es=x['edge_ids'];assert len(ids)==len(es)+1
  seconds=0
  for i,eid in enumerate(es):
   e=edges[eid];assert e['from']==ids[i] and e['to']==ids[i+1];seconds+=e['seconds']
  assert seconds==x['osm_path_seconds'];assert seconds+x['source_connector_seconds']+x['target_connector_seconds']==p['duration']
  for side,node,field,direction in [('from',ids[0],'source_connector_seconds','exit'),('to',ids[-1],'target_connector_seconds','entry')]:
   sid=p[side]
   if sid in bus:
    anchor=bus[sid];assert node==anchor['osm_graph_node_id'] and x[field]==max(1,anchor['connector_seconds'])
   else:
    assert layer=='rail-sensitivity600' and sid in rail
    assert any(z['osm_graph_node_id']==node and z[direction+'_seconds']==x[field] for z in rail[sid]['entrances'])
  checked+=1
 assert checked==len(fps)
 result['layers'][layer]={'footpaths':len(fps),'all_witness_continuity_and_costs_checked':True,'unique_ordered_pairs':len(pairs)}
# Independent SciPy directed shortest distances for32 deterministic bus sources.
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
ids=sorted(nodes);ni={x:i for i,x in enumerate(ids)};es=list(edges.values());rows=np.array([ni[e['from']] for e in es],dtype=np.int32);cols=np.array([ni[e['to']] for e in es],dtype=np.int32);ws=np.array([e['seconds'] for e in es],dtype=np.int64)
order=np.lexsort((cols,rows));rows=rows[order];cols=cols[order];ws=ws[order];mask=np.r_[True,(rows[1:]!=rows[:-1])|(cols[1:]!=cols[:-1])];idx=np.flatnonzero(mask);ws=np.minimum.reduceat(ws,idx);rows=rows[idx];cols=cols[idx];csr=csr_matrix((ws,(rows,cols)),shape=(len(ids),len(ids)))
bss=sorted(bus);sources=[bss[i*len(bss)//32] for i in range(32)];actual=collections.defaultdict(dict)
for p in json.loads(Path('conservative600/footpaths.json').read_text()):actual[p['from']][p['to']]=p['duration']
checked_pairs=0
for sid in sources:
 s=bus[sid];ds=dijkstra(csr,directed=True,indices=ni[s['osm_graph_node_id']],limit=600);expected={}
 for tid,t in bus.items():
  if tid==sid:continue
  duration=ds[ni[t['osm_graph_node_id']]]+max(1,s['connector_seconds'])+max(1,t['connector_seconds'])
  if duration<=600:expected[tid]=int(duration)
 assert actual[sid]==expected,(sid,actual[sid],expected)
 checked_pairs+=len(expected)
result['independent_shortest_path_check']={'implementation':'scipy.sparse.csgraph.dijkstra','source_count':32,'matching_reachable_pairs':checked_pairs,'all3632_targets_tested_for_each_source':True,'directed':True}
result['elapsed_seconds']=time.perf_counter()-start;b.dump('ARTIFACT_VALIDATION.json',result);print(json.dumps(result,indent=2))
