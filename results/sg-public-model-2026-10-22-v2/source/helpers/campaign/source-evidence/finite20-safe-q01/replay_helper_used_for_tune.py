#!/usr/bin/env python3
"""Source-bound finite20-safe feature qualification/replay, never router timing."""
import argparse,collections,hashlib,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('safe_candidate_evaluator',ROOT/'analysis/evaluate_v2_certified_delivery_finite_safe_staged.py');E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
def lines(path):
 with Path(path).open() as f:
  for line in f:yield json.loads(line)
def write(path,value):Path(path).write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
def compact(value):
 value=dict(value);value['regret_score_seconds']=E.dist(value.pop('regrets',[]));value['normalized_regret']=E.dist(value.pop('normalized_regrets',[]));return value
def math_feature(name,d,t,w):return {'identity':json.dumps([{'kind':'ride','ref':name}],separators=(',',':')),'route_stop_walk_pattern':name,'duration_seconds':d,'metrics':{'arrival':d,'boardings':t+1,'transfers':t,'walking_seconds':w}}
def main():
 p=argparse.ArgumentParser();p.add_argument('--probe-root',required=True,type=Path);p.add_argument('--probe',required=True,type=Path);p.add_argument('--out',required=True,type=Path);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--synthetic',action='store_true');g.add_argument('--manifest',type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 source=(a.probe_root/'SOURCE_SHA256.txt').read_text().strip();origin=E.read(a.probe_root/'FINITE_SAFE_ORIGIN.json');matrix=E.read(a.probe_root/'FINITE_SAFE_MATRIX.json');policies=matrix['policies']
 if len(policies)!=2 or origin['composition_scope']!='safe_only_A_no_fill_source':raise ValueError('unexpected policy count/source scope')
 if E.sha(a.probe_root/'FINITE_SAFE_MATRIX.json')!=origin['policy_matrix_sha256']:raise ValueError('matrix origin mismatch')
 binarysha=E.sha(a.probe);bindings={Path(row.split()[1]).name:row.split()[0] for row in (a.probe_root/'BINARY_SHA256.txt').read_text().splitlines()}
 if binarysha!=bindings.get(a.probe.name):raise ValueError('binary SHA differs from source build evidence')
 if E.sha(ROOT/'analysis/evaluate_v2_certified_delivery_v2.py')!=E.ACCEPTED_CERTIFIED_V2_SHA256:raise ValueError('immutable evaluator dependency changed')
 stderr=(a.out/'PROBE.stderr.log').open('w');proc=subprocess.Popen([str(a.probe.resolve())],cwd=a.probe_root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True,bufsize=1);requests=0
 def call(fs,cfg,tag):
  nonlocal requests
  requests+=1;rid=str(requests)+':'+tag;proc.stdin.write(json.dumps({'request_id':rid,'features':fs,'config':cfg},separators=(',',':'))+'\n');proc.stdin.flush();line=proc.stdout.readline()
  if not line:raise ValueError('probe lost one-response-per-request contract')
  z=json.loads(line)
  if z.get('request_id')!=rid or z.get('build_source_sha256')!=source:raise ValueError('request/source echo mismatch')
  return z
 held=E.read(ROOT/'selector-quality/configs/heldout393.json');stress=E.read(ROOT/'selector-quality/configs/outside_rectangle_stress257.json');panels={'exposed_tune393':held,'wider_domain_stress257':stress};parity=0;raw=[];originals=collections.defaultdict(list);rows_by_pool=collections.defaultdict(list);members={};refs={}
 if a.synthetic:
  pools=[{'candidate_pool_id':'synthetic-empty','query_id':'empty','features':[]},{'candidate_pool_id':'synthetic-one','query_id':'one','features':[math_feature('a',100,0,0)]},{'candidate_pool_id':'synthetic-interior','query_id':'interior','features':[math_feature('a',1900,0,300),math_feature('b',1600,2,0),math_feature('c',2500,0,0),math_feature('r',1800,1,100)]}];manifest=None
 else:
  manifest=E.read(a.manifest/'MANIFEST.json')
  for name,h in manifest['outputs'].items():
   if E.sha(a.manifest/name)!=h:raise ValueError('manifest hash mismatch: '+name)
  pools=list(lines(a.manifest/'CANDIDATE_POOLS.jsonl'))
  for row in lines(a.manifest/'CANDIDATE_ROWS.jsonl'):
   rows_by_pool[row['candidate_pool_id']].append(row)
   if row['independent_complete']:
    for s in row['original_selections']:
     if s['policy']=='finite_preferences_v2' and s['limit']==3 and s['selection_complete']:originals[row['candidate_pool_id']].append(s['selected_replay_ids'])
  for z in lines(a.manifest/'POOL_MEMBERS.jsonl'):members[(z['dataset_sha256'],z['query_id'],z['identity'])]=z['feature']
  refs={(z['dataset_sha256'],z['query_id']):z for z in lines(a.manifest/'REFERENCE_POOLS.jsonl')}
 rawfile=(a.out/'RAW_RESULTS.jsonl').open('w');auditfile=(a.out/'INDEPENDENT_CONSTRAINTS.jsonl').open('w')
 try:
  # Whole-cohort baseline parity is a gate. No heldout/stress score is accepted
  # until every output's baseline and20 constraints has independently passed.
  for pool in pools:
   fs=pool['features'];final=[{'identity':f['identity'],'pattern':f['route_stop_walk_pattern'],'duration_seconds':f['duration_seconds'],'metrics':f['metrics']} for f in fs]
   for policy in policies:
    reply=call(fs,policy['feature_config'],pool['candidate_pool_id']+':'+policy['id']);result=reply.get('result')
    if reply.get('error') or not isinstance(result,dict) or result.get('complete') is not True:raise ValueError('preregistered current pool safe policy incomplete: '+json.dumps(reply))
    row={'query':{'id':pool['query_id']},'final':final,'recommendation_quality':{'policy':result['policy'],'finite20_safe_choices':result,'selections':[]}}
    rawfile.write(json.dumps({'candidate_pool_id':pool['candidate_pool_id'],'policy_id':policy['id'],'reply':reply},separators=(',',':'))+'\n');rawfile.flush()
    audit=E.validate_finite_safe_constraints(row,policy['config'],3,final)
    for expected in originals[pool['candidate_pool_id']]:
     parity+=1
     if expected!=result['baseline']['selected']:raise ValueError('new safe baseline differs from original finite20 emission')
    auditfile.write(json.dumps({'candidate_pool_id':pool['candidate_pool_id'],'policy_id':policy['id'],**audit},separators=(',',':'))+'\n');raw.append((pool,policy,result))
  rawfile.flush();auditfile.flush();write(a.out/'BASELINE_PARITY_GATE.json',{'all_passed':True,'independent_constraint_checks':len(raw),'original_emitted_finite20_parity_checks':parity,'scoring_started':False})
  if a.synthetic:
   # Invalid known-profile contract must fail without an implicit baseline answer.
   bad=json.loads(json.dumps(policies[0]['feature_config']));bad['baseline']['groups'][0]['preferences'][0]['transfer_seconds']=1;z=call([],bad,'changed_historical20')
   if not z.get('error') or z.get('result') is not None:raise ValueError('changed profile was accepted')
  else:
   output=(a.out/'POLICY_POOL_SCORES.jsonl').open('w');buckets={};refcache={}
   def ref_features(key,ids):return [members[(*key,i)] for i in ids]
   def accumulate(key,value,available):
    b=buckets.setdefault(key,{'offered_rows':0,'available_rows':0,'eligible_weight_slots':0,'missing_weight_slots':0,'covered':0,'within30':0,'within60':0,'within120':0,'within1percent':0,'within5percent':0,'scored_weight_slots':0,'regret_sum':0.,'normalized_regret_sum':0.,'max_regret':None,'max_normalized_regret':None,'negative_signed_slots':0});b['offered_rows']+=1;b['available_rows']+=bool(available);b['eligible_weight_slots']+=value.get('eligible',0)
    if not available or value.get('missing'):b['missing_weight_slots']+=value.get('eligible',0);return
    for name in ['covered','within30','within60','within120','within1percent','within5percent']:b[name]+=value.get(name,0)
    ds=value.get('regrets',[]);rs=value.get('normalized_regrets',[]);b['scored_weight_slots']+=len(ds);b['regret_sum']+=sum(ds);b['normalized_regret_sum']+=sum(rs);b['negative_signed_slots']+=value.get('counterexample_slots',0)
    if ds:b['max_regret']=max(max(ds),b['max_regret'] if b['max_regret'] is not None else max(ds));b['max_normalized_regret']=max(max(rs),b['max_normalized_regret'] if b['max_normalized_regret'] is not None else max(rs))
   for pool,policy,result in raw:
    key=(pool['dataset_sha256'],pool['query_id']);ref=refs[key];by={f['identity']:f for f in pool['features']};chosen=[by[i] for i in result['selection']['selected']];mapped=rows_by_pool[pool['candidate_pool_id']];families=sorted({r['family'] for r in mapped});scores={}
    for panel,weights in panels.items():
     common=E.score_stage(chosen,ref_features(key,ref['common_semantic_ids']),weights,True);lofo={f:E.score_stage(chosen,ref_features(key,ref['leave_donor_family_out'][f]['semantic_ids']),weights,True) for f in families};scores[panel]={'common':common,'leave_donor_family_out_signed':lofo}
    oracle=[]
    for slot in ref['oracle_slots']:
     entry={'weight':slot['weight'],'reference_complete':slot['complete'],'reference_found':slot['found'],'status':'reference_unknown'}
     if slot['complete'] and slot['found']:
      if chosen:
       delta=min(E.cost(f,slot['weight']) for f in chosen)-slot['score_seconds'];entry.update(status='scored',signed_regret=delta)
       if delta< -1e-7:raise ValueError('candidate contradicts exact scalar reference')
      else:entry['status']='display_missing'
     elif slot['complete']:
      entry['status']='independent_empty'
      if chosen:raise ValueError('candidate contradicts independent empty')
     oracle.append(entry)
    output.write(json.dumps({'candidate_pool_id':pool['candidate_pool_id'],'policy_id':policy['id'],'limit':3,'selected':result['selection']['selected'],'complete':True,'original_scalar_slots':oracle,'scores':{p:{'common':compact(v['common']),'leave_donor_family_out_signed':{f:compact(z) for f,z in v['leave_donor_family_out_signed'].items()}} for p,v in scores.items()}},separators=(',',':'))+'\n')
    for row in mapped:
     for panel in panels:
      for reference,value in [('common',scores[panel]['common']),('leave_donor_family_out_signed',scores[panel]['leave_donor_family_out_signed'][row['family']])]:accumulate((row['variant_id'],row['window'],row['stratum'],policy['id'],panel,reference),value,row['independent_complete'])
   output.close();aggregate=[]
   for key,b in sorted(buckets.items()):
    variant,window,stratum,policy,panel,reference=key;n=b['eligible_weight_slots'];scored=b['scored_weight_slots'];aggregate.append({'variant_id':variant,'window':window,'stratum':stratum,'policy_id':policy,'panel':panel,'reference':reference,**b,'coverage_including_unavailable':b['covered']/n if n else None,'mean_regret':b['regret_sum']/scored if scored else None,'mean_normalized_regret':b['normalized_regret_sum']/scored if scored else None})
   write(a.out/'QUALITY_AGGREGATE.json',aggregate)
 finally:
  rawfile.close();auditfile.close();proc.stdin.close();proc.stdout.close();returncode=proc.wait();stderr.close()
 if returncode:raise ValueError('feature probe nonzero exit')
 # Parser/duplicate-ID negatives are distinct fresh-process synthetic checks.
 parser_checks=[]
 if a.synthetic:
  valid={'request_id':'duplicate','features':[],'config':policies[0]['feature_config']}
  for name,payload in [('unknown_field',json.dumps(dict(valid,unknown_field=True))+'\n'),('duplicate_request_id',(json.dumps(valid)+'\n')*2)]:
   z=subprocess.run([str(a.probe.resolve())],input=payload,text=True,capture_output=True,cwd=a.probe_root)
   if z.returncode!=2:raise ValueError('strict parser expected rejection did not occur: '+name)
   parser_checks.append({'name':name,'exit_code':z.returncode,'stderr':z.stderr})
 write(a.out/'REPORT.json',{'schema':'sg-finite20-safe-feature-evidence-v1','synthetic_only':a.synthetic,'offline_quality_not_serving_latency':True,'probe_sha256':binarysha,'source_sha256':source,'origin_sha256':E.sha(a.probe_root/'FINITE_SAFE_ORIGIN.json'),'matrix_sha256':E.sha(a.probe_root/'FINITE_SAFE_MATRIX.json'),'evaluator_sha256':E.sha(E.__file__),'helper_sha256':E.sha(__file__),'manifest_sha256':E.sha(a.manifest/'MANIFEST.json') if a.manifest else None,'native_pools':len(pools),'policies':len(policies),'requests':requests,'independent_constraint_checks':len(raw),'original_finite20_parity_checks':parity,'parser_negatives':parser_checks,'offered_rows_retained':sum(map(len,rows_by_pool.values())) if not a.synthetic else None,'oracle_original_slots_retained':manifest['oracle_slots_retained'] if manifest else None,'oracle_original_complete_slots_retained':manifest['oracle_complete_slots_retained'] if manifest else None,'limitations':['Original393/stress panels are exposed tune diagnostics, not optimizer inputs or untouched preference generalization.','No new real-model router,validation,test or serving timing was run.','Independent integer historical baseline and chosen20 safeguards are checked; continuous repair exactness relies on separately qualified geometry/source proof.']})
 print(json.dumps(E.read(a.out/'REPORT.json')))
if __name__=='__main__':main()
