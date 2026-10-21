#!/usr/bin/env python3
"""Bounded single-source shortest paths; stop-pair closures with full OSM edge witnesses.
Graph is directed and integer costs match walking/osm.Load exactly. Connector assumptions
remain separate. Source limits produce explicit partial closures, never full coverage claims.
"""
import argparse,collections,hashlib,heapq,json,math,time
from pathlib import Path
import build_walk as b

def run(limit,cap,out):
 started=time.perf_counter();g=json.loads(Path('osm-pedestrian-graph.json').read_text());bindingdoc=json.loads(Path('stop-bindings.json').read_text());bs=bindingdoc['bindings'];bs.sort(key=lambda r:r['transit_stop_id'])
 ids=[n['id'] for n in g['nodes']];ni={x:i for i,x in enumerate(ids)};adj=[[] for _ in ids]
 for ei,e in enumerate(g['edges']):adj[ni[e['from']]].append((ni[e['to']],e['seconds'],ei))
 for es in adj:es.sort(key=lambda a:(a[0],a[1],a[2]))
 targets=collections.defaultdict(list)
 for x in bs:targets[ni[x['osm_graph_node_id']]].append(x)
 sources=bs if not limit or limit>=len(bs) else [bs[i*len(bs)//limit] for i in range(limit)]
 paths=[];metrics=[];out=Path(out);out.mkdir(exist_ok=True);wf=open(out/'path-witnesses.jsonl','w');witness_hash=hashlib.sha256();graphsha=b.sha('osm-pedestrian-graph.json');bindsha=b.sha('stop-bindings.json')
 total_settled=total_visits=0
 for count,s in enumerate(sources):
  t=time.perf_counter();src=ni[s['osm_graph_node_id']];sc=max(1,s['connector_seconds']);d={src:sc};prev={};q=[(sc,src)];settled=visits=0;found=0
  while q:
   du,u=heapq.heappop(q)
   if du!=d[u]:continue
   if du>cap:break
   settled+=1
   for z in targets.get(u,[]):
    sid,zid=s['transit_stop_id'],z['transit_stop_id'];duration=du+max(1,z['connector_seconds'])
    if sid==zid or duration>cap:continue
    nodes=[];edge_ids=[];at=u
    while at!=src:
     before,ei=prev[at];edge_ids.append(g['edges'][ei]['id']);nodes.append(ids[at]);at=before
    edge_ids.reverse();nodes.append(ids[src]);nodes.reverse()
    fid=f'osmwalk{cap}:{sid}:{zid}'
    p={'id':fid,'from':sid,'to':zid,'duration':duration,'accessible':'unknown','provenance':f'OSM-walk:{graphsha};bindings:{bindsha};source:{g["source_sha256"]};assumed-stop-connectors;ODbL-1.0'}
    paths.append(p)
    witness={'footpath_id':fid,'from':sid,'to':zid,'duration':duration,'osm_path_seconds':du-sc,'source_connector_seconds':sc,'target_connector_seconds':max(1,z['connector_seconds']),'edge_ids':edge_ids,'osm_node_ids':nodes,'source_binding':s['method'],'target_binding':z['method'],'graph_sha256':graphsha,'bindings_sha256':bindsha,'physical_verification':False}
    raw=json.dumps(witness,sort_keys=True,separators=(',',':'))+'\n';wf.write(raw);witness_hash.update(raw.encode());found+=1
   for v,sec,ei in adj[u]:
    visits+=1;nd=du+sec
    if nd>=cap:continue
    if nd<d.get(v,math.inf):d[v]=nd;prev[v]=(u,ei);heapq.heappush(q,(nd,v))
  elapsed=time.perf_counter()-t;total_settled+=settled;total_visits+=visits
  metrics.append({'source_stop':s['transit_stop_id'],'settled':settled,'edge_visits':visits,'footpaths':found,'elapsed_seconds':elapsed})
  if count%100==0:print('source',count+1,'of',len(sources),'footpaths',len(paths),'elapsed',round(time.perf_counter()-started,2),flush=True)
 wf.close();paths.sort(key=lambda r:r['id']);b.dump(out/'footpaths.json',paths);b.dump(out/'search-metrics.json',metrics)
 stats={'schema':'sg-osm-footpath-closure-v1','permission_policy':b.PROFILE,'max_duration_seconds':cap,'chosen_scope':'identity-matched bus boarding anchors only; conservative mapped pedestrian graph; uncertain barrier-screened short connectors','total_gtfs_stops':len(bs)+len(bindingdoc['unbound']),'bound_stops':len(bs),'source_stops':len(sources),'source_stop_ids':[s['transit_stop_id'] for s in sources],'complete_over_bound_scope':len(sources)==len(bs),'directional':True,'footpaths':len(paths),'source_sha256':g['source_sha256'],'graph_sha256':graphsha,'bindings_sha256':bindsha,'footpaths_sha256':b.sha(out/'footpaths.json'),'witnesses_sha256':witness_hash.hexdigest(),'elapsed_seconds':time.perf_counter()-started,'dijkstra_settled':total_settled,'edge_visits':total_visits,'physical_verification':False,'claims':{'timeless_static_cost_model':True,'OSM_node_topology_witnesses':True,'all_stops_covered':False,'rail_interior_witnessed':False,'wheelchair_accessibility_verified':False,'real_world_verification':False},'limitations':['Conservative scope excludes rail interior/entrance links and bus stops without unique reference match','Endpoint connectors are model assumptions screened against mapped barriers, not actual OSM ways','Per-segment ceil distance/1.4 cost omits stairs slope crossing waits and crowding; not a journey-time forecast','Bounded shortest-path closure may chain into longer walking paths in transit router; query role caps must still be enforced','Input map and GTFS snapshots differ in date; missing map detail and bbox crop cause false negatives','Preserve GTFS proxy transfer layer separately; these walking edges do not reclassify it as observed physical truth']}
 b.dump(out/'closure-manifest.json',stats);print(json.dumps(stats,indent=2),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--limit',type=int,default=32);p.add_argument('--cap',type=int,default=600);p.add_argument('--out',default='sample32');a=p.parse_args();run(a.limit,a.cap,a.out)
