#!/usr/bin/env python3
import argparse,hashlib,importlib.util,json,math,pathlib,random,subprocess,time
P=pathlib.Path(__file__).parent
s=importlib.util.spec_from_file_location('rational',P/'selector_exact_audit.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--probe',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();out=pathlib.Path(a.out);out.mkdir(exist_ok=False);rng=random.Random(202610211521);cases=[]
 # Deliberate trap plus synthetic candidates. No search outcomes or timing claims.
 cases.append({'name':'triple_interior','pool':[(1900,0,300),(1600,2,0),(2500,0,0),(1800,1,100)],'box':[0,900,0,4]})
 for i in range(55):
  n=rng.randrange(3,9);p=[(rng.randrange(1,3601),rng.randrange(4),rng.randrange(601)) for _ in range(n)]
  cases.append({'name':'synthetic_%02d'%i,'pool':p,'box':rng.choice([[0,900,0,4],[0,0,0,4],[100,900,1,1],[75,750,.25,3]])})
 # Real exposed-V1 pool replays are retrospective only.
 source='/workspace/shared/sg-coldstart/public-campaign-20261021/resumed-0130/evalkit-test-primary-default-morning/queries.jsonl'
 for line in open(source):
  r=json.loads(line)
  if r['algorithm']=='mc_raptor' and len(r['stages']['candidates'])>=3:
   js=r['stages']['candidates'];p=[mvec(j) for j in js]
   if len(p)<=10:cases.append({'name':'exposed_v1_'+r['query_id'],'pool':p,'patterns':[j['pattern'] for j in js],'box':[0,900,0,4]})
   if len(cases)>=76:break
 records=[];errors=[];maxabs=maxrel=0;start=time.time()
 for case in cases:
  pool=case['pool'];ids=['c%03d'%i for i in range(len(pool))];pats=case.get('patterns',ids);features=[{'identity':ids[i],'route_stop_walk_pattern':pats[i],'duration_seconds':v[0],'metrics':{'transfers':v[1],'walking_seconds':v[2]}} for i,v in enumerate(pool)]
  for objective in ['absolute','normalized']:
   for exact in [False,True]:
    if exact and len(pool)>8:continue
    box=case['box'];cfg={'max_candidates':1024,'max_subsets':200000,'bounded':{'min_transfer_seconds':box[0],'max_transfer_seconds':box[1],'min_extra_walk_weight':box[2],'max_extra_walk_weight':box[3],'objective':objective,'limits':[3,5],'distinct_patterns':False,'nested':False,'max_critical_points':100000,'max_work':50000000,'exact_subset_search':exact}}
    req={'features':features,'config':cfg};pr=subprocess.run([a.probe],input=json.dumps(req),text=True,capture_output=True);rec={'case':case['name'],'objective':objective,'exact':exact,'input':req,'returncode':pr.returncode,'stderr':pr.stderr}
    if pr.returncode:errors.append({'case':case['name'],'failure':pr.stderr});rec['stdout']=pr.stdout;records.append(rec);continue
    result=json.loads(pr.stdout);rec['output']=result;rec['rational']=[]
    for pick in result['selections']:
     selected=[ids.index(i) for i in pick['selected']];add=m.worst(pool,selected,box);rel=m.worst(pool,selected,box,True);ae=abs(float(add['maximum'])-pick['worst_pool_absolute_regret']);re=abs(float(rel['maximum'])-pick['worst_pool_normalized_regret']);maxabs=max(maxabs,ae);maxrel=max(maxrel,re)
     row={'limit':pick['limit'],'additive':m.encode(add),'normalized':m.encode(rel),'additive_error':ae,'normalized_error':re}
     if ae>1e-8 or re>1e-12:errors.append({'case':case['name'],'objective':objective,'exact':exact,'limit':pick['limit'],'absolute_error':ae,'relative_error':re})
     if exact:
      oracle=m.exhaustive(pool,min(pick['limit'],len(pool)),box,objective=='normalized');value=add['maximum'] if objective=='absolute' else rel['maximum'];gap=float(value-oracle['objective']['maximum']);row['exact_primary_optimum']=m.encode(oracle);row['optimum_gap']=gap
      if gap>(1e-8 if objective=='absolute' else 1e-12):errors.append({'case':case['name'],'failure':'subset_optimal_false','gap':gap})
     rec['rational'].append(row)
    records.append(rec)
 with (out/'cases.jsonl').open('w') as f:
  for r in records:f.write(json.dumps(r)+'\n')
 report={'schema':'independent-selector-replay-v1','cases':len(cases),'probe_executions':len(records),'selected_outputs':sum(len(r.get('rational',[])) for r in records),'failures':errors,'max_absolute_error_score_seconds':maxabs,'max_normalized_error':maxrel,'elapsed_seconds':time.time()-start,'probe_sha256':sha(a.probe),'rational_auditor_sha256':sha(P/'selector_exact_audit.py'),'replay_script_sha256':sha(__file__),'case_records_sha256':sha(out/'cases.jsonl'),'scope':'synthetic and exposed-V1 feature replay, no routing benchmark, no new V2 holdout and no journey completeness claim'}
 (out/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
def mvec(j):return (j['duration_seconds'],j['metrics']['transfers'],j['metrics']['walking_seconds'])
if __name__=='__main__':main()
