#!/usr/bin/env python3
"""Deterministic OSM walking graph + explicit uncertain GTFS stop connectors.
No claim of ground truth, safe crossing, station interior, accessibility or completeness.
"""
import argparse, collections, csv, hashlib, json, math, os, pickle, re, time, zipfile
from pathlib import Path
import osmium

BBOX=(1.13,103.58,1.49,104.10)  # minlat,minlon,maxlat,maxlon; not a national border
PROFILE='sg-conservative-mapped-pedestrian-v1'
POS={'yes','designated','official','permissive'}
FOOTWAYS={'footway','pedestrian','path','steps','corridor'}
SOURCE='malaysia-singapore-brunei-261019.osm.pbf'
ATTR='© OpenStreetMap contributors; ODbL 1.0; https://www.openstreetmap.org/copyright; extract by Geofabrik'
M=111195.0802335329
X=M*math.cos(math.radians(1.3))

def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def dump(path,obj):
 Path(path).write_text(json.dumps(obj,separators=(',',':'),sort_keys=True,ensure_ascii=False)+'\n')
def xy(lat,lon):return (lon*X,lat*M)
def dist(a,b):
 p1,p2=map(math.radians,(a[0],b[0]));dl=math.radians(b[1]-a[1]);dp=p2-p1
 z=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
 return 6371008.8*2*math.asin(min(1,math.sqrt(z)))
def cost(m):return max(1,math.ceil(m/1.4))
def denied(t):
 if t.get('foot') in POS:return False
 return t.get('foot','yes') not in POS or t.get('access','yes') not in POS

def policy(t):
 """Return directed forward/reverse availability and reason. Reject ambiguity."""
 h=t.get('highway','')
 if not (h in FOOTWAYS or (h in {'cycleway','residential','living_street','unclassified','service','track','primary','secondary','tertiary','trunk','primary_link','secondary_link','tertiary_link'} and t.get('foot') in POS) or t.get('railway')=='platform'):
  return False,False,'not_mapped_pedestrian_or_explicit_foot'
 if t.get('area')=='yes':return False,False,'pedestrian_area_no_interior_routing'
 if t.get('foot')=='use_sidepath' or t.get('sidewalk')=='separate':return False,False,'use_separate_sidewalk'
 if denied(t):return False,False,'restricted_access'
 if t.get('construction') or t.get('proposed') or h in {'construction','proposed'}:return False,False,'construction_or_proposed'
 if t.get('highway')=='elevator' or t.get('conveying','no')!='no':return False,False,'dynamic_vertical_transport'
 if t.get('ford') not in (None,'no') or t.get('highway')=='ford':return False,False,'ford'
 if t.get('opening_hours') not in (None,'24/7'):return False,False,'opening_hours_not_timeless'
 if any(k.endswith(':conditional') and (k.startswith('foot') or k.startswith('access') or k.startswith('oneway')) for k in t):return False,False,'conditional_access_or_direction'
 oneway=t.get('oneway:foot','no')
 if oneway not in {'yes','1','true','-1','no','0','false'}:return False,False,'unknown_foot_oneway'
 # Vehicle oneway does not constrain walking on streets. Ambiguous pedestrian-only oneway excluded.
 if h in FOOTWAYS and 'oneway:foot' not in t and t.get('oneway') in {'yes','1','true','-1'}:
  return False,False,'ambiguous_pedestrian_oneway'
 f=oneway not in {'-1'} and t.get('foot:forward','yes') in POS
 r=oneway not in {'yes','1','true'} and t.get('foot:backward','yes') in POS
 return f,r,'allowed'

def node_allowed(t):
 if denied(t):return False
 if t.get('locked')=='yes':return False
 b=t.get('barrier')
 if b and b not in {'no','bollard','cycle_barrier','entrance'} and t.get('foot') not in POS:return False
 if t.get('opening_hours') not in (None,'24/7'):return False
 if any(k.endswith(':conditional') and (k.startswith('foot') or k.startswith('access')) for k in t):return False
 return True

class Extract(osmium.SimpleHandler):
 def __init__(self):
  super().__init__();self.coords={};self.tags={};self.ways=[];self.blocks=[];self.stats=collections.Counter();self.relations=[]
 def node(self,n):
  a,b=n.location.lat,n.location.lon
  if BBOX[0]<=a<=BBOX[2] and BBOX[1]<=b<=BBOX[3]:
   self.coords[n.id]=(a,b)
   if len(n.tags):self.tags[n.id]=dict(n.tags)
 def way(self,w):
  ts=dict(w.tags);ids=[n.ref for n in w.nodes]
  if not any(i in self.coords for i in ids):return
  self.stats['ways_touching_bbox']+=1
  inside=all(i in self.coords for i in ids)
  if not inside:self.stats['ways_cropped_at_bbox']+=1
  f,r,why=policy(ts);self.stats['policy_'+why]+=1
  if (f or r):
   self.ways.append((w.id,ids,ts,f,r))
  # All mapped linear barriers + road/rail/water + building/water areas screen connectors.
  kind=None
  if ts.get('barrier') not in (None,'no','entrance'):kind='barrier'
  elif ts.get('waterway') in {'river','stream','canal','drain','ditch'}:kind='waterway'
  elif ts.get('natural') in {'water','wetland','coastline'} or ts.get('water'):kind='water'
  elif ts.get('building') not in (None,'no'):kind='building'
  elif ts.get('railway') in {'rail','light_rail','subway','monorail','tram'}:kind='rail'
  elif ts.get('highway') not in (None,'footway','pedestrian','path','steps','corridor','cycleway','platform'):
   if ts.get('highway') not in {'bus_stop','crossing','traffic_signals'}:kind='road'
  if kind and inside and len(ids)>1:self.blocks.append((w.id,ids,ts,kind))
 def relation(self,r):
  t=dict(r.tags)
  if t.get('type')=='restriction' and ('restriction:foot' in t or 'foot' in t.get('restriction','')):
   self.relations.append({'id':r.id,'tags':t,'members':[(m.type,m.ref,m.role) for m in r.members]})

def parse():
 t=time.time();h=Extract();h.apply_file(SOURCE)
 print('parsed',len(h.coords),'bbox nodes',len(h.ways),'walking ways',len(h.blocks),'blocker ways',time.time()-t,flush=True)
 edges=[];used=set();node_kinds=collections.defaultdict(set);node_grade=collections.defaultdict(set);waymeta=[]
 # foot restriction relations cannot be represented in node-based provider: conservatively exclude their from/to ways.
 restricted_ways={m[1] for r in h.relations for m in r['members'] if m[0]=='w' and m[2] in {'from','to','via'}}
 for wid,ids,ts,f,r in sorted(h.ways):
  if wid in restricted_ways:h.stats['foot_restriction_way_excluded']+=1;continue
  waymeta.append({'way_id':wid,'tags':ts,'node_ids':ids,'forward':f,'reverse':r})
  grade=(ts.get('layer','0'),ts.get('level','0'),ts.get('bridge','no'),ts.get('tunnel','no'))
  for idx,(a,b) in enumerate(zip(ids,ids[1:])):
   if a not in h.coords or b not in h.coords or a==b:continue
   if not node_allowed(h.tags.get(a,{})) or not node_allowed(h.tags.get(b,{})):
    h.stats['segments_blocked_by_node']+=1;continue
   metres=round(dist(h.coords[a],h.coords[b]),6);secs=cost(metres)
   for src,dst,direction,ok in [(a,b,'f',f),(b,a,'r',r)]:
    if ok:edges.append({'id':f'way:{wid}:{idx}:{direction}','from':src,'to':dst,'metres':metres,'seconds':secs})
   used.update((a,b))
   for n in (a,b):node_kinds[n].add(ts.get('highway',ts.get('railway','')));node_grade[n].add(grade)
 nodes=[{'id':n,'lat':h.coords[n][0],'lon':h.coords[n][1]} for n in sorted(used)]
 graph={'attribution':ATTR,'permission_policy':PROFILE,'source_sha256':sha(SOURCE),'nodes':nodes,'edges':edges}
 dump('osm-pedestrian-graph.json',graph);dump('osm-way-audit.json',waymeta)
 # This local pickle is generated and consumed by our pipeline only, never ingest an external pickle.
 with open('extracted.pkl','wb') as f:pickle.dump({'coords':h.coords,'tags':h.tags,'blocks':h.blocks,'node_kinds':dict(node_kinds),'node_grade':dict(node_grade),'stats':dict(h.stats),'foot_restrictions':h.relations},f,protocol=5)
 dump('parse-stats.json',dict(h.stats));print('graph',len(nodes),len(edges),'sha256',sha('osm-pedestrian-graph.json'),flush=True)


def make_connectors():
 import numpy as np
 from scipy.spatial import cKDTree
 from shapely.geometry import LineString,Polygon,Point
 from shapely.strtree import STRtree
 t0=time.time();g=json.loads(Path('osm-pedestrian-graph.json').read_text())
 with open('extracted.pkl','rb') as f:h=pickle.load(f)
 tags=h['tags'];coords=h['coords'];gids={n['id'] for n in g['nodes']}
 # Candidate anchors must be non-platform, pedestrian-specific, ground-level graph nodes.
 good=[]
 for n in sorted(gids):
  if not h['node_kinds'][n].intersection(FOOTWAYS):continue
  if not node_allowed(tags.get(n,{})):continue
  grades=h['node_grade'][n]
  if not all(gr[0] in {'0',''} and gr[1] in {'0',''} and gr[2]=='no' and gr[3]=='no' for gr in grades):continue
  if tags.get(n,{}).get('level','0') not in {'0',''} or tags.get(n,{}).get('layer','0') not in {'0',''}:continue
  good.append(n)
 tree=cKDTree(np.array([xy(*coords[n]) for n in good]))
 geoms=[];info=[]
 for wid,ids,ts,kind in h['blocks']:
  # Elevated/underground linework is not a barrier to ground connectors. Ground water/buildings always are.
  if kind not in {'water','building'} and (ts.get('layer','0') not in {'0',''} or ts.get('bridge','no')!='no' or ts.get('tunnel','no')!='no'):continue
  ps=[xy(*coords[n]) for n in ids]
  try:
   shape=Polygon(ps) if len(ps)>3 and ids[0]==ids[-1] and kind in {'water','building'} else LineString(ps)
   if shape.is_empty or not shape.is_valid:continue
  except Exception:continue
  geoms.append(shape);info.append((wid,kind))
 bt=STRtree(geoms)
 def clear(a,b):
  if a==b:return True,[]
  l=LineString([xy(*a),xy(*b)])
  # Trim 0.25m at endpoints, allowing stop mapped on roadside or building edge without permitting through-crossing.
  if l.length>0.5:l=LineString([l.interpolate(0.25),l.interpolate(l.length-0.25)])
  hits=bt.query(l,predicate='intersects')
  return not len(hits),[info[int(i)] for i in hits]
 refs=collections.defaultdict(list);entrances=[];osm_bus=[]
 for n,ts in tags.items():
  if ts.get('highway')=='bus_stop' or ts.get('public_transport')=='platform' and ts.get('bus')=='yes':
   osm_bus.append(n)
   for key in ('ref','local_ref','ref:LTAsg','ref:LTA','bus_stop'):
    for ref in re.split(r'[;, ]+',ts.get(key,'')):
     if re.fullmatch(r'\d{5}',ref):refs[ref].append(n)
  if ts.get('railway')=='subway_entrance' or ts.get('entrance') in {'yes','main'} and ts.get('station') in {'subway','light_rail','train'}:entrances.append(n)
 for key in refs:refs[key]=sorted(set(refs[key]))
 with zipfile.ZipFile('../data/singapore-gtfs-v2026-07-12.zip') as z:
  stops=sorted(csv.DictReader(z.read('stops.txt').decode('utf-8-sig').splitlines()),key=lambda x:x['stop_id'])
 bindings=[];unbound=[];connector_edges=[];stats=collections.Counter();review=[]
 for s in stops:
  sid=s['stop_id'];p=(float(s['stop_lat']),float(s['stop_lon']));isbus=bool(re.fullmatch(r'\d{5}',sid))
  record={'transit_stop_id':sid,'stop_name':s['stop_name'],'gtfs_lat':p[0],'gtfs_lon':p[1],'location_type':int(s.get('location_type') or 0),'parent_station':s.get('parent_station','')}
  if not isbus:
   # Do not fabricate rail boarding-anchor-to-entrance/interior travel.
   nearby=sorted(((round(dist(p,coords[n]),3),n) for n in entrances if dist(p,coords[n])<=500))[:8]
   unbound.append(dict(record,reason='rail_station_interior_or_entrance_not_witnessed',nearby_mapped_entrances=[{'osm_node_id':n,'distance_metres':d,'tags':tags[n]} for d,n in nearby]));stats['rail_unbound']+=1;continue
  candidates=[]
  for n in refs.get(sid,[]):
   d=dist(p,coords[n])
   if d<=75 and node_allowed(tags.get(n,{})):candidates.append((d,n))
  candidates.sort()
  if not candidates:
   unbound.append(dict(record,reason='no_unique_nearby_osm_bus_reference'));stats['bus_no_ref_match']+=1;continue
  if len(candidates)>1 and candidates[1][0]-candidates[0][0]<10:
   unbound.append(dict(record,reason='ambiguous_osm_bus_reference',candidates=candidates));stats['bus_ambiguous_ref']+=1;continue
  delta,n=candidates[0];q=coords[n]
  # GTFS coordinate is metadata only; anchor is the identity-matched OSM bus stop, not an off-network straight line from GTFS.
  target=None;blocked=[]
  if n in gids:target=n;kind='identity_matched_existing_graph_node';metres=0
  else:
   ds,ix=tree.query(xy(*q),k=32,distance_upper_bound=25)
   for d,i in sorted(zip(np.atleast_1d(ds),np.atleast_1d(ix)),key=lambda a:(float(a[0]),int(a[1]))):
    if not math.isfinite(float(d)):continue
    v=good[int(i)];actual=dist(q,coords[v])
    if actual>25:continue
    ok,hits=clear(q,coords[v])
    if ok:target=v;kind='assumed_short_barrier_screened_ground_connector';metres=round(actual,6);break
    blocked.extend(hits)
  if target is None:
   unbound.append(dict(record,reason='no_barrier_screened_pedestrian_node_within_25m',osm_bus_node_id=n,gtfs_offset_metres=round(delta,3),blocking_features=sorted(set(blocked))[:10]));stats['bus_connector_rejected']+=1;continue
  seconds=0 if n==target else cost(metres)
  nodeid='gtfs:'+sid
  binding=dict(record,provider_node_id=nodeid,osm_bus_node_id=n,osm_graph_node_id=target,anchor_lat=q[0],anchor_lon=q[1],gtfs_offset_metres=round(delta,3),connector_metres=metres,connector_seconds=seconds,method=kind,osm_bus_tags=tags[n],accessible='unknown',uncertainty=['OSM identity, map tags and footway topology are not independently surveyed','Boarding location and side-of-road equivalence are assumed from bus ref','Unmapped barriers, closed paths and access restrictions may exist']+(['Straight short access segment is an explicit model assumption, not an OSM path'] if seconds else []))
  bindings.append(binding);stats[kind]+=1
  # Positive-cost interface even when sharing the OSM node, for model.Footpath consistency. 1 sec is a declared boarding-anchor connector cost.
  c=max(1,seconds)
  connector_edges.extend([{'id':f'connector:{sid}:out','from':nodeid,'to':str(target),'seconds':c,'metres':metres,'method':kind},{'id':f'connector:{sid}:in','from':str(target),'to':nodeid,'seconds':c,'metres':metres,'method':kind}])
 dump('stop-bindings.json',{'schema':'sg-explicit-stop-bindings-v1','permission_policy':PROFILE,'graph_sha256':sha('osm-pedestrian-graph.json'),'gtfs_sha256':sha('../data/singapore-gtfs-v2026-07-12.zip'),'bindings':bindings,'unbound':unbound,'limitations':['Not walking/transit.Bindings: separate artifact for explicit boarding-anchor connectors; provider node IDs are gtfs:<stop_id>','Only bus refs uniquely matched within75m; short connectors<=25m screen mapped blockers but are uncertain','Rail stop central points are not entrances: no fabricated interior access; all rail unbound in conservative scope','Candidate nearest nodes must be pedestrian-specific and mapped ground-level; no road-center nearest-node snap','BBox is a processing window, not Singapore border; paths touching boundary can be missing','Source GTFS is July2026; OSM is October2026; temporal mismatch retained']})
 dump('stop-connectors.json',{'schema':'sg-stop-connectors-v1','attribution':ATTR,'edges':connector_edges});dump('connector-stats.json',{'counts':dict(stats),'graph_nodes':len(gids),'ground_pedestrian_candidates':len(good),'obstacle_features':len(geoms),'mapped_bus_features':len(osm_bus),'mapped_station_entrances':len(entrances),'total_gtfs_stops':len(stops),'bound_stops':len(bindings),'unbound_stops':len(unbound),'elapsed_seconds':round(time.time()-t0,3)})
 print('connectors',dict(stats),'time',time.time()-t0,flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('phase',choices=['parse','connect']);a=p.parse_args()
 if a.phase=='parse':parse()
 else:make_connectors()
