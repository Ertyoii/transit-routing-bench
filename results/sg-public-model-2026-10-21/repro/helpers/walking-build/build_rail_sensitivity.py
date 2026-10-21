#!/usr/bin/env python3
"""A SEPARATE rail-entry sensitivity model. 120s entry / 90s exit are hypotheses.
Never present this artifact as physically verified, measured station access, or conservative layer.
Only mapped subway entrances already present on OSM pedestrian graph are eligible.
"""
import collections,csv,json,pickle,re,zipfile
from pathlib import Path
import build_walk as b

def norm(s):
 s=re.sub(r'\(.*?\)','',s).lower();s=re.sub(r'\b(mrt|lrt|station)\b','',s)
 return re.sub(r'[^a-z0-9]','',s)

def run():
 g=json.loads(Path('osm-pedestrian-graph.json').read_text());gids={n['id'] for n in g['nodes']}
 with open('extracted.pkl','rb') as f:h=pickle.load(f)
 areas=json.loads(Path('transit-stop-areas.json').read_text());coords=h['coords'];tags=h['tags']
 named=collections.defaultdict(set)
 for r in areas:
  name=norm(r['tags'].get('name',''))
  if not name or r['tags'].get('bus')=='yes' or 'bus' in r['tags'].get('name','').lower():continue
  for typ,n,role in r['members']:
   if typ=='n' and tags.get(n,{}).get('railway')=='subway_entrance':named[name].add(n)
 entrances=[]
 for n,t in tags.items():
  if t.get('railway')!='subway_entrance' or n not in gids or not b.node_allowed(t):continue
  if t.get('level','0') not in {'0',''} or t.get('layer','0') not in {'0',''}:continue
  entrances.append(n)
 with zipfile.ZipFile('../data/singapore-gtfs-v2026-07-12.zip') as z:stops=sorted(csv.DictReader(z.read('stops.txt').decode('utf-8-sig').splitlines()),key=lambda s:s['stop_id'])
 out=[];unbound=[];count=collections.Counter()
 for s in stops:
  sid=s['stop_id']
  if sid.isdigit() or int(s.get('location_type') or 0)==1:continue
  p=(float(s['stop_lat']),float(s['stop_lon']));name=norm(s['stop_name']);candidates=[]
  for n in entrances:
   d=b.dist(p,coords[n]);tn=norm(tags[n].get('name',''))
   member=n in named.get(name,set());match=bool(tn and tn.startswith(name) and name)
   if d<=700 and (member or match):candidates.append((d,n,'stop_area_membership' if member else 'entrance_name_match'))

  candidates.sort();chosen=[]
  for d,n,method in candidates[:8]:
   chosen.append({'osm_entrance_node_id':n,'osm_graph_node_id':n,'lat':coords[n][0],'lon':coords[n][1],'association_method':method,'centroid_to_entrance_metres_for_association_only':round(d,3),'entry_seconds':None if tags[n].get('entrance') in {'exit','emergency'} else 120,'exit_seconds':None if tags[n].get('entrance')=='emergency' else 90,'entry_exit_times_are_hypotheses_not_measured':True,'tags':tags[n]})
  if not chosen:
   unbound.append({'transit_stop_id':sid,'stop_name':s['stop_name'],'reason':'no_name_or_relation_associated_ground_entrance_already_in_graph'});continue
  out.append({'transit_stop_id':sid,'provider_node_id':'gtfs:'+sid,'stop_name':s['stop_name'],'gtfs_lat':p[0],'gtfs_lon':p[1],'entrances':chosen,'accessible':'unknown','uncertainty':['Fixed120sentry and90sexit are source hypotheses, not measurements','GTFS platform stop to mapped entrance association does not witness interior path or fare-gate access','Several line-specific stops at same station may share entrances; internal interchange still separately proxy modelled']});count['bound_rail_stops']+=1;count['entrance_bindings']+=len(chosen)
 artifact={'schema':'sg-modelled-rail-entrance-sensitivity-v1','separate_from_conservative_layer':True,'physical_verification':False,'graph_sha256':b.sha('osm-pedestrian-graph.json'),'gtfs_sha256':b.sha('../data/singapore-gtfs-v2026-07-12.zip'),'entry_hypothesis_seconds':120,'exit_hypothesis_seconds':90,'bindings':out,'unbound':unbound,'counts':dict(count),'limitations':['Explicitly modelled station-interior connector sensitivity, not measured or OSM-witnessed interior paths','Only mapped entrances with station-name or stop-area membership association<=700m; unnamed proximity-only associations are excluded','No centroid-to-road or straight-line station path is fabricated','Entry/exit fixed time omits station depth, line platform position, fares, opening hours, gating and crowding','Parent location_type1 stops are not added as boarding anchors']}
 b.dump('rail-sensitivity-bindings.json',artifact);print(json.dumps(artifact['counts']), 'unbound',len(unbound))
if __name__=='__main__':run()
