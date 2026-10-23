#!/usr/bin/env python3
"""STATIC derived projection only. Test/run after owner measurement release.

No router/optimizer/new evaluator. Actual clocks are pooled from ordinary rows;
quality comes from sealed V4, plus optional existing score_stage on independently
checked witnesses and the separately labeled initial reference generation.
Takes campaign.lock internally; never outer-wrap this helper in the same lock.
"""
import argparse,collections,fcntl,hashlib,importlib.util,json,math,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PARITY_SHA='3b12724741e846ac0c9bfc3d16ca691ac0a34bd161e1a7a99ffacee1c5dd677f'
V4_SHA='b75ff1d989896d411fa33d39f70ccc995a2af25f5b2d598c23fa0004c1dc37b0'
B_SHA='b95a3706d533c89e53a06a798d8b65815146c94fcdc5b0cb8f481ded300bee88'
CHECKER_SHA='d26f32d8cabfcc873387749cd1d9d818bbaecd8ad3b597753f029b0f7a5aeedb'
PLAN_SHA='562780615b349aca408e291a3f5cee989b125977f030d805d241b87696a75627'
MANIFEST_SHA='52712fdc0ecf6f1d1db4ef33a52bf90f1f909eb6bc038707200bc54bb8df9812'
CLOCK_FIELDS=('response_ns','published_response_ns','quality_ns','validation_rank_ns','serialization_ns','core_ns')
PROCESS_FIELDS=('startup_phase_sum_ns','process_wall_s','launch_to_first_available_answer_ns','accepted_native_launch_to_first_available_answer_ns','sampled_peak_rss_bytes')
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  while chunk:=f.read(1048576):h.update(chunk)
 return h.hexdigest()
def read(path):return json.loads(Path(path).read_text())
def lines(path):
 with Path(path).open() as f:
  for line in f:yield json.loads(line)
def write(path,value):
 with Path(path).open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def identity(value):return json.dumps(json.loads(value),sort_keys=True,separators=(',',':'),ensure_ascii=False)
def load_module(name,path,expected):
 if sha(path)!=expected:raise ValueError('qualified source changed: '+str(path))
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def dist(values):
 xs=sorted(values);n=len(xs)
 return {'count':n,'mean':statistics.fmean(xs) if n else None,'p50':xs[math.ceil(.5*n)-1] if n else None,'p95':xs[math.ceil(.95*n)-1] if n else None,'p99':xs[math.ceil(.99*n)-1] if n else None,'max':xs[-1] if n else None,'method':'empirical nearest rank of pooled actual observations; not averaged quantiles or SLA'}
def projections(run):
 return [(run['variant_id'],run['requested_selector_limit'],b,w) for b,w in [(run['block'],run['window']),(run['block'],'all_windows'),('both_blocks',run['window']),('both_blocks','all_windows')]]
def exact_pair(parity,left,right,left_error=None,right_error=None):
 if left_error or right_error:return {'status':'unknown','baseline_error':left_error,'candidate_error':right_error}
 changed=[];incomplete=[];incomplete_changed=[]
 for qid in sorted(set(left)|set(right)):
  a,b=left.get(qid),right.get(qid)
  if a is None or b is None:changed.append({'query_id':qid,'fields':['missing_record']});continue
  fields=[field for field in parity.FIELDS if a[field]!=b[field]]
  if not a['completed'] or not b['completed']:
   incomplete.append(qid)
   if fields:incomplete_changed.append({'query_id':qid,'fields':fields})
  elif fields:changed.append({'query_id':qid,'fields':fields})
 return {'status':'mismatch' if changed else 'unknown' if incomplete else 'exact','offered':len(set(left)|set(right)),'differences':changed,'incomplete_query_ids':incomplete,'incomplete_outcome_differences':incomplete_changed}
def compact_score(score):
 out={k:v for k,v in score.items() if k not in ('regrets','normalized_regrets')}
 if 'regrets' in score:out['regret_score_seconds']=dist(score['regrets'])
 if 'normalized_regrets' in score:out['normalized_regret']=dist(score['normalized_regrets'])
 return out
def add_quality(bucket,value,complete):
 bucket['offered_rows']+=1;bucket['independently_complete_rows']+=bool(complete);bucket['eligible_slots']+=value.get('eligible',0)
 if value.get('missing'):bucket['missing_slots']+=value.get('eligible',0)
 for key in ('covered','within30','within60','within120','within1percent','within5percent','counterexample_slots'):bucket[key]+=value.get(key,0)
 for key in ('regret_score_seconds','normalized_regret'):
  d=value.get(key,{})
  if d.get('count',0):
   bucket[key+'_count']+=d['count'];bucket[key+'_weighted_sum'].append(d['count']*d['mean']);bucket[key+'_max']=max(bucket[key+'_max'],d['max']) if bucket[key+'_max'] is not None else d['max']
def new_quality():return {'offered_rows':0,'independently_complete_rows':0,'eligible_slots':0,'missing_slots':0,'covered':0,'within30':0,'within60':0,'within120':0,'within1percent':0,'within5percent':0,'counterexample_slots':0,**{k+suffix:value for k in ('regret_score_seconds','normalized_regret') for suffix,value in [('_count',0),('_weighted_sum',[]),('_max',None)]}}
def finish_quality(value):
 out=dict(value);n=out['eligible_slots'];out['coverage_including_unavailable']=out['covered']/n if n else None
 for key in ('regret_score_seconds','normalized_regret'):
  xs=out.pop(key+'_weighted_sum');count=out[key+'_count'];out[key+'_mean']=math.fsum(xs)/count if count else None
 out['pooled_quality_quantiles']='not inferable from compact row distributions; authoritative window/stratum aggregates preserved separately; never average quantiles'
 return out
def observed_slacks(checker,query,validated):
 now=query['departure'];previous=None;last_ride=None;slacks=[]
 for leg in validated['journey']['legs']:
  if leg['kind']=='ride':
   ride=checker.rides[leg['ref']];continuing=previous is not None and previous['trip_id']==ride['trip_id'] and previous['sequence']+1==ride['sequence']
   if not continuing and last_ride is not None:
    allowed,minimum=checker.transfer(last_ride,ride,query['transfer_buffer']);ready=max(now,last_ride['arrival']+minimum);slack=ride['departure']-ready
    if not allowed or slack<0:raise ValueError('checked witness has negative/prohibited interchange slack')
    slacks.append(slack)
   previous=last_ride=ride
  else:previous=None
  now=leg['arrival']
 return slacks
def pattern_sets(features,selected):
 physical={features[i]['pattern'] for i in selected};ride=set()
 for i in selected:
  tokens=[v for v in json.loads(features[i]['pattern']) if v['kind']=='ride']
  if tokens:ride.add(json.dumps(tokens,sort_keys=True,separators=(',',':')))
 return physical,ride
def pattern_overlap(a,b):
 union=a|b
 return {'intersection':len(a&b),'union':len(union),'jaccard':len(a&b)/len(union) if union else None,'pattern_count_delta_vs_finite20':len(a)-len(b)}
def project(campaign,evaluation,out,with_stress=True):
 out.mkdir(parents=True,exist_ok=False);bindings={};report=read(evaluation/'REPORT.json');authoritative=report['inputs']
 def consume(path,expected=None,authoritative_required=False):
  path=Path(path).resolve();digest=sha(path)
  if expected and digest!=expected:raise ValueError('frozen input hash differs: '+str(path))
  if authoritative_required and authoritative.get(str(path))!=digest:raise ValueError('not bound to authoritative V4 input: '+str(path))
  bindings[str(path)]=digest;return path
 parity=load_module('qualified_native_parity',consume(ROOT/'analysis/compare_native_outputs.py',PARITY_SHA),PARITY_SHA)
 B=load_module('qualified_B_projection_helpers',consume(ROOT/'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py',B_SHA,True),B_SHA)
 legacy=load_module('qualified_checked_sidepanel',consume(ROOT.parent/'evalkit/evalkit.py',CHECKER_SHA,True),CHECKER_SHA)
 consume(ROOT/'analysis/evaluate_v2_feasible_safe_fill_v4.py',V4_SHA,True);consume(evaluation/'REPORT.json');plan=read(consume(campaign/'plan.json',PLAN_SHA,True));runs={r['id']:r for r in plan['runs']}
 if len(runs)!=96 or len({r['variant_id'] for r in runs.values()})!=12:raise ValueError('not exact frozen96 serving panel')
 quality_path=consume(evaluation/'QUALITY_ROWS.jsonl');states={};quality=collections.defaultdict(new_quality);quality_seen=set()
 for row in lines(quality_path):
  run=runs.get(row['run'])
  if run is None:raise ValueError('quality row from undeclared run')
  tag=(row['run'],row['query_id'],row['stage'])
  if tag in quality_seen:raise ValueError('duplicate authoritative quality row')
  quality_seen.add(tag)
  if row['stage']=='final':states[tag[:2]]={'complete':row['complete'],'status':row['status'],'cohort':row['common_pool_cohort']}
  for panel,field in [('full393','score'),('leave_family_out_signed','leave_donor_family_out_signed'),('leave_ancestry_out_signed','leave_donor_lineage_out_signed')]:
   if field not in row:continue
   for key in projections(run):add_quality(quality[(*key,row['stage'],panel)],row[field],row['complete'])
 metrics=read(consume(evaluation/'METRICS_BY_RUN.json'));metric_by={m['id']:m for m in metrics}
 if set(metric_by)!=set(runs):raise ValueError('authoritative metrics do not cover all96 runs')
 # Preserve exact evaluator distributions. No cross-window quantile invention.
 aggregates=read(consume(evaluation/'QUALITY_AGGREGATE.json'));write(out/'AUTHORITATIVE_QUALITY_AGGREGATE_UNCHANGED.json',aggregates)
 row_clocks=collections.defaultdict(lambda:collections.defaultdict(list));process_clocks=collections.defaultdict(lambda:collections.defaultdict(list));guard_rows=[];pass_rows={};summaries={}
 def bound_read(path):return read(consume(path,authoritative_required=True))
 for rid,run in runs.items():
  summary_path=campaign/rid/'artifact/summary.json';result_path=campaign/rid/'result.json';summary=bound_read(summary_path) if summary_path.exists() else {};supervisor=bound_read(result_path) if result_path.exists() else {};summaries[rid]=summary;config=read(consume(Path(run['argv'][run['argv'].index('-preference-scenarios')+1]),authoritative_required=True));k,_=B.delivery_config(config,run['requested_selector_limit'])
  if summary and summary.get('preference_config_sha256')!=bindings[str(Path(run['argv'][run['argv'].index('-preference-scenarios')+1]).resolve())]:raise ValueError('summary config binding mismatch')
  records=[]
  for desc in summary.get('passes',[]):
   if desc.get('warmup') or desc.get('forced'):continue
   path=consume(campaign/rid/'artifact'/desc['file'],desc['sha256'],True);records.extend(read(path)['records'])
  if len(records)>60 or len({r['query']['id'] for r in records})!=len(records):raise ValueError('extra/duplicate ordinary offered records')
  # Keep paths only; do not retain every heavy recommendation payload at once.
  pass_rows[rid]=[d for d in summary.get('passes',[]) if not d.get('warmup') and not d.get('forced')]
  statuses=collections.Counter(v['status'] for (rr,qid),v in states.items() if rr==rid);errors=collections.Counter();methods=collections.Counter();selection_incomplete=0
  for row in records:
   state=states.get((rid,row['query']['id']))
   if state is None:raise ValueError('native offered row absent in V4 authoritative output')
   if row.get('error'):errors[row['error']]+=1
   q=row.get('recommendation_quality') or {};choice=q.get('continuous_choices') or q.get('finite20_safe_choices') or q.get('absolute_hybrid_fill_choices') or q.get('choices')
   if isinstance(choice,dict):
    if choice.get('complete') is not True:selection_incomplete+=1
    for s in choice.get('selections',[]):methods[s.get('method','unknown')]+=1
    for group in choice.get('groups',[]):
     for selection in group.get('selections',[]):methods[selection.get('method','unknown')]+=1
    if choice.get('selection'):methods[choice['selection'].get('method',choice.get('policy','unknown'))]+=1
   cohorts=['all_attempted'] if row.get('attempted') else []
   if state['complete']:cohorts+=['independently_complete',state['cohort']]
   for cohort in cohorts:
    for key in projections(run):
     for field in CLOCK_FIELDS:
      value=row.get(field)
      if value is not None:
       if type(value) is not int or value<0:raise ValueError('invalid measured row clock')
       row_clocks[(*key,cohort)][field].append(value)
  metric=metric_by[rid]
  for key in projections(run):
   for field in PROCESS_FIELDS:
    value=metric.get(field)
    if value is not None:process_clocks[key][field].append(value)
   for phase in ('preparation','checker_preparation','quality_preparation'):
    for field in ('elapsed_ns','allocated_bytes'):
     value=summary.get(phase,{}).get(field)
     if value is not None:process_clocks[key][phase+'_'+field].append(value)
   process_clocks[key]['input_load_ns'].append(summary.get('input_load_ns',0));process_clocks[key]['supervisor_elapsed_wall_s'].append(supervisor.get('elapsed_wall_s'))
  guard_rows.append({'run':rid,'variant_id':run['variant_id'],'block':run['block'],'window':run['window'],'limit':k,'offered_rows':sum(statuses.values()),'ordinary_records_available':len(records),'authoritative_statuses':dict(statuses),'native_errors':dict(errors),'incomplete_selector_payloads':selection_incomplete,'selector_methods':dict(methods),'supervisor_ok':supervisor.get('ok'),'preparation_complete':summary.get('preparation',{}).get('complete'),'first_published_native_row_accepted':metric.get('first_published_native_row_accepted'),'first_answer_unavailable_reason':metric.get('first_answer_unavailable_reason'),'published_deadline_misses':metric.get('published_deadline_misses')})
  records=None
 # Exactly11 policy comparisons against finite20k3 in each of8 block/window cells.
 checks=[]
 for block,window in sorted({(r['block'],r['window']) for r in runs.values()}):
  cell=sorted((r for r in runs.values() if r['block']==block and r['window']==window),key=lambda r:r['variant_id']);base=next(r for r in cell if r['variant_id']=='finite20-lean-k3');left,le=parity.load(campaign,base,bindings)
  for run in cell:
   if run['id']==base['id']:continue
   right,re=parity.load(campaign,run,bindings);checks.append({'baseline':base['id'],'candidate':run['id'],'block':block,'window':window,**exact_pair(parity,left,right,le,re)})
 if len(checks)!=88:raise ValueError('expected exactly88 native parity comparisons')
 write(out/'NATIVE_POLICY_PARITY_88.json',{'qualified_helper_sha256':PARITY_SHA,'compared_fields':list(parity.FIELDS),'checks':checks,'counts':dict(collections.Counter(c['status'] for c in checks)),'scope':'raw/final witness order,status and certificates; selector outputs/clocks intentionally excluded; incomplete differences remain unknown'})
 # One qualified independent checker/window, deduplicated witnesses. No recovery search.
 manifest_dir=ROOT/'analysis/selector-tune-v3-manifest-attempt02';manifest=None;members={};references={};stress_weights=None
 if with_stress:
  manifest=read(consume(manifest_dir/'MANIFEST.json',MANIFEST_SHA))
  for name in ('POOL_MEMBERS.jsonl','REFERENCE_POOLS.jsonl'):consume(manifest_dir/name,manifest['outputs'][name])
  for m in lines(manifest_dir/'POOL_MEMBERS.jsonl'):members[(m['dataset_sha256'],m['query_id'],m['identity'])]=m['feature']
  references={(r['dataset_sha256'],r['query_id']):r for r in lines(manifest_dir/'REFERENCE_POOLS.jsonl')}
  seal=read(consume(ROOT/'selector-quality/PREFERENCE_SEAL.json',authoritative_required=True));stress_weights=read(consume(ROOT/'selector-quality/configs/outside_rectangle_stress257.json',seal['files']['outside_rectangle_stress257.json']))
 side=out/'CHECKED_PATTERN_SLACK_ROWS.jsonl';stress_path=out/'INITIAL_REFERENCE_STRESS_ROWS.jsonl';overlaps=[];stress_groups=collections.defaultdict(new_quality);stress_cache={}
 with side.open('x') as sf,stress_path.open('x') as tf:
  for window in sorted({r['window'] for r in runs.values()}):
   window_runs=[r for r in runs.values() if r['window']==window];first=window_runs[0];dataset=consume(Path(first['argv'][first['argv'].index('-dataset')+1]),authoritative_required=True);dsha=bindings[str(dataset)];checker=legacy.Checker(read(dataset));cache={};selected_sets={}
   for run in window_runs:
    rid=run['id'];config=read(Path(run['argv'][run['argv'].index('-preference-scenarios')+1]));workload=Path(run['argv'][run['argv'].index('-queries')+1]);records=[]
    initial_query_bound=with_stress and manifest['inputs'].get(str(workload.resolve()))==sha(workload)
    def emit_initial_stress(qid,chosen,ids,complete):
     reference=references.get((dsha,qid));entry={'run':rid,'query_id':qid,'variant_id':run['variant_id'],'limit':run['requested_selector_limit'],'independently_complete':complete,'scope':'Actual independently checked serving selection; OLD initial192 reference generation only, not native-enriched/ancestry stress or heldout generalization'}
     if reference is None or not initial_query_bound:entry['status']='unknown_missing_initial_query_binding'
     else:
      ck=(dsha,qid,tuple(ids),complete);scores=stress_cache.get(ck)
      if scores is None:
       scores={}
       for panel,refids in [('common',reference['common_semantic_ids']),('leave_family_out_signed',reference['leave_donor_family_out']['McRAPTOR']['semantic_ids'])]:
        ref=[members[(dsha,qid,i)] for i in refids];scores[panel]=compact_score(B.score_stage(chosen,ref,stress_weights,complete))
       stress_cache[ck]=scores
      entry.update(status='checked_existing_score_helper' if complete else 'unknown_incomplete_candidate_retained',scores=scores)
      for panel,value in scores.items():
       for group in projections(run):add_quality(stress_groups[(*group,panel)],value,complete)
     tf.write(json.dumps(entry,separators=(',',':'))+'\n')
    for desc in pass_rows[rid]:records.extend(read(campaign/rid/'artifact'/desc['file'])['records'])
    for row in records:
     q=row['query'];state=states[(rid,q['id'])];entry={'run':rid,'block':run['block'],'window':window,'query_id':q['id'],'variant_id':run['variant_id'],'limit':run['requested_selector_limit'],'independently_complete':state['complete'],'recovery_status':'not_computed_lean_no_recovery_index; no resilience or reliability claim'}
     if not state['complete']:
      unknown=dict(entry,status='unknown_independent_incomplete');sf.write(json.dumps(unknown,separators=(',',':'))+'\n')
      if with_stress:emit_initial_stress(q['id'],[],[],False)
      continue
     features={}
     for obj in row['final']:
      key=json.dumps((q,obj),sort_keys=True,separators=(',',':'));v=cache.get(key)
      if v is None:checker.query(q);v=checker.check(q,obj);v=dict(v,observed_rule_adjusted_interchange_slacks=observed_slacks(checker,q,v));cache[key]=v
      iv=identity(v['identity'])
      if iv in features:raise ValueError('duplicate checked native candidate identity')
      features[iv]=v
     ids=[identity(i) for i in B.selected_delivery_ids(row,config,run['requested_selector_limit'])]
     if any(i not in features for i in ids):raise ValueError('checked selected identity absent')
     physical,ride=pattern_sets(features,ids);nativephysical,nativeride=pattern_sets(features,list(features));slacks=[s for i in ids for s in features[i]['observed_rule_adjusted_interchange_slacks']];entry.update(status='checked',native_candidates=len(features),selected_count=len(ids),native_physical_patterns=len(nativephysical),selected_physical_patterns=len(physical),native_ride_patterns=len(nativeride),selected_ride_patterns=len(ride),selected_observed_slack_seconds=dist(slacks),selected_interchanges=len(slacks),selected_interchanges_below_seconds={str(t):sum(s<t for s in slacks) for t in (30,60,120,300)},slack_scope='Observed ready=max(walk-complete,incoming-arrival+resolved-minimum); not disturbance/recovery success')
     fill=(row.get('recommendation_quality') or {}).get('absolute_hybrid_fill_choices')
     if fill:
      base=[identity(i) for i in fill['selection']['base_selected']];bp,br=pattern_sets(features,base)
      if not set(base)<=set(ids) or not bp<=physical or not br<=ride:raise ValueError('fill lost own base identity/pattern')
      entry.update(fill_own_base_pattern_inclusion=True,fill_own_base_physical_patterns=len(bp),fill_own_base_ride_patterns=len(br),finite20_diversity_dominance_claim=False)
     sf.write(json.dumps(entry,separators=(',',':'))+'\n');selected_sets[(run['block'],q['id'],run['variant_id'])]=(set(ids),physical,ride,entry['limit'])
     if with_stress:emit_initial_stress(q['id'],[features[i] for i in ids],ids,True)
    available={r['query']['id'] for r in records}
    for (offered_rid,qid),state in states.items():
     if offered_rid==rid and qid not in available:
      unknown={'run':rid,'block':run['block'],'window':window,'query_id':qid,'variant_id':run['variant_id'],'limit':run['requested_selector_limit'],'independently_complete':False,'status':'unknown_missing_ordinary_native_record','recovery_status':'not_computed'};sf.write(json.dumps(unknown,separators=(',',':'))+'\n')
      if with_stress:emit_initial_stress(qid,[],[],False)
    records=None
   for (block,qid,variant),(ids,physical,ride,k) in selected_sets.items():
    base=selected_sets.get((block,qid,'finite20-lean-k%d'%k))
    if base:overlaps.append({'block':block,'window':window,'query_id':qid,'variant_id':variant,'limit':k,'versus':'finite20-lean-k%d'%k,'identity_overlap':pattern_overlap(ids,base[0]),'physical_pattern_overlap':pattern_overlap(physical,base[1]),'ride_pattern_overlap':pattern_overlap(ride,base[2]),'scope':'same-k diagnostic only; fill inclusion guarantees its own base, not finite20 diversity'})
   checker=None;cache=None
 write(out/'PATTERN_OVERLAP_VS_FINITE20.json',overlaps)
 write(out/'POOLED_ACTUAL_ROW_CLOCKS.json',[{'variant_id':key[0],'limit':key[1],'block':key[2],'window':key[3],'cohort':key[4],**{field:dist(values) for field,values in fields.items()}} for key,fields in sorted(row_clocks.items(),key=lambda z:str(z[0]))])
 write(out/'POOLED_ACTUAL_PROCESS_CLOCKS.json',[{'variant_id':key[0],'limit':key[1],'block':key[2],'window':key[3],**{field:dist([v for v in values if v is not None]) for field,values in fields.items()}} for key,fields in sorted(process_clocks.items(),key=lambda z:str(z[0]))])
 write(out/'QUALITY_COUNTS_MEANS_MAXIMA.json',[{'variant_id':key[0],'limit':key[1],'block':key[2],'window':key[3],'stage':key[4],'panel':key[5],**finish_quality(value)} for key,value in sorted(quality.items(),key=lambda z:str(z[0]))])
 write(out/'INITIAL_REFERENCE_STRESS_COUNTS_MEANS_MAXIMA.json',[{'variant_id':key[0],'limit':key[1],'block':key[2],'window':key[3],'panel':key[4],**finish_quality(value)} for key,value in sorted(stress_groups.items(),key=lambda z:str(z[0]))])
 write(out/'GUARDS_AND_FIRST_ANSWER_ACCEPTANCE.json',guard_rows)
 # Revalidate every direct authoritative input read, plus parity.load additions.
 for path,digest in bindings.items():
  if sha(path)!=digest:raise ValueError('input changed during derived projection: '+path)
  if str(campaign) in path and path not in authoritative:raise ValueError('projection consumed unbound campaign artifact: '+path)
 write(out/'REPORT.json',{'schema':'sg-source-B-serving-derived-frontier-v1','helper_sha256':sha(__file__),'inputs':bindings,'evaluator_report_sha256':sha(evaluation/'REPORT.json'),'source_B_plan_sha256':PLAN_SHA,'runs':len(runs),'offered_rows':len(states),'native_pair_checks':len(checks),'native_parity_counts':dict(collections.Counter(c['status'] for c in checks)),'oracle_offered_slots':report['oracle_offered_slots'],'oracle_complete_slots':report['oracle_complete_slots'],'oracle_unknown_slots':report['oracle_offered_slots']-report['oracle_complete_slots'],'limitations':['Derived projection only, not a new evaluator/router/optimizer.','Latency quantiles pool actual observations; quality quantiles are preserved only at their authoritative aggregate resolution.','393/continuous saturation is not launch quality, authentic utility, journey completeness or reliability.','Published latency is emitted separately from compute response; first answer accepted only under V4 independent native/display check.','Native incomplete differences are unknown, never parity success.','Current full393 common/family/ancestry quality is retained; optional stress uses only old independently reconstructed reference generation.','Observed interchange slack is not recovery probability; lean recovery was not computed.','Fill preserves own-base patterns; no finite20 diversity dominance is claimed.','All12 products including losing policies, finite20k3/k5 controls and all offered unknown/guard rows are retained.']})
 print(json.dumps({'out':str(out),'runs':len(runs),'offered_rows':len(states),'parity':dict(collections.Counter(c['status'] for c in checks))}),flush=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('--quiet-window-open',action='store_true');p.add_argument('--campaign',type=Path,required=True);p.add_argument('--evaluation',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--without-initial-stress',action='store_true');a=p.parse_args()
 if not a.quiet_window_open:raise SystemExit('Owner measurement release/analysis slot required')
 with (ROOT.parent/'setup/campaign.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);project(a.campaign.resolve(),a.evaluation.resolve(),a.out.resolve(),not a.without_initial_stress)
if __name__=='__main__':main()
