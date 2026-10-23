#!/usr/bin/env python3
"""Offline selector quality on fixed native candidate pools; never serving timing."""
import argparse,collections,copy,hashlib,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('replay_eval_v2',ROOT/'analysis/evaluate_v2.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def readlines(p):
 with Path(p).open() as f:
  for s in f:yield json.loads(s)
def compact(v):
 v=dict(v);v['regret_score_seconds']=E.dist(v.pop('regrets',[]));v['normalized_regret']=E.dist(v.pop('normalized_regrets',[]));return v

def run(manifest_dir,probe_root,probe,out):
 global E
 out.mkdir(parents=True,exist_ok=False);manifest_dir=Path(manifest_dir);probe_root=Path(probe_root);manifest=E.read(manifest_dir/'MANIFEST.json')
 implementation=manifest.get('evaluator_implementation')
 if implementation:
  if E.sha(implementation['path'])!=implementation['sha256']:raise ValueError('authoritative evaluator implementation changed')
  spec=importlib.util.spec_from_file_location('selector_replay_authoritative',implementation['path']);E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
 for name,digest in manifest['outputs'].items():
  if E.sha(manifest_dir/name)!=digest:raise ValueError('replay manifest output hash mismatch: '+name)
 matrix=E.read(probe_root/'OFFLINE_POLICY_MATRIX.json');origin=E.read(probe_root/'OFFLINE_ORIGIN.json');expected_build=(probe_root/'PROBE_SOURCE_SHA256.txt').read_text().strip()
 if E.sha(probe_root/'OFFLINE_POLICY_MATRIX.json')!=origin['policy_matrix_sha256']:raise ValueError('offline matrix origin binding mismatch')
 if E.sha(probe_root/'vendor/github.com/ertyoii/transit-routing-go/recommend/offline_wrapper_test.go')!=origin['wrapper_test_sha256']:raise ValueError('offline wrapper tests changed')
 if E.sha(probe_root/'vendor/github.com/ertyoii/transit-routing-go/recommend/offline_wrapper.go')!=origin['wrapper_sha256'] or E.sha(probe_root/'cmd/offlinefeatureprobe/main.go')!=origin['main_sha256']:raise ValueError('offline wrapper/CLI origin binding changed')
 if E.sha(probe)!=(probe_root/'PROBE_BINARY_SHA256.txt').read_text().split()[0]:raise ValueError('offline probe binary changed')
 for path in [ROOT/'selector-quality/PREFERENCE_SEAL.json',ROOT/'selector-quality/configs/heldout393.json',ROOT/'selector-quality/configs/scalar9.json',ROOT/'selector-quality/configs/outside_rectangle_stress257.json']:
  if E.sha(path)!=manifest['inputs'].get(str(path)):raise ValueError('replay preference dependency differs from manifest')
 for name,digest in origin['unchanged_recommend_files'].items():
  if E.sha(probe_root/'vendor/github.com/ertyoii/transit-routing-go/recommend'/name)!=digest:raise ValueError('frozen selector implementation changed in offline copy')
 policies=matrix['policies'];held=E.read(ROOT/'selector-quality/configs/heldout393.json');stress=E.read(ROOT/'selector-quality/configs/outside_rectangle_stress257.json');panels={'heldout393':held,'wider_domain_stress257':stress}
 seal=E.read(ROOT/'selector-quality/PREFERENCE_SEAL.json')
 for name,digest in seal['files'].items():
  if E.sha(ROOT/'selector-quality/configs'/name)!=digest:raise ValueError('preference freeze changed')
 members={}
 for m in readlines(manifest_dir/'POOL_MEMBERS.jsonl'):members[(m['dataset_sha256'],m['query_id'],m['identity'])]=m['feature']
 references={(r['dataset_sha256'],r['query_id']):r for r in readlines(manifest_dir/'REFERENCE_POOLS.jsonl')};rows_by_pool=collections.defaultdict(list)
 for row in readlines(manifest_dir/'CANDIDATE_ROWS.jsonl'):rows_by_pool[row['candidate_pool_id']].append(row)
 stderr=(out/'PROBE.stderr.log').open('w');proc=subprocess.Popen([str(probe)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True,bufsize=1);request_count=0;parity_checks=0;parity_cache={};aggregates={};refcache={}
 reductionout=(out/'REDUCTION_POOLS.jsonl').open('w');reduction_seen=set()
 output=(out/'POLICY_POOL_SCORES.jsonl').open('w');parityout=(out/'ORIGINAL_SERVING_PARITY.jsonl').open('w')
 def call(cid,fs,cfg,tag):
  nonlocal request_count
  request_count+=1;rid=f'{request_count}:{cid}:{tag}';proc.stdin.write(json.dumps({'request_id':rid,'features':fs,'config':cfg},separators=(',',':'))+'\n');proc.stdin.flush();line=proc.stdout.readline()
  if not line:raise ValueError('offline probe exited before one reply per request')
  result=json.loads(line)
  if result.get('request_id')!=rid or result.get('build_source_sha256')!=expected_build:raise ValueError('probe reply request/source binding mismatch')
  return result
 def reference_features(key,ids):return [members[(*key,i)] for i in ids]
 def refcost(key,panel,which,family=None):
  ck=(*key,panel,which,family)
  if ck not in refcache:
   ref=references[key];ids=ref['common_semantic_ids'] if which=='common' else ref['leave_donor_family_out'][family]['semantic_ids'];fs=reference_features(key,ids);refcache[ck]=[min(E.cost(f,w) for f in fs) for w in panels[panel]] if fs else None
  return refcache[ck]
 def score(chosen,key,panel,which,family,complete):
  best=refcost(key,panel,which,family);weights=panels[panel]
  if best is None:return {'eligible':0,'reference_empty_or_unavailable':True,'missing':False,'regrets':[],'normalized_regrets':[]}
  if not complete or not chosen:return {'eligible':len(weights),'missing':True,'covered':0,'regrets':[],'normalized_regrets':[]}
  ds=[min(E.cost(f,w) for f in chosen)-b for w,b in zip(weights,best)];rels=[d/(1+b) for d,b in zip(ds,best)]
  return {'eligible':len(weights),'missing':False,'covered':sum(d<=1e-7*max(1,abs(b)) for d,b in zip(ds,best)),'regrets':ds,'normalized_regrets':rels,'counterexample_slots':sum(d< -1e-7 for d in ds),'within30':sum(d<=30+1e-7 for d in ds),'within60':sum(d<=60+1e-7 for d in ds),'within120':sum(d<=120+1e-7 for d in ds),'within1percent':sum(d<=.01+1e-7 for d in rels),'within5percent':sum(d<=.05+1e-7 for d in rels)}
 def accumulate(key,value,available):
  b=aggregates.setdefault(key,{'offered_rows':0,'available_rows':0,'eligible_weight_slots':0,'missing_weight_slots':0,'covered':0,'within30':0,'within60':0,'within120':0,'within1percent':0,'within5percent':0,'scored_weight_slots':0,'signed_regret_sum':0.,'normalized_signed_regret_sum':0.,'max_observed_signed_regret':None,'max_observed_normalized_regret':None,'negative_signed_slots':0})
  b['offered_rows']+=1;b['available_rows']+=available;b['eligible_weight_slots']+=value.get('eligible',0)
  if not available or value.get('missing'):b['missing_weight_slots']+=value.get('eligible',0);return
  for name in ['covered','within30','within60','within120','within1percent','within5percent']:b[name]+=value.get(name,0)
  ds=value.get('regrets',[]);rels=value.get('normalized_regrets',[]);b['scored_weight_slots']+=len(ds);b['signed_regret_sum']+=sum(ds);b['normalized_signed_regret_sum']+=sum(rels);b['negative_signed_slots']+=value.get('counterexample_slots',0)
  if ds:b['max_observed_signed_regret']=max(max(ds),b['max_observed_signed_regret'] if b['max_observed_signed_regret'] is not None else max(ds));b['max_observed_normalized_regret']=max(max(rels),b['max_observed_normalized_regret'] if b['max_observed_normalized_regret'] is not None else max(rels))
 try:
  for pool in readlines(manifest_dir/'CANDIDATE_POOLS.jsonl'):
   cid=pool['candidate_pool_id'];fs=pool['features'];by={f['identity']:f for f in fs};rows=rows_by_pool[cid];key=(pool['dataset_sha256'],pool['query_id']);families=sorted({r['family'] for r in rows})
   # Before any counterfactual is accepted, check every independently successful
   # original emitted selection using its original policy on this exact same C.
   for row in rows:
    if not row['independent_complete']:continue
    for original in row['original_selections']:
     if not original['selection_complete']:continue
     policy=original['policy'];limit=original['limit']
     if policy=='bounded_continuous_regret_v3':cfg=row['requested_preference_config']
     elif policy=='finite_preferences_v2':
      cfg=copy.deepcopy(row['requested_preference_config']);cfg.pop('bounded',None);cfg.update(lean_delivery=True,delivery_policy='finite_preferences_v2',delivery_limits=[limit])
     else:cfg={'max_candidates':1024,'max_subsets':200000,'lean_delivery':True,'delivery_policy':'pattern_anchors_v1','delivery_limits':[limit]}
     pk=(cid,canonical(cfg))
     if pk not in parity_cache:parity_cache[pk]=call(cid,fs,cfg,'original_parity')
     result=parity_cache[pk];selection=next((s for s in result.get('selections') or [] if s['limit']==limit),None);match=bool(result.get('complete') and selection and selection['complete'] and selection['selected']==original['selected_replay_ids']);parity_checks+=1
     parityout.write(json.dumps({'run':row['run'],'query_id':row['query']['id'],'policy':policy,'limit':limit,'match':match},separators=(',',':'))+'\n')
     if not match:raise ValueError('offline exact-source replay differs from original successful emitted selection')
  parityout.flush();(out/'PARITY_GATE.json').write_text(json.dumps({'original_emitted_parity_checks':parity_checks,'all_passed':True,'counterfactual_policies_started':False,'manifest_sha256':E.sha(manifest_dir/'MANIFEST.json')},sort_keys=True,indent=2)+'\n');print(json.dumps({'phase':'original_serving_parity_passed','checks':parity_checks}),flush=True)
  for pool in readlines(manifest_dir/'CANDIDATE_POOLS.jsonl'):
   cid=pool['candidate_pool_id'];fs=pool['features'];by={f['identity']:f for f in fs};rows=rows_by_pool[cid];key=(pool['dataset_sha256'],pool['query_id']);families=sorted({r['family'] for r in rows})
   for policy in policies:
    result=call(cid,fs,policy['config'],policy['id']);reduction=result.get('reduction');reduction_id=None
    if reduction is not None:
     reduction_id=hashlib.sha256(canonical({'candidate_pool_id':cid,'reduction':reduction}).encode()).hexdigest()
     if reduction_id not in reduction_seen:reduction_seen.add(reduction_id);reductionout.write(json.dumps({'reduction_pool_id':reduction_id,'candidate_pool_id':cid,'reduction':reduction},separators=(',',':'))+'\n')
     if policy['config'].get('bounded',{}).get('distinct_patterns') and reduction['complete'] and reduction['retained_patterns']!=reduction['original_patterns']:raise ValueError('distinct-pattern policy lost an original native pattern before applying constraint')
    actual={s['limit']:s for s in result.get('selections') or []};cfg=policy['config'];limits=cfg['bounded']['limits'] if cfg.get('bounded') else cfg.get('delivery_limits',[3]);sets={k:set(actual.get(k,{}).get('selected',[])) for k in limits}
    for limit in limits:
     selection=actual.get(limit);complete=bool(result.get('complete') and selection and selection['complete']);ids=selection.get('selected',[]) if selection else []
     if len(ids)>limit or len(ids)!=len(set(ids)) or any(i not in by for i in ids):raise ValueError('counterfactual selected invalid/duplicate/over-cap identity')
     chosen=[by[i] for i in ids];scores={}
     for panel in panels:
      scores[panel]={'common':score(chosen,key,panel,'common',None,complete),'leave_donor_family_out_signed':{f:score(chosen,key,panel,'lofo',f,complete) for f in families}}
     oracle=[]
     for slot in references[key]['oracle_slots']:
      o={'weight':slot['weight'],'reference_complete':slot['complete'],'reference_found':slot['found'],'selector_complete':complete,'candidate_found':bool(chosen),'status':'reference_unknown'}
      if slot['complete'] and slot['found']:
       if complete and chosen:
        got=min(E.cost(f,slot['weight']) for f in chosen);delta=got-slot['score_seconds'];o.update(status='scored',signed_regret=delta,normalized_signed_regret=delta/(1+slot['score_seconds']))
        if delta< -1e-7:raise ValueError('counterfactual feasible display beats alleged exact scalar reference')
       else:o['status']='display_missing'
      elif slot['complete']:
       o['status']='independent_empty'
       if complete and chosen:raise ValueError('counterfactual display contradicts independent empty reference')
      oracle.append(o)
     record={'candidate_pool_id':cid,'dataset_sha256':key[0],'query_id':key[1],'policy_id':policy['id'],'limit':limit,'selected':ids,'complete':complete,'error':result.get('error'),'details':selection.get('details') if selection else None,'offline_quality_not_serving_latency':True,'native_candidate_count':len(fs),'input_patterns':len({f['route_stop_walk_pattern'] for f in fs}),'reduction_pool_id':reduction_id,'post_reduction_patterns':reduction['retained_patterns'] if reduction and reduction['complete'] else None,'post_reduction_candidates':reduction['retained_candidates'] if reduction and reduction['complete'] else None,'selected_patterns':len({f['route_stop_walk_pattern'] for f in chosen}),'k3_k5_overlap':len(sets.get(3,set())&sets.get(5,set())) if 3 in sets and 5 in sets else None,'nested_constraint_holds':sets.get(3,set())<=sets.get(5,set()) if cfg.get('bounded',{}).get('nested') and 3 in sets and 5 in sets else None,'scores':{p:{'common':compact(v['common']),'leave_donor_family_out_signed':{f:compact(z) for f,z in v['leave_donor_family_out_signed'].items()}} for p,v in scores.items()},'original_scalar_slots':oracle}
     output.write(json.dumps(record,separators=(',',':'))+'\n')
     for row in rows:
      available=bool(row['independent_complete'] and complete)
      for panel in panels:
       for reference,value in [('common',scores[panel]['common']),('leave_donor_family_out_signed',scores[panel]['leave_donor_family_out_signed'][row['family']])]:accumulate((row['variant_id'],row['window'],row['stratum'],policy['id'],limit,panel,reference),value,available)
 finally:
  proc.stdin.close();proc.stdout.close();returncode=proc.wait();stderr.close();output.close();parityout.close();reductionout.close()
 if returncode:raise ValueError('offline probe returned nonzero')
 aggregate=[]
 for key,b in sorted(aggregates.items()):
  variant,window,stratum,policy,limit,panel,reference=key;n=b['eligible_weight_slots'];scored=b['scored_weight_slots'];b.update(coverage_including_unavailable=b['covered']/n if n else None,mean_observed_signed_regret=b['signed_regret_sum']/scored if scored else None,mean_observed_normalized_regret=b['normalized_signed_regret_sum']/scored if scored else None);aggregate.append({'variant_id':variant,'window':window,'stratum':stratum,'policy_id':policy,'limit':limit,'panel':panel,'reference':reference,**b})
 (out/'QUALITY_AGGREGATE.json').write_text(json.dumps(aggregate,sort_keys=True,indent=2)+'\n');report={'schema':'sg-offline-selector-replay-v1','manifest_sha256':E.sha(manifest_dir/'MANIFEST.json'),'matrix_sha256':E.sha(probe_root/'OFFLINE_POLICY_MATRIX.json'),'origin_sha256':E.sha(probe_root/'OFFLINE_ORIGIN.json'),'probe_sha256':E.sha(probe),'probe_source_sha256':expected_build,'helper_sha256':E.sha(__file__),'evaluator_implementation':implementation,'requests':request_count,'original_emitted_parity_checks':parity_checks,'original_emitted_parity_all_passed':True,'policies':len(policies),'reduction_pools':len(reduction_seen),'limitations':['Offline counterfactual quality, never serving timing/startup/RSS.','Joint[3,5] display budget differs from original top3-only serving.','Aggregate means/maxima condition on scored slots; unavailable slots remain missing and lower coverage.','Global p95 is not synthesized from per-pool p95; exact per-profile values are reproducible from selected IDs/pools/sealed weights.','LOFO negatives are incomplete reference deficiency, not better-than-global routing.','Stress257 uses the wider[0,1800]×[0,8] rectangle and includes some in-domain points; no outside-domain guarantee.','Keep nondominated objective/display-budget tradeoffs rather than force one winner; never return all candidates.']};(out/'REPORT.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--probe-root',required=True);p.add_argument('--probe',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.manifest,a.probe_root,a.probe,Path(a.out))
