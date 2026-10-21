#!/usr/bin/env python3
"""Only footpaths touching modelled rail boarding anchors; not the conservative layer."""
import collections,hashlib,heapq,json,math,time
from pathlib import Path
import build_walk as b

def run():
 t0=time.perf_counter();g=json.loads(Path('osm-pedestrian-graph.json').read_text());bus=json.loads(Path('stop-bindings.json').read_text())['bindings'];rail=json.loads(Path('rail-sensitivity-bindings.json').read_text())['bindings'];cap=600
 ids=[n['id'] for n in g['nodes']];ix={n:i for i,n in enumerate(ids)};adj=[[] for _ in ids]
 for ei,e in enumerate(g['edges']):adj[ix[e['from']]].append((ix[e['to']],e['seconds'],ei))
 for es in adj:es.sort()
 bindings={};targets=collections.defaultdict(list)
 for x in bus:
  sid=x['transit_stop_id'];sec=max(1,x['connector_seconds']);n=ix[x['osm_graph_node_id']];bindings[sid]={'rail':False,'entry':[(n,sec,x['method'])],'exit':[(n,sec,x['method'])]}
 for x in rail:
  ent=[];ext=[]
  for e in x['entrances']:
   n=ix[e['osm_graph_node_id']]
   if e['entry_seconds'] is not None:ent.append((n,e['entry_seconds'],'MODELLED_station_interior_120s_entry'))
   if e['exit_seconds'] is not None:ext.append((n,e['exit_seconds'],'MODELLED_station_interior_90s_exit'))
  bindings[x['transit_stop_id']]={'rail':True,'entry':sorted(ent),'exit':sorted(ext)}
 for sid,x in bindings.items():
  for n,c,method in x['entry']:targets[n].append((sid,c,method))
 paths=[];stats=[];out=Path('rail-sensitivity600');out.mkdir(exist_ok=True);wf=open(out/'path-witnesses.jsonl','w');gh=b.sha('osm-pedestrian-graph.json');bh=b.sha('stop-bindings.json');rh=b.sha('rail-sensitivity-bindings.json')
 for count,(sid,s) in enumerate(sorted(bindings.items())):
  start=time.perf_counter();d={};prev={};root={};q=[];sourcecost={};sourcemethod={}
  for n,c,method in s['exit']:
   if c<d.get(n,math.inf):d[n]=c;root[n]=n;sourcecost[n]=c;sourcemethod[n]=method;heapq.heappush(q,(c,n))
  best={};settled=visits=0
  while q:
   du,u=heapq.heappop(q)
   if d[u]!=du:continue
   if du>=cap:break
   settled+=1
   for zid,tc,method in targets.get(u,[]):
    if zid==sid or (not s['rail'] and not bindings[zid]['rail']):continue
    dur=du+tc
    if dur>cap:continue
    candidate=(dur,u,tc,method)
    if candidate<best.get(zid,(math.inf,0,0,'')):best[zid]=candidate
   for v,c,ei in adj[u]:
    visits+=1;nd=du+c
    if nd>=cap:continue
    if nd<d.get(v,math.inf):d[v]=nd;prev[v]=(u,ei);root[v]=root[u];heapq.heappush(q,(nd,v))
  for zid,(duration,u,tc,tm) in sorted(best.items()):
   at=u;seed=root[u];eids=[];nodes=[ids[u]]
   while at!=seed:
    prevnode,ei=prev[at];eids.append(g['edges'][ei]['id']);at=prevnode;nodes.append(ids[at])
   eids.reverse();nodes.reverse();sc=sourcecost[seed];fid=f'railmodel600:{sid}:{zid}'
   paths.append({'id':fid,'from':sid,'to':zid,'duration':duration,'accessible':'unknown','provenance':f'MODELLED-RAIL-INTERIOR:120s-entry:90s-exit;OSM-walk:{gh};bus-bindings:{bh};rail-bindings:{rh};ODbL-1.0'})
   wf.write(json.dumps({'footpath_id':fid,'from':sid,'to':zid,'duration':duration,'osm_path_seconds':duration-sc-tc,'source_connector_seconds':sc,'target_connector_seconds':tc,'source_method':sourcemethod[seed],'target_method':tm,'osm_node_ids':nodes,'edge_ids':eids,'graph_sha256':gh,'bus_bindings_sha256':bh,'rail_sensitivity_sha256':rh,'physical_verification':False,'station_interior_modelled_not_witnessed':True},separators=(',',':'),sort_keys=True)+'\n')
  stats.append({'source_stop':sid,'settled':settled,'edge_visits':visits,'additional_rail_footpaths':len(best),'elapsed_seconds':time.perf_counter()-start})
  if count%500==0:print('source',count+1,'of',len(bindings),'additional',len(paths),'elapsed',round(time.perf_counter()-t0,2),flush=True)
 wf.close();paths.sort(key=lambda p:p['id']);b.dump(out/'footpaths.json',paths);b.dump(out/'search-metrics.json',stats)
 summary={'schema':'sg-modelled-rail-footpath-sensitivity-v1','separate_from_conservative_layer':True,'physical_verification':False,'station_interior_modelled_not_witnessed':True,'entry_hypothesis_seconds':120,'exit_hypothesis_seconds':90,'max_duration_seconds':cap,'rail_bound_stops':len(rail),'bus_bound_stops':len(bus),'all_source_stops':len(bindings),'source_stops_with_exit':sum(bool(x['exit']) for x in bindings.values()),'footpaths':len(paths),'bus_to_rail':sum(not bindings[x['from']]['rail'] and bindings[x['to']]['rail'] for x in paths),'rail_to_bus':sum(bindings[x['from']]['rail'] and not bindings[x['to']]['rail'] for x in paths),'rail_to_rail':sum(bindings[x['from']]['rail'] and bindings[x['to']]['rail'] for x in paths),'complete_over_chosen_scope':True,'chosen_scope':'All<=600s directed pair shortest paths touching the61 supported modelled rail stops;3632 bus anchor supports reused; no unnamed entrance association','graph_sha256':gh,'bus_bindings_sha256':bh,'rail_sensitivity_bindings_sha256':rh,'footpaths_sha256':b.sha(out/'footpaths.json'),'witnesses_sha256':b.sha(out/'path-witnesses.jsonl'),'elapsed_seconds':time.perf_counter()-t0,'limitations':['Not a physical-verified or measured rail transfer layer','Station-interior fixed120sentry90sexit is an explicit hypothesis, not an OSM path','Only named or stop-area-associated mapped ground entrances already on graph; unnamed proximity-only station associations excluded','Supports61 line-specific rail stops only;155 other railplatform stops plus29 parentstations excluded','OSM footway witnesses cover street portion only; maps and barriers may be incomplete','Do not compare with conservative results as if assumptions were identical; run separate sensitivity eval']}
 b.dump(out/'closure-manifest.json',summary);print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':run()
