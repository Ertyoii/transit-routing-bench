#!/usr/bin/env python3
"""Prepare metadata-bound selector inputs after authoritative independent evaluation.

No routers are run. Native candidate inputs are reconstructed final witnesses,
never chosen-display unions or oracle-enriched pools. Common/LOFO references are
separate objects. This helper must not run during headline timing.
"""
import argparse,collections,hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('selector_eval_v2',ROOT/'analysis/evaluate_v2.py')
E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def go_json(x):
 return json.dumps(x,separators=(',',':'),ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
def go_identity(v):return go_json([{'kind':x['kind'],'ref':x['ref']} for x in json.loads(v)])
def go_pattern(v):
 out=[]
 for t in json.loads(v):
  if t['kind']=='walk':z={'Kind':'walk','Route':'','Stops':None,'Walk':t['footpath']}
  else:
   z={'Kind':'ride','Route':t['route'],'Stops':t['stops'],'Walk':''}
   if t.get('missing_route'):z['MissingRoute']=True
  out.append(z)
 return go_json(out)
def feature(v):return {'identity':go_identity(v['identity']),'route_stop_walk_pattern':go_pattern(v['pattern']),'metrics':v['metrics'],'duration_seconds':v['duration_seconds']}
def pool_id(role,dsha,qid,features):return digest({'role':role,'dataset_sha256':dsha,'query_id':qid,'features':sorted(features,key=lambda f:f['identity'])})
def selections(row):
 quality=row.get('recommendation_quality') or {};out=[];continuous=quality.get('continuous_choices')
 if continuous is not None:
  for s in continuous.get('selections',[]):out.append({'policy':'bounded_continuous_regret_v3','limit':s['limit'],'selected':s.get('selected',[]),'selection_complete':bool(continuous.get('complete') and s.get('complete')),'details':s})
 choices=quality.get('choices') or {}
 for group in choices.get('groups',[]):
  for s in group.get('selections',[]):
   if s.get('method')=='preference_minimax':out.append({'policy':'finite_preferences_v2','group':group['group']['name'],'limit':s['limit'],'selected':s.get('selected',[]),'selection_complete':bool(choices.get('complete') and s.get('complete')),'details':s})
 # Legacy envelope selections remain explicit controls if a finite selector also exists.
 for s in quality.get('selections',[]):
  if s.get('score_envelope_seconds')==300:out.append({'policy':'pattern_anchors_v1','limit':s['limit'],'selected':s.get('selected',[]),'selection_complete':True,'emitted_control_not_requested_serving':bool(choices or continuous),'details':s})
 return out

def build(campaigns,evaluation,out,evaluator=None):
 global E
 if evaluator is not None:
  spec=importlib.util.spec_from_file_location("selector_authoritative_evaluator",Path(evaluator).resolve());E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
 out.mkdir(parents=True,exist_ok=False);evaluation=Path(evaluation);report=E.read(evaluation/'REPORT.json');inputs=report['inputs'];consumed={}
 def bound_read(path):
  path=Path(path);key=str(path);actual=E.sha(path)
  if key not in inputs or inputs[key]!=actual:raise ValueError('not bound to authoritative evaluator: '+key)
  consumed[key]=actual;return E.read(path)
 for p in [Path(E.__file__).resolve(),ROOT.parent/'evalkit/evalkit.py',ROOT/'selector-quality/configs/heldout393.json',ROOT/'selector-quality/configs/scalar9.json']:
  if E.sha(p)!=inputs.get(str(p)):raise ValueError('evaluator dependency changed: '+str(p))
 held=bound_read(ROOT/'selector-quality/configs/heldout393.json');bound_read(ROOT/'selector-quality/configs/scalar9.json')
 stress=E.read(ROOT/'selector-quality/configs/outside_rectangle_stress257.json');seal=bound_read(ROOT/'selector-quality/PREFERENCE_SEAL.json')
 if E.sha(ROOT/'selector-quality/configs/outside_rectangle_stress257.json')!=seal['files']['outside_rectangle_stress257.json']:raise ValueError('stress panel seal mismatch')
 consumed[str(ROOT/'selector-quality/configs/outside_rectangle_stress257.json')]=seal['files']['outside_rectangle_stress257.json']
 states={};state_stages=collections.defaultdict(set);quality_file=evaluation/'QUALITY_ROWS.jsonl'
 with quality_file.open() as f:
  for line in f:
   z=json.loads(line);key=(z['run'],z['query_id']);state=(z['complete'],z['status'],z['dataset_sha256'])
   if z['stage'] in state_stages[key]:raise ValueError('duplicate authoritative run/query/stage')
   state_stages[key].add(z['stage'])
   if key in states and states[key]!=state:raise ValueError('authoritative stages disagree on row outcome')
   states[key]=state
 known_reconstruction_errors={(z.get('run'),z.get('query_id'),z.get('stage')) for z in E.read(evaluation/'VALIDATION_ERRORS.json')};slots=E.read(evaluation/'INDEPENDENT_ORACLE_SLOTS.json');slot_keys=set()
 for s in slots:
  key=(s['dataset_sha256'],s['query_id'],canonical(s['weight']))
  if key in slot_keys:raise ValueError('duplicate independent oracle semantic slot')
  slot_keys.add(key)
  if type(s['complete']) is not bool or type(s['found']) is not bool:raise ValueError('invalid oracle outcome type')
 descriptors=[];runids=set()
 for campaign in campaigns:
  campaign=Path(campaign);plan=bound_read(campaign/'plan.json');registry=E.gate.load_registry(plan,campaign)
  for run in plan['runs']:
   rid=run['id']
   if rid in runids:raise ValueError('duplicate run ID across replay campaigns')
   runids.add(rid);args=run['argv'];dataset=Path(E.flag(args,'-dataset'));workload=Path(E.flag(args,'-queries'));work=bound_read(workload)
   expected={i['query']['id']:i for i in work['items']}
   if len(expected)!=len(work['items']):raise ValueError('duplicate frozen workload query')
   if registry and str(workload.resolve()) not in registry['by_path']:raise ValueError('unregistered workload')
   alg=E.flag(args,'-algorithm');artifact=campaign/rid/'artifact';summary=bound_read(artifact/'summary.json') if (artifact/'summary.json').exists() else {};command=bound_read(campaign/rid/'command.json') if (campaign/rid/'command.json').exists() else {}
   dsha=inputs.get(str(dataset))
   if not dsha:raise ValueError('dataset absent from independent input binding')
   if summary:E.validate_summary_binding(summary,command,alg,dsha,E.sha(workload))
   descriptors.append({'run':run,'id':rid,'variant_id':run.get('variant_id',rid),'window':run.get('window'),'algorithm':alg,'family':E.family(alg),'dataset':dataset,'dataset_sha256':dsha,'workload':workload,'expected':expected,'artifact':artifact,'summary':summary,'campaign':str(campaign)})
 outputs={n:(out/n).open('w') for n in ['CANDIDATE_ROWS.jsonl','CANDIDATE_POOLS.jsonl','POOL_MEMBERS.jsonl','REFERENCE_POOLS.jsonl','ORIGINAL_SELECTION_SCORES.jsonl']}
 def emit(name,x):outputs[name].write(json.dumps(x,separators=(',',':'),ensure_ascii=False)+'\n')
 nrows=npools=nmembers=noriginal=0;errors=[]
 try:
  for dsha in sorted({d['dataset_sha256'] for d in descriptors}):
   related=[d for d in descriptors if d['dataset_sha256']==dsha];paths={str(d['dataset']) for d in related}
   if len(paths)!=1:raise ValueError('same dataset hash uses ambiguous replay paths')
   checker=E.legacy.Checker(bound_read(next(iter(paths))));members={};candidate_pools={};pending=[];queries={};families={d['family'] for d in related}
   def add(qid,v,family,variant,run,stage,oracle=None):
    iv=E.identity(v['identity']);key=(qid,iv);signature=(v['metrics'],v['duration_seconds'],v['pattern'],v['journey'])
    if key in members:
     if members[key]['_signature']!=signature:raise ValueError('same identity has inconsistent independent reconstruction')
     m=members[key]
    else:
     m={'query_id':qid,'dataset_sha256':dsha,'identity':iv,'feature':feature(v),'journey':v['journey'],'donor_families':set(),'donor_variants':set(),'donor_runs':set(),'contribution_stages':set(),'oracle_sources':[],'_signature':signature};members[key]=m
    m['donor_families'].add(family);m['donor_variants'].add(variant);m['donor_runs'].add(run);m['contribution_stages'].add(stage)
    if oracle is not None:m['oracle_sources'].append(oracle)
    return iv
   for d in related:
    recs={};pass_sources={}
    for descriptor in d['summary'].get('passes',[]):
     if descriptor.get('forced') or descriptor.get('warmup'):continue
     name=descriptor['file'];path=d['artifact']/name;payload=bound_read(path);E.validate_pass_binding(payload,descriptor,d['algorithm'],path)
     for r in payload['records']:
      qid=r['query']['id']
      if qid in recs:raise ValueError('duplicate ordinary query in source run')
      recs[qid]=r;pass_sources[qid]={'path':str(path),'sha256':consumed[str(path)]}
    if set(recs)-set(d['expected']):raise ValueError('source run has an unoffered query')
    for qid,offered in d['expected'].items():
     q=offered['query'];r=recs.get(qid);state=states.get((d['id'],qid))
     if state is None or state[2]!=dsha:raise ValueError('source row missing authoritative outcome')
     if qid in queries and queries[qid]!=q:raise ValueError('same ID has different frozen query contracts')
     queries[qid]=q
     if r and (r['query']!=q or r.get('stratum')!=offered.get('stratum')):raise ValueError('offered query/stratum differs')
     by_stage={};reconstruction_errors=[]
     for stage in ['raw','final']:
      seen={}
      for obj in (r or {}).get(stage,[]):
       try:v=checker.check(q,obj)
       except (E.legacy.ValidationError,KeyError,ValueError,TypeError) as exc:
        reconstruction_errors.append({'stage':stage,'error':str(exc)});continue
       iv=E.identity(v['identity'])
       if iv in seen:
        if seen[iv]!=v:raise ValueError('conflicting duplicate source witness')
        if stage=='final':reconstruction_errors.append({'stage':stage,'error':'duplicate final identity'})
       seen[iv]=v;add(qid,v,d['family'],d['variant_id'],d['id'],stage)
      by_stage[stage]=seen
     if reconstruction_errors and (state[0] or any((d['id'],qid,z['stage']) not in known_reconstruction_errors for z in reconstruction_errors)):raise ValueError('new reconstruction error disagrees with authoritative evaluation')
     fs=[feature(v) for _,v in sorted(by_stage['final'].items())];cid=pool_id('native_final_before_selection',dsha,qid,fs);candidate_pools.setdefault(cid,{'candidate_pool_id':cid,'role':'native_final_before_selection','dataset_sha256':dsha,'query_id':qid,'features':fs,'native_runs':[]})['native_runs'].append(d['id'])
     emitted=[]
     for s in selections(r or {}):
      canonical_ids=[E.identity(i) for i in s['selected']]
      if len(canonical_ids)!=len(set(canonical_ids)) or len(canonical_ids)>s['limit']:raise ValueError('duplicate/over-cap original selected identities')
      if any(i not in by_stage['final'] for i in canonical_ids):raise ValueError('original selected identity absent from independently valid final pool')
      s={**s,'emitted_selected_ids':s['selected'],'selected_semantic_ids':canonical_ids,'selected_replay_ids':[feature(by_stage['final'][i])['identity'] for i in canonical_ids]};s.pop('selected');emitted.append(s)
     for native_feature in ((r or {}).get('recommendation_quality') or {}).get('features',[]):
      iv=E.identity(native_feature['identity'])
      if iv not in by_stage['final']:raise ValueError('native feature identity absent from final witnesses')
      v=by_stage['final'][iv]
      if native_feature['metrics']!=v['metrics'] or native_feature['duration_seconds']!=v['duration_seconds']:raise ValueError('native feature objective claims differ from independent reconstruction')
     row={'run':d['id'],'variant_id':d['variant_id'],'window':d['window'],'algorithm':d['algorithm'],'family':d['family'],'dataset_sha256':dsha,'query':q,'query_sha256':digest(q),'stratum':offered['stratum'],'native_complete':bool(r and r.get('completed')),'independent_complete':state[0],'independent_status':state[1],'candidate_pool_id':cid,'candidate_count':len(fs),'raw_semantic_ids':sorted(by_stage['raw']),'original_selections':emitted,'requested_preference_config':d['summary'].get('preference_config'),'source_pass':pass_sources.get(qid),'reconstruction_errors':reconstruction_errors,'candidate_pool_definition':'independently reconstructed native final candidates before chosen display; oracle/common/LOFO witnesses are never added to this candidate input'}
     pending.append((row,by_stage['final']));emit('CANDIDATE_ROWS.jsonl',row);nrows+=1
   relevant_slots=[s for s in slots if s['dataset_sha256']==dsha]
   for s in relevant_slots:
    qid=s['query_id']
    if qid not in queries:raise ValueError('independent reference query absent from offered replay universe')
    if s['complete'] and s['found']:
     v=checker.check(queries[qid],s['journey'])
     if abs(E.cost(v,s['weight'])-s['score_seconds'])>1e-7:raise ValueError('oracle witness score changed in replay reconstruction')
     add(qid,v,'independent_scalar_oracle','independent_scalar_oracle',s['source'],'oracle',{'source':s['source'],'weight':s['weight'],'complete':True})
   for cid,pool in sorted(candidate_pools.items()):pool['native_runs']=sorted(set(pool['native_runs']));emit('CANDIDATE_POOLS.jsonl',pool);npools+=1
   for (_,iv),m in sorted(members.items()):
    for key in ['donor_families','donor_variants','donor_runs','contribution_stages']:m[key]=sorted(m[key])
    m.pop('_signature');emit('POOL_MEMBERS.jsonl',m);nmembers+=1
   refs={}
   for qid,q in sorted(queries.items()):
    local=[m for (mq,_),m in members.items() if mq==qid];full=sorted(m['identity'] for m in local);lofo={family:sorted(m['identity'] for m in local if set(m['donor_families'])-{family}) for family in sorted(families)}
    ref={'query_id':qid,'dataset_sha256':dsha,'common_semantic_ids':full,'common_pool_id':digest({'dataset':dsha,'query':qid,'members':full}),'leave_donor_family_out':{f:{'semantic_ids':ids,'pool_id':digest({'dataset':dsha,'query':qid,'exclude_family':f,'members':ids})} for f,ids in lofo.items()},'oracle_slots':[s for s in relevant_slots if s['query_id']==qid],'reference_scope':'incomplete feasible-witness union plus complete scalar-oracle witnesses; exact optimum only in the original complete9 scalar slots, never a393-profile/full3D proof'};refs[qid]=ref;emit('REFERENCE_POOLS.jsonl',ref)
   for row,by in pending:
    qid=row['query']['id'];ref=refs[qid];full=[{'duration_seconds':members[(qid,i)]['feature']['duration_seconds'],'metrics':members[(qid,i)]['feature']['metrics']} for i in ref['common_semantic_ids']];lofo=[{'duration_seconds':members[(qid,i)]['feature']['duration_seconds'],'metrics':members[(qid,i)]['feature']['metrics']} for i in ref['leave_donor_family_out'][row['family']]['semantic_ids']]
    for s in row['original_selections']:
     chosen=[by[i] for i in s['selected_semantic_ids']];success=row['independent_complete'] and s['selection_complete'];panels={}
     for name,ws in [('heldout393',held),('outside_rectangle_stress257',stress)]:
      panels[name]={'common':E.score_stage(chosen,full,ws,success),'leave_donor_family_out_signed':E.score_stage(chosen,lofo,ws,success)}
      for scored in panels[name].values():
       scored['regret_score_seconds']=E.dist(scored.pop('regrets',[]));scored['normalized_regret']=E.dist(scored.pop('normalized_regrets',[]))
     emit('ORIGINAL_SELECTION_SCORES.jsonl',{'run':row['run'],'variant_id':row['variant_id'],'window':row['window'],'family':row['family'],'dataset_sha256':dsha,'query_id':qid,'policy':s['policy'],'limit':s['limit'],'selected_replay_ids':s['selected_replay_ids'],'independent_complete':row['independent_complete'],'selection_complete':s['selection_complete'],'original_emitted_not_reselected':True,'panels':panels});noriginal+=1
   del checker,members,candidate_pools,pending
 finally:
  for f in outputs.values():f.close()
 # All original independent slots, including18 unknowns/missing rows, are copied
 # without changing completion flags or substituting larger-tier derivations.
 (out/'ORACLE_SLOTS_UNCHANGED.json').write_text(json.dumps(slots,sort_keys=True,indent=2)+'\n')
 if nrows!=report['offered_run_rows']:raise ValueError('replay offered denominator differs from authoritative evaluator; unsupported domain rows require explicit handling, never deletion')
 manifest={'schema':'sg-selector-replay-manifest-v1','evaluator_implementation':{'path':str(Path(E.__file__).resolve()),'sha256':E.sha(Path(E.__file__))},'prepared_from_authoritative_evaluator':str(evaluation),'authoritative_report_sha256':E.sha(evaluation/'REPORT.json'),'authoritative_quality_rows_sha256':E.sha(quality_file),'authoritative_errors':report.get('independent_reconstruction_errors'),'authoritative_native_counterexamples':report.get('native_contract_counterexamples'),'builder_sha256':E.sha(Path(__file__)),'candidate_rows':nrows,'unique_native_candidate_pools':npools,'common_pool_members':nmembers,'original_emitted_selections':noriginal,'oracle_slots_retained':len(slots),'oracle_complete_slots_retained':sum(s['complete'] for s in slots),'inputs':consumed,'outputs':{p.name:E.sha(p) for p in sorted(out.iterdir()) if p.is_file()},'limitations':['No router or timing experiment is run by this helper.','Offline candidate inputs are final witnesses, independent of chosen display; common/LOFO references remain separate.','Identical candidate sets across timing blocks/selectors are deduplicated for replay, but every offered run row remains mapped.','Reference union and LOFO are incomplete; preserve negative signed LOFO differences as pool deficiency, not better-than-global regret.','Outside-domain stress has no bounded-selector guarantee.','Top5 emitted controls are not new equal-work top5 serving latency observations.']}
 (out/'MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');print(json.dumps({'candidate_rows':nrows,'candidate_pools':npools,'members':nmembers,'original_selections':noriginal,'oracle_slots':len(slots)}))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--campaign',action='append',required=True);p.add_argument('--evaluation',required=True);p.add_argument('--out',required=True);p.add_argument('--evaluator');a=p.parse_args();build(a.campaign,a.evaluation,Path(a.out),a.evaluator)
