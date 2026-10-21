#!/usr/bin/env python3
"""Deterministic append-only merge to NEW datasets. Never overwrites known-edge inputs.
Default fails on all ID/pair collisions. An explicit --rail-overlap-policy preserve-gtfs
may be used only when authorized: it records and excludes26 duplicate rail-model pairs.
"""
import argparse,copy,hashlib,json,os,time
from pathlib import Path
import build_walk as b
HERE=Path(__file__).resolve().parent

def canonical_sha(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def write_once(path,obj):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 data=(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode();sha=hashlib.sha256(data).hexdigest()
 if path.exists():
  if b.sha(path)!=sha:raise ValueError('Refusing to overwrite a different existing output: '+str(path))
 else:path.write_bytes(data)
 return sha

def run(policy):
 start=time.perf_counter();source_path=HERE/'../data/NORMALIZED_INPUTS.json';source=json.loads(source_path.read_text());outroot=HERE/'../data-enriched'
 con=json.loads((HERE/'conservative600/footpaths.json').read_text());rail=json.loads((HERE/'rail-sensitivity600/footpaths.json').read_text())
 artifact_paths=['SOURCE_QUALIFICATION.json','SOURCE_PROVENANCE.json','ODbL-ATTRIBUTION.txt','osm-pedestrian-graph.json','osm-way-audit.json','stop-bindings.json','stop-connectors.json','rail-sensitivity-bindings.json','conservative600/footpaths.json','conservative600/path-witnesses.jsonl','conservative600/closure-manifest.json','rail-sensitivity600/footpaths.json','rail-sensitivity600/path-witnesses.jsonl','rail-sensitivity600/closure-manifest.json','ARTIFACT_VALIDATION.json']
 artifacts=[{'path':str(HERE/p),'sha256':b.sha(HERE/p)} for p in artifact_paths]
 manifest={'schema':'sg-enriched-normalized-inputs-v1','physical_verification':False,'formal_baseline_eligible':False,'latest_official_transit_feed':False,'source_classification':'PROVISIONAL community2026-07-12 typical-weekday frequency model; not official LTA or certified latest/complete','new_baseline_not_historical_frozenSG':True,'source_normalized_manifest_path':str(source_path.resolve()),'source_normalized_manifest_sha256':b.sha(source_path),'source_artifacts':artifacts,'rail_overlap_policy':policy,'inputs':[],'excluded_inputs':[]}
 for original in source['inputs']:
  src=Path(original['dataset_path'])
  assert b.sha(src)==original['dataset_sha256'],'source hash mismatch'
  if not original['eligible_for_primary_transit_reachability_score']:
   manifest['excluded_inputs'].append({'id':original['id'],'path':str(src),'sha256':original['dataset_sha256'],'reason':'Empty source weekday-only calendar; retain original unsupported/weekend coverage manifest; do not reinterpret as physical unreachability'})
   continue
  d=json.loads(src.read_text());oldid=d['id'];basefp=list(d['footpaths']);basepairs={(p['from'],p['to']):p for p in basefp};baseids={p['id'] for p in basefp}
  unchangedkeys=[k for k in d if k not in {'id','footpaths'}];unchanged={k:canonical_sha(d[k]) for k in unchangedkeys}
  for layer in ['conservative600','rail-sensitivity600']:
   rawdelta=con+(rail if layer=='rail-sensitivity600' else []);delta=[];ids=set(baseids);pairs=set(basepairs);excluded=[]
   for fp in rawdelta:
    if fp['id'] in ids:raise ValueError('Duplicate footpathID: '+fp['id'])
    key=(fp['from'],fp['to'])
    if key in pairs:
     if policy=='preserve-gtfs' and layer=='rail-sensitivity600' and fp['id'].startswith('railmodel600:') and key in basepairs:
      excluded.append({'from':fp['from'],'to':fp['to'],'retained_original':basepairs[key],'excluded_rail_model':fp,'reason':'GTFS proxy is retained; do not silently choose competing modelled interior alternative'})
      continue
     raise ValueError('Conflicting ordered stop pair: '+str(key))
    ids.add(fp['id']);pairs.add(key);delta.append(fp)
   delta.sort(key=lambda p:p['id']);delta_hash=canonical_sha(delta);d['id']=oldid+'+'+layer+'-v1-'+delta_hash[:12];d['footpaths']=basefp+delta
   for k in unchangedkeys:assert canonical_sha(d[k])==unchanged[k],k+' changed'
   assert d['footpaths'][:len(basefp)]==basefp
   target=outroot/layer/original['id']/'dataset.json';datasetsha=write_once(target,d)
   applied=outroot/layer/'applied-footpath-delta.json';appliedsha=write_once(applied,delta)
   exclusionpath=outroot/layer/'excluded-overlapping-rail-model-pairs.json';exclusionsha=write_once(exclusionpath,excluded)
   entry={'id':original['id'],'walking_variant':layer,'dataset_id':d['id'],'dataset_path':str(target.resolve()),'dataset_sha256':datasetsha,'dataset_bytes':target.stat().st_size,'original_dataset_path':str(src),'original_dataset_sha256':original['dataset_sha256'],'applied_delta_path':str(applied.resolve()),'applied_delta_sha256':appliedsha,'applied_delta_semantic_sha256':delta_hash,'applied_delta_count':len(delta),'excluded_overlap_count':len(excluded),'excluded_overlap_path':str(exclusionpath.resolve()),'excluded_overlap_sha256':exclusionsha,'unchanged_fields_semantic_sha256':unchanged,'preserved_original_footpaths':len(basefp),'counts':{k:len(d.get(k,[])) for k in ['stops','trips','connections','footpaths','transfers']},'original_footpaths_prefix_unchanged':True,'query_departures_start':original['query_departures_start'],'query_departures_end_exclusive':original['query_departures_end_exclusive'],'query_arrival_horizon_seconds':original['query_arrival_horizon_seconds'],'eligible_for_primary_transit_reachability_score':False,'eligible_for_provisional_model_score':True,'formal_baseline_eligible':False,'latest_official_transit_feed':False,'unsupported_conservative_stop_anchors':1818,'walking_coverage_is_not_physical_reachability':True}
   write_once(target.parent/'merge-audit.json',entry);manifest['inputs'].append(entry);print(layer,original['id'],entry['counts'],'sha256',datasetsha,flush=True)
 write_once(outroot/'NORMALIZED_INPUTS.json',manifest);print('done elapsed',time.perf_counter()-start,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--rail-overlap-policy',choices=['error','preserve-gtfs'],default='error');a=p.parse_args();os.chdir(HERE);run(a.rail_overlap_policy)
