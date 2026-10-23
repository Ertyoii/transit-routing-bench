#!/usr/bin/env python3
"""Freeze small actual-model induced fixtures from metadata only, no router output.

The earliest eligible seed under SHA256(tripID,sequence) is fixed before any
exhaustive/scalar result. Keep every input event and walking edge within the chosen
stop/time submodel; split disconnected retained trip chunks explicitly.
"""
import argparse,copy,hashlib,json,pathlib,collections
p=argparse.ArgumentParser();p.add_argument('--dataset-registry',required=True);p.add_argument('--out-dir',required=True);a=p.parse_args();out=pathlib.Path(a.out_dir);out.mkdir(parents=True,exist_ok=False);registry=json.load(open(a.dataset_registry))['datasets'];manifest={'contract':'induced finite submodels only; no full-network or physical reachability claim','selection':'minimum SHA256([tripID,first sequence]) among all contiguous three-edge segments with four distinct stops, duration<=540s and a complete10min window, independent of router/scalar outcomes','generator_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'fixtures':[]}
for window,path in sorted(registry.items()):
 raw=pathlib.Path(path).read_bytes();d=json.loads(raw);trips={t['id']:t for t in d['trips']};by=collections.defaultdict(list)
 for c in d['connections']:by[c['trip_id']].append(c)
 seeds=[];start=d.get('window',{}).get('start',0);end=d.get('window',{}).get('end',604800)
 for tid,cs in by.items():
  cs.sort(key=lambda c:c['sequence'])
  for i in range(len(cs)-2):
   seg=cs[i:i+3];stops=[seg[0]['from']]+[c['to'] for c in seg];dep=max(start,seg[0]['departure']-60)
   if len(set(stops))==4 and seg[-1]['arrival']<=dep+600<=end:
    key=hashlib.sha256(json.dumps([tid,seg[0]['sequence']],separators=(',',':')).encode()).hexdigest();seeds.append((key,seg,dep))
 assert seeds,'no metadata-eligible induced seed';key,seg,dep=min(seeds,key=lambda x:x[0]);stopids={seg[0]['from']}|{c['to'] for c in seg};stops={s['id']:s for s in d['stops']};base=set(stopids)
 while True:
  parents={stops[s].get('parent_station') for s in stopids if stops[s].get('parent_station')};expanded=stopids|parents
  if expanded==stopids:break
  stopids=expanded
 retained=[c for c in d['connections'] if c['from'] in stopids and c['to'] in stopids and dep<=c['departure'] and c['arrival']<=dep+600];chunks=collections.defaultdict(list)
 for c in retained:chunks[c['trip_id']].append(c)
 newtrips=[];newcs=[]
 for tid,cs in sorted(chunks.items()):
  cs.sort(key=lambda c:c['sequence']);part=[];parts=[]
  for c in cs:
   if part and c['sequence']!=part[-1]['sequence']+1:parts.append(part);part=[]
   part.append(c)
  if part:parts.append(part)
  for i,part in enumerate(parts):
   t=copy.deepcopy(trips[tid]);t['source_id']=t.get('source_id') or tid;t['id']=tid+f'|induced_chunk{i}';newtrips.append(t)
   for seq,c in enumerate(part):c=copy.deepcopy(c);c['trip_id']=t['id'];c['sequence']=seq;newcs.append(c)
 sourceids={t['source_id'] for t in newtrips};routes={t.get('route_id','') for t in newtrips};rules=[]
 for r in d.get('transfers',[]):
  if r['from_stop'] not in stopids or r['to_stop'] not in stopids:continue
  if any(r.get(k) and r[k] not in sourceids for k in ['from_trip','to_trip']):continue
  if any(r.get(k) and r[k] not in routes for k in ['from_route','to_route']):continue
  rules.append(r)
 nd={k:copy.deepcopy(v) for k,v in d.items() if k not in ['id','stops','trips','connections','footpaths','transfers','window']};nd.update(id=window+'|induced10m_fourstop_v2',stops=[stops[i] for i in sorted(stopids)],trips=newtrips,connections=newcs,footpaths=[f for f in d['footpaths'] if f['from'] in stopids and f['to'] in stopids],transfers=rules,window={'start':dep,'end':dep+600})
 origin,dest=seg[0]['from'],seg[-1]['to'];qs=[]
 for label,o,z in [('forward',origin,dest),('reverse',dest,origin),('same',origin,origin)]:qs.append({'id':window+'|induced|'+label,'origin':o,'destination':z,'departure':dep,'latest_arrival':dep+600,'max_walk_seconds':1200,'max_boardings':2,'max_legs':5,'transfer_buffer':0,'accessible_only':False,'walking_limits':{'access_seconds':600,'direct_seconds':600,'egress_seconds':600,'transfer_seconds':600}})
 bundle={'dataset':nd,'queries':qs};p=out/f'{window}.json';p.write_text(json.dumps(bundle,sort_keys=True,indent=2)+'\n');manifest['fixtures'].append({'window':window,'file':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source_dataset_sha256':hashlib.sha256(raw).hexdigest(),'seed_sha256':key,'seed_connection_ids':[c['id'] for c in seg],'stops':len(nd['stops']),'connections':len(newcs),'footpaths':len(nd['footpaths']),'queries':len(qs)})
(out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n');print(json.dumps(manifest,indent=2))
