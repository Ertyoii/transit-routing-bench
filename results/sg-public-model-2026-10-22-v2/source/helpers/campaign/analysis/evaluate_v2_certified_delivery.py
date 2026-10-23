#!/usr/bin/env python3
"""Certified single-limit serving delivery revision of bounded-memory v2.

Additive evaluator only: accepted evaluate_v2.py and bounded-memory ad875c60
remain immutable. The legacy selected_ids helper is retained unchanged for
historical/synthetic parity; evaluate uses the fail-closed selected_delivery_ids
helper, exact config/input/source bindings, and explicit top3/top5 cohorts.
No reference-only historical import is implemented. All declared serving runs
and exact scalar references contribute to one common independently feasible
pool; every offered row remains in its requested delivery-k denominator.
"""
import argparse,collections,hashlib,importlib.util,json,math,statistics,re
from array import array
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
gspec=importlib.util.spec_from_file_location('v2_gate',ROOT/'harness/campaign_gate.py');gate=importlib.util.module_from_spec(gspec);gspec.loader.exec_module(gate)
spec=importlib.util.spec_from_file_location('legacy_checker',ROOT.parent/'evalkit/evalkit.py');legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  while chunk:=f.read(1024*1024):h.update(chunk)
 return h.hexdigest()
def read(p):return legacy.read_json(p)[0]
def dist(xs):
 xs=sorted(xs);n=len(xs)
 return {'count':n,'p50':xs[math.ceil(n*.5)-1] if n else None,'p95':xs[math.ceil(n*.95)-1] if n else None,'p99':xs[math.ceil(n*.99)-1] if n else None,'max':xs[-1] if n else None,'mean':statistics.fmean(xs) if n else None,'method':'empirical nearest rank, not population/SLA'}
def flag(args,name):
 i=args.index(name);return args[i+1]
def identity(v):return json.dumps(json.loads(v),sort_keys=True,separators=(',',':'),ensure_ascii=False)
def family(name):
 if name.startswith('mc_raptor'):return 'McRAPTOR'
 if name.startswith('raptor'):return 'RAPTOR'
 if name.startswith('ultra'):return 'ULTRA_capped' if 'capped' in name or 'subset' in name else 'ULTRA_native'
 if name.startswith('trip_based'):return 'TripBased'
 if name.startswith('tp_') or name in ('transfer_patterns','scalable_tp'):return 'TransferPatterns'
 if name.startswith('trex'):return 'TREX'
 if name.startswith('flash'):return 'FLASH'
 return name

def selected_ids(row):
 q=row.get('recommendation_quality') or {};c=q.get('continuous_choices')
 if c is not None:
  for s in c.get('selections',[]):
   if s.get('limit')==3:
    if not c.get('complete') or not s.get('complete'):raise ValueError('requested continuous top3 selection incomplete')
    return s.get('selected',[])
  raise ValueError('requested continuous top3 selection absent')
 choices=q.get('choices') or {}
 if choices and choices.get('complete') is not True:raise ValueError('requested finite selection incomplete')
 for g in choices.get('groups',[]):
  for s in g.get('selections',[]):
   if s.get('limit')==3 and s.get('method')=='preference_minimax':
    if s.get('complete') is not True:raise ValueError('requested finite top3 incomplete')
    return s.get('selected',[])
 for s in q.get('selections',[]):
  if s.get('limit')==3 and s.get('score_envelope_seconds')==300:return s.get('selected',[])
 opts=row.get('display_options',{}).get('3',{}).get('options',[])
 return [v['journey']['identity'] for v in opts]


ACCEPTED_BOUNDED_SHA256='ad875c60a90dedcb1c63b1bee6eaa8415b63d92c9a61bce4467c1149f91d5e15'
ACCEPTED_ORIGINAL_SHA256='499ede17fbf04a7bb5b2904b8f5929c816cdafc7952c7bb1e0be1278aec2551e'


def normalize_serving_config(config):
 """Compare full Go config values, permitting only known omitted zero fields.

 File bytes need not contain groups:null or omitted false/zero struct members.
 Unknown fields fail closed until their consuming source schema is reviewed.
 """
 defaults={'lean_delivery':False,'delivery_policy':'','delivery_limits':None,'bounded':None,
           'max_subsets':0,'max_candidates':0,'groups':None}
 if not isinstance(config,dict) or set(config)-set(defaults):raise ValueError('unknown/malformed serving config fields')
 out={**defaults,**config}
 if out['bounded'] is not None:
  fields={'min_transfer_seconds':0,'max_transfer_seconds':0,'min_extra_walk_weight':0,
          'max_extra_walk_weight':0,'objective':'','limits':None,'distinct_patterns':False,
          'nested':False,'max_critical_points':0,'max_work':0,'max_matrix_bytes':0,
          'exact_subset_search':False}
  if not isinstance(out['bounded'],dict) or set(out['bounded'])-set(fields):raise ValueError('unknown/malformed bounded config fields')
  out['bounded']={**fields,**out['bounded']}
 if out['groups'] is not None:
  if not isinstance(out['groups'],list):raise ValueError('malformed serving groups')
  groups=[]
  for group in out['groups']:
   fields={'name':'','description':'','preferences':None}
   if not isinstance(group,dict) or set(group)-set(fields):raise ValueError('unknown/malformed serving group fields')
   g={**fields,**group}
   if g['preferences'] is not None:
    if not isinstance(g['preferences'],list):raise ValueError('malformed preferences')
    ps=[]
    for pref in g['preferences']:
     pf={'id':'','transfer_seconds':0,'extra_walk_weight':0}
     if not isinstance(pref,dict) or set(pref)-set(pf):raise ValueError('unknown/malformed preference fields')
     ps.append({**pf,**pref})
    g['preferences']=ps
   groups.append(g)
  out['groups']=groups
 return out


def serving_argv(argv):
 """Only output location may differ after runner placeholder expansion."""
 out=[];i=0
 while i<len(argv):
  if argv[i]=='-out-dir':
   if i+1>=len(argv):raise ValueError('missing output directory')
   i+=2
  else:out.append(argv[i]);i+=1
 return out


def delivery_config(config,requested='per-run'):
 """Return exact single serving k and certified schema, never default k3."""
 if not isinstance(config,dict):raise ValueError('serving preference config missing')
 bounded=config.get('bounded')
 if bounded is not None:
  if not isinstance(bounded,dict):raise ValueError('bounded config is not an object')
  if config.get('lean_delivery'):raise ValueError('mixed bounded/legacy lean delivery config')
  limits=bounded.get('limits');kind='bounded'
 else:
  if config.get('lean_delivery') is not True or config.get('delivery_policy')!='finite_preferences_v2':
   raise ValueError('certified serving requires bounded or finite_preferences_v2; legacy pattern selection has no completion certificate')
  limits=config.get('delivery_limits');kind='finite'
 if not isinstance(limits,list) or len(limits)!=1 or type(limits[0]) is not int or limits[0] not in (3,5):
  raise ValueError('serving requires explicit exact single delivery limit [3] or [5], not absent/mixed/joint work')
 k=limits[0]
 if requested!='per-run' and (type(requested) is not int or requested!=k):raise ValueError('requested delivery-k differs from frozen serving config')
 if kind=='finite' and (not isinstance(config.get('groups'),list) or len(config['groups'])!=1):
  raise ValueError('one certified serving preference group is required')
 return k,kind


def validate_delivery_binding(summary,command,args,requested,inputs):
 """Bind declared k to exact config file, supervisor input and native summary."""
 if args.count('-quality')!=1 or args.count('-display-k')!=1 or args.count('-preference-scenarios')!=1 or any(a.startswith(('-quality=','-display-k=','-preference-scenarios=')) for a in args) or flag(args,'-display-k')!='-1':
  raise ValueError('certified serving requires quality and no evaluation-only display ranking')
 path=Path(flag(args,'-preference-scenarios')).resolve()
 config=read(path);digest=sha(path);inputs[str(path)]=digest
 k,kind=delivery_config(config,requested)
 if summary:
  if summary.get('quality_enabled') is not True:raise ValueError('serving summary quality disabled')
  if summary.get('preference_config_sha256')!=digest:raise ValueError('serving preference config SHA mismatch')
  if normalize_serving_config(summary.get('preference_config'))!=normalize_serving_config(config):
   raise ValueError('parsed summary preference config differs from exact hash-bound config')
  sk,skind=delivery_config(summary.get('preference_config'),k)
  if (sk,skind)!=(k,kind):raise ValueError('summary delivery schema differs')
  if summary.get('display_k'):raise ValueError('unrequested display ranking controls were timed')
  actual=command.get('argv',[])
  if len(actual)<4 or actual[:2]!=['/usr/bin/taskset','-c'] or serving_argv(actual[3:])!=serving_argv(args):
   raise ValueError('consuming supervisor argv differs from frozen serving argv')
  recorded=[entry for entry in command.get('inputs',[]) if Path(entry.get('path','')).resolve()==path]
  if len(recorded)!=1 or recorded[0].get('sha256')!=digest or recorded[0].get('bytes')!=path.stat().st_size:
   raise ValueError('supervisor serving config input binding missing/different')
 return k,kind


def selected_delivery_ids(row,config,k):
 """Only a present, complete, exactly requested native selection may serve."""
 actual,kind=delivery_config(config,k)
 q=row.get('recommendation_quality')
 if not isinstance(q,dict):raise ValueError('requested certified selection missing')
 if kind=='bounded':
  if q.get('choices') is not None or q.get('selections'):raise ValueError('unrequested finite/legacy controls in bounded serving response')
  choices=q.get('continuous_choices')
  if not isinstance(choices,dict) or choices.get('complete') is not True or choices.get('error'):
   raise ValueError('requested continuous top%d choices absent/incomplete'%k)
  output_config=dict(config,bounded=choices.get('config'))
  if normalize_serving_config(output_config)!=normalize_serving_config(config):raise ValueError('continuous output config differs')
  selections=choices.get('selections')
 else:
  if q.get('continuous_choices') is not None or q.get('selections'):raise ValueError('unrequested bounded/legacy controls in finite serving response')
  choices=q.get('choices')
  if not isinstance(choices,dict) or choices.get('complete') is not True or choices.get('error'):
   raise ValueError('requested finite top%d choices absent/incomplete'%k)
  groups=choices.get('groups')
  if not isinstance(groups,list) or len(groups)!=1 or normalize_serving_config(dict(config,groups=[groups[0].get('group')]))!=normalize_serving_config(config):
   raise ValueError('finite serving group differs/missing')
  selections=groups[0].get('selections')
 if not isinstance(selections,list) or len(selections)!=1:raise ValueError('missing/duplicate/mixed-limit serving selections')
 selection=selections[0]
 if selection.get('limit')!=k or type(selection.get('limit')) is not int or selection.get('complete') is not True:
  raise ValueError('requested top%d selection limit/completion mismatch'%k)
 if kind=='finite' and selection.get('method')!='preference_minimax':raise ValueError('wrong finite serving method')
 ids=selection.get('selected')
 if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or len(ids)>k:
  raise ValueError('selected top%d identities missing/malformed/over limit'%k)
 if row.get('final') and not ids:raise ValueError('complete nonempty pool has empty serving selection')
 return ids


def accumulate_delivery_quality_row(buckets,row):
 """Same exact bounded-memory arithmetic, with delivery-k in grouping key."""
 for panel,key in [('full','score'),('leave_family_out','leave_donor_family_out_signed')]:
  v=row[key];b=buckets.setdefault((row['dataset_sha256'],row['window'],row['variant_id'],row['delivery_k'],row['stage'],row['stratum'],panel),{'rows':0,'complete':0,'eligible':0,'covered':0,'missing':0,'counterexamples':0,'regrets':ExactRegretSamples(),'normalized':array('d')})
  b['rows']+=1;b['complete']+=row['complete'];b['eligible']+=v.get('eligible',0);b['covered']+=v.get('covered',0);b['missing']+=v.get('eligible',0) if v.get('missing') else 0;b['counterexamples']+=v.get('counterexample_slots',0);b['regrets'].extend(v.get('regrets',[]));b['normalized'].extend(v.get('normalized_regrets',[]))

def cost(v,w):return v['duration_seconds']+w['transfer_seconds']*v['metrics']['transfers']+w['extra_walk_weight']*v['metrics']['walking_seconds']
def score_stage(candidates,reference,weights,completed):
 eligible=len(weights) if reference else 0
 if not reference:return {'eligible':0,'reference_empty_or_unavailable':True,'missing':False,'regrets':[]}
 if not completed or not candidates:return {'eligible':eligible,'missing':True,'regrets':[],'covered':0}
 ds=[];rels=[];covered=0
 for w in weights:
  best=min(cost(j,w) for j in reference);got=min(cost(j,w) for j in candidates);delta=got-best;tol=1e-7*max(1,abs(best));covered+=delta<=tol;ds.append(delta);rels.append(delta/(1+best))
 return {'eligible':eligible,'missing':False,'covered':covered,'regrets':ds,'normalized_regrets':rels,'counterexample_slots':sum(x< -1e-7 for x in ds),'within30':sum(x<=30+1e-7 for x in ds),'within60':sum(x<=60+1e-7 for x in ds),'within120':sum(x<=120+1e-7 for x in ds),'within1percent':sum(x<=.01+1e-7 for x in rels),'within5percent':sum(x<=.05+1e-7 for x in rels)}


class JsonArraySink:
 """Stream the exact json.dumps(..., indent=2, sort_keys=True) array bytes.

 Only one record is live; iterencode avoids another whole-record JSON string.
 A directory is complete evidence only when its final REPORT.json exists.
 """
 def __init__(self,path):
  self.file=Path(path).open('w');self.count=0;self.offered=0
  self.encoder=json.JSONEncoder(indent=2,sort_keys=True)
 def append(self,value):
  self.file.write('[\n' if not self.count else ',\n');self.file.write('  ')
  for chunk in self.encoder.iterencode(value):self.file.write(chunk.replace('\n','\n  '))
  self.count+=1;self.offered+=value.get('offered',0)
 def __len__(self):return self.count
 def close(self):
  self.file.write('\n]\n' if self.count else '[]\n');self.file.close()


class JsonlSink:
 def __init__(self,path):self.file=Path(path).open('w')
 def append(self,value):self.file.write(json.dumps(value,separators=(',',':'))+'\n')
 def close(self):self.file.close()


class ExactRegretSamples(array):
 """Compact doubles plus sparse original-integer tags for byte-exact JSON.

 A few frozen boundary preferences use integer weights, so even tied zero
 quantiles must preserve stable-sort int-versus-float identity. Rare integers
 outside exact binary64 range have a sparse lossless fallback, never rounding.
 """
 def __new__(cls):return super().__new__(cls,'d')
 def __init__(self):self.integer_slots=array('Q');self.exact_integers={}
 def extend(self,values):
  for value in values:
   index=len(self)
   if type(value) is int:
    self.integer_slots.append(index)
    try:stored=float(value)
    except OverflowError:stored=0.0
    if not math.isfinite(stored) or int(stored)!=value:self.exact_integers[index]=value
   else:stored=value
   super().append(stored)
 def __iter__(self):
  positions=iter(self.integer_slots);integer_slot=next(positions,None)
  for index,value in enumerate(super().__iter__()):
   if index==integer_slot:
    yield self.exact_integers.get(index,int(value));integer_slot=next(positions,None)
   else:yield value


def accumulate_quality_row(buckets,row):
 """Same insertion order and counters as v2; exact samples, not sketches.

 array('d') retains every float bit while avoiding Python-float objects and
 duplicate pointer lists. Sparse type tags preserve integer boundary samples.
 Quantiles still call the unchanged dist(), including sorted-order fmean.
 """
 for panel,key in [('full','score'),('leave_family_out','leave_donor_family_out_signed')]:
  v=row[key];b=buckets.setdefault((row['dataset_sha256'],row['window'],row['variant_id'],row['stage'],row['stratum'],panel),{'rows':0,'complete':0,'eligible':0,'covered':0,'missing':0,'counterexamples':0,'regrets':ExactRegretSamples(),'normalized':array('d')})
  b['rows']+=1;b['complete']+=row['complete'];b['eligible']+=v.get('eligible',0);b['covered']+=v.get('covered',0);b['missing']+=v.get('eligible',0) if v.get('missing') else 0;b['counterexamples']+=v.get('counterexample_slots',0);b['regrets'].extend(v.get('regrets',[]));b['normalized'].extend(v.get('normalized_regrets',[]))


def compact_quality_row(row):
 for panel in ['score','leave_donor_family_out_signed']:
  value=row[panel];value['regret_score_seconds']=dist(value.pop('regrets',[]));value['normalized_regret']=dist(value.pop('normalized_regrets',[]))
 return row

def validate_summary_binding(summary,command,algorithm,dataset_sha,workload_sha):
 if summary.get('algorithm')!=algorithm or summary.get('dataset_sha256')!=dataset_sha or summary.get('queries_sha256')!=workload_sha:raise ValueError('summary algorithm/dataset/workload binding mismatch')
 prov=summary.get('provenance',{})
 for key in ['build_source_sha256','runtime_tree_sha256','routing_source_sha256','executable_sha256']:
  if not isinstance(prov.get(key),str) or not re.fullmatch('[0-9a-f]{64}',prov[key]):raise ValueError('missing/invalid provenance digest '+key)
 if prov.get('source_binding')!='embedded_build_source':raise ValueError('unbound executable source')
 if not prov.get('runtime_matches_build') or prov.get('build_source_sha256')!=prov.get('runtime_tree_sha256'):raise ValueError('summary source/build mismatch')
 if command:
  if prov.get('executable_sha256')!=command.get('binary',{}).get('sha256'):raise ValueError('summary binary mismatch')
  roots=command.get('sources_before',[])
  if roots and prov.get('runtime_tree_sha256')!=roots[0].get('go_source_hash_sha256'):raise ValueError('summary source binding differs from supervisor')


def validate_pass_binding(payload,descriptor,algorithm,file):
 name=descriptor.get('file')
 if not isinstance(name,str) or Path(name).name!=name or name in ('.','..'):raise ValueError('unsafe pass filename')
 if sha(file)!=descriptor.get('sha256'):raise ValueError('pass SHA mismatch')
 if payload.get('algorithm')!=algorithm or payload.get('repetition')!=descriptor.get('repetition') or bool(payload.get('warmup'))!=bool(descriptor.get('warmup')):raise ValueError('pass algorithm/repetition/warmup mismatch')
 if not isinstance(payload.get('records'),list):raise ValueError('pass records not array')


def validate_row_timing(row):
 for k in ['response_ns','quality_ns','validation_rank_ns']:
  if not isinstance(row.get(k),int) or isinstance(row.get(k),bool) or row[k]<0:raise ValueError('invalid timing '+k)
 if not row['quality_ns']<=row['validation_rank_ns']<=row['response_ns']:raise ValueError('timing hierarchy')
 if row.get('core_ns') is not None and (not isinstance(row['core_ns'],int) or isinstance(row['core_ns'],bool) or row['core_ns']<0 or row['core_ns']+row['validation_rank_ns']>row['response_ns']):raise ValueError('core timing hierarchy')
 if row.get('published_response_ns') is not None:
  pub=row['published_response_ns'];ser=row.get('serialization_ns')
  if not isinstance(pub,int) or isinstance(pub,bool) or pub<row['response_ns']:raise ValueError('publication precedes computed response')
  if not isinstance(ser,int) or isinstance(ser,bool) or ser<0 or ser>pub-row['response_ns']:raise ValueError('invalid serialization timing')
 offsets=[row.get(k) for k in ['service_start_offset_ns','search_done_offset_ns','validation_start_offset_ns']]
 if any(v is not None for v in offsets):
  if not all(isinstance(v,int) and v>=0 for v in offsets) or offsets!=sorted(offsets) or offsets[-1]>row['response_ns'] or row['validation_rank_ns']!=row['response_ns']-offsets[-1]:raise ValueError('timing offsets')
  if row.get('core_ns') is not None and row['core_ns']>offsets[1]-offsets[0]:raise ValueError('core exceeds search interval')


def validate_oracle_slot(z,header,expected,weights,seen):
 q=z['query'];key=q['id'];index=z.get('weight_index')
 if key not in expected or q!=expected[key]:raise ValueError('oracle query differs from frozen workload')
 if not isinstance(index,int) or isinstance(index,bool) or index<0 or index>=len(weights) or z.get('weight')!=weights[index]:raise ValueError('oracle weight/index mismatch')
 slot=(key,index)
 if slot in seen:raise ValueError('duplicate oracle slot')
 seen.add(slot)
 return slot

def first_answer_acceptance(supervisor,rows):
 """Preserve emitter timing; qualify it only if that exact native row survives.

 Stream payload equivalence remains a separately required receipt audit. We must
 not reinterpret a later successful answer as the first marker after a falsifier.
 """
 events=supervisor.get('first_available_answer_events') or []
 result={'accepted_native_launch_to_first_available_answer_ns':None,'first_published_native_row_accepted':False,'first_answer_acceptance_scope':'exact first emitted marker row after independent feasibility/display/native falsification; stream payload equivalence audited separately'}
 ordinary=[x for x in rows if x.get('row') and type(x['row'].get('batch')) is int and x['row']['batch']>=0]
 if ordinary:
  batch=min(x['row']['batch'] for x in ordinary);first_batch=[x for x in ordinary if x['row']['batch']==batch]
  result['first_offered_batch_query_ids']=sorted(x['query']['id'] for x in first_batch)
  if len(first_batch)==1:
   first=first_batch[0];result.update(first_offered_query_id=first['query']['id'],first_offered_independent_status=first['status'],first_offered_native_complete=first['complete'])
 if len(events)!=1:
  result['first_answer_unavailable_reason']='missing_or_nonunique_publication_event';return result
 event=events[0];marker=event.get('payload') or {};qid=marker.get('query_id');matches=[x for x in rows if x['query']['id']==qid]
 result['first_published_query_id']=qid
 result['first_marker_matches_first_offered_query']=qid==result.get('first_offered_query_id') if result.get('first_offered_query_id') is not None else None
 if len(matches)!=1 or not matches[0]['complete']:
  result['first_answer_unavailable_reason']='first_published_row_not_independently_complete';return result
 row=matches[0]['row']
 clocks=[event.get('supervisor_received_since_spawn_ns'),marker.get('process_elapsed_ns'),marker.get('published_response_ns'),marker.get('serialization_ns')]
 if (not supervisor.get('publication_receipt',{}).get('valid') or not row
     or not all(type(value) is int and value>=0 for value in clocks)
     or not clocks[0]>=clocks[1]>=clocks[2]>=clocks[3]
     or marker.get('published_response_ns')!=row.get('published_response_ns')
     or marker.get('serialization_ns')!=row.get('serialization_ns')
     or supervisor.get('launch_to_first_available_answer_ns')!=event.get('supervisor_received_since_spawn_ns')):
  result['first_answer_unavailable_reason']='first_marker_pass_or_receipt_binding_mismatch';return result
 result.update(accepted_native_launch_to_first_available_answer_ns=supervisor.get('launch_to_first_available_answer_ns'),first_published_native_row_accepted=True,first_answer_unavailable_reason=None)
 return result


def evaluate(campaigns,oracle_globs,out,delivery_mode):
 if delivery_mode not in (3,5,'per-run'):raise ValueError('explicit delivery mode must be3,5,or per-run')
 for name,expected in [('evaluate_v2.py',ACCEPTED_ORIGINAL_SHA256),('evaluate_v2_bounded_memory.py',ACCEPTED_BOUNDED_SHA256)]:
  if sha(Path(__file__).with_name(name))!=expected:raise ValueError('accepted evaluator source changed: '+name)
 out.mkdir(parents=True,exist_ok=False)
 held=read(ROOT/'selector-quality/configs/heldout393.json');scalar=read(ROOT/'selector-quality/configs/scalar9.json')
 scalar=scalar.get('weights',scalar) if isinstance(scalar,dict) else scalar
 expected_queries={};scope={};runs=[];pool=collections.defaultdict(dict);errors=[];inputs={};oracle_slots=[];oracle_semantic_slots=set();cohort_offered=collections.Counter()
 for dependency in [Path(__file__),Path(__file__).with_name('evaluate_v2.py'),Path(__file__).with_name('evaluate_v2_bounded_memory.py'),ROOT.parent/'evalkit/evalkit.py',ROOT/'selector-quality/configs/heldout393.json',ROOT/'selector-quality/configs/scalar9.json',ROOT/'selector-quality/PREFERENCE_SEAL.json']:
  if dependency.is_file():inputs[str(dependency)]=sha(dependency)
 seal_path=ROOT/'selector-quality/PREFERENCE_SEAL.json'
 if seal_path.exists():
  seal=read(seal_path)
  for name,digest in seal['files'].items():
   if sha(ROOT/'selector-quality/configs'/name)!=digest:raise ValueError('preference freeze seal mismatch')
 # One model/window at a time avoids loading many large static models at once.
 for campaign in campaigns:
  campaign=Path(campaign);plan=read(campaign/'plan.json');registry=gate.load_registry(plan,campaign);inputs[str(campaign/'plan.json')]=sha(campaign/'plan.json')
  for run in plan['runs']:
   args=run['argv'];dataset=Path(flag(args,'-dataset'));workload=Path(flag(args,'-queries'));dsha=sha(dataset);w=read(workload);expected={x['query']['id']:x for x in w['items']};unsupported_offers=[]
   if registry:
    registered=registry['by_path'].get(str(workload.resolve()))
    if registered is None:raise ValueError('unregistered evaluator workload')
    ledger_ref=registry['payload'].get('source_manifest')
    if ledger_ref:
     ledger_path=Path(ledger_ref['path']);ledger=read(ledger_path)
     for offered in ledger.get('files',[]):
      if Path(offered['path']).resolve()==workload.resolve():
       if offered['sha256']!=sha(workload) or offered['metadata_sha256']!=registered['metadata']['sha256']:raise ValueError('offered ledger binding changed')
       unsupported_offers=offered.get('unsupported',[])
       if offered['offered']!=len(expected)+len(unsupported_offers):raise ValueError('offered ledger denominator mismatch')
       inputs[str(ledger_path)]=sha(ledger_path)
       break
   alg=flag(args,'-algorithm');kind=family(alg);rid=run['id'];folder=campaign/rid;result=read(folder/'result.json') if (folder/'result.json').exists() else {}
   key=(dsha,str(dataset));scope[key]=dataset
   recs={};artifact=folder/'artifact';summary=read(artifact/'summary.json') if (artifact/'summary.json').exists() else {}
   command=read(folder/'command.json') if (folder/'command.json').exists() else {}
   for dependency in [workload,artifact/'summary.json',folder/'command.json',folder/'result.json']:
    if dependency.exists():inputs[str(dependency)]=sha(dependency)
   if summary:validate_summary_binding(summary,command,alg,dsha,sha(workload))
   delivery_k,delivery_schema=validate_delivery_binding(summary,command,args,delivery_mode,inputs)
   for p in summary.get('passes',[]):
    if p.get('forced') or p.get('warmup'):continue
    file=artifact/p['file']
    if file.exists():
     payload=read(file);validate_pass_binding(payload,p,alg,file);inputs[str(file)]=sha(file)
     for r in payload['records']:
      qid=r['query']['id']
      if qid in recs:raise ValueError('duplicate ordinary query in run')
      recs[qid]=r
   if set(recs)-set(expected):raise ValueError('unknown offered query')
   rowset=[]
   for qid,x in expected.items():
    r=recs.get(qid)
    if r and (r['query']!=x['query'] or r.get('stratum')!=x.get('stratum')):raise ValueError('frozen query or stratum changed')
    expected_queries[(dsha,qid)]=x['query']
    rowset.append({'query':x['query'],'stratum':x['stratum'],'row':r,'final':[],'raw':[],'display':[],'complete':bool(r and r.get('completed')),'status':r.get('status') if r else 'unresolved_outer_process','dataset_sha256':dsha})
   if unsupported_offers:
    source_path=ROOT/'data-workload/workloads/phase_hash_a_conservative600'/workload.name
    source_queries={x['query']['id']:x for x in read(source_path)['items']}
    for offer in unsupported_offers:
     qid=offer['query_id']
     if qid in expected or qid not in source_queries:raise ValueError('unsupported offered ID missing/duplicated')
     source=source_queries[qid]
     rowset.append({'query':source['query'],'stratum':offer['cohort'],'row':None,'final':[],'raw':[],'display':[],'complete':False,'status':offer['status'],'dataset_sha256':dsha,'unsupported_endpoint_offer':True})
   runs.append({'id':rid,'delivery_k':delivery_k,'display_label':'top%d'%delivery_k,'delivery_schema':delivery_schema,'variant_id':run.get('variant_id',rid),'window':run.get('window'),'algorithm':alg,'family':kind,'dataset':str(dataset),'dataset_sha256':dsha,'workload':str(workload),'campaign':str(campaign),'summary':{k:summary[k] for k in ['quality_enabled','preference_config'] if k in summary},'_summary_source':str(artifact/'summary.json') if summary else None,'supervisor':result,'rows':rowset})
   # Retain validation configuration only; exact preparation payloads are reloaded
   # from the same hash-bound artifact during streamed METRICS output.
   summary=None;payload=None;recs=None;command=None;result=None
 # Reconstruct all supplied candidate and raw witnesses using independent Python rules.
 for (dsha,_),dataset in scope.items():
  checker=legacy.Checker(read(dataset));inputs[str(dataset)]=dsha
  related=[r for r in runs if r['dataset_sha256']==dsha]
  for run in related:
   for item in run['rows']:
    r=item['row'];q=item['query']
    if not r:continue
    checker.query(q)
    try:
     validate_row_timing(r)
     if any(type(r.get(k)) is not bool for k in ['attempted','completed','valid_empty','transit']):raise ValueError('invalid outcome boolean')
     if r['completed'] and (not r['attempted'] or r['status']!='complete'):raise ValueError('completed outcome inconsistent')
    except ValueError as exc:errors.append({'run':run['id'],'query_id':q['id'],'stage':'outcome_timing','error':str(exc)});item['complete']=False
    for stage,key in [('raw','raw'),('final','final')]:
     seen={}
     for j in r.get(key,[]):
      try:
       v=checker.check(q,j);iv=identity(v['identity'])
       if iv in seen and stage=='final':raise ValueError('duplicate final identity')
       seen[iv]=v
      except (legacy.ValidationError,KeyError,ValueError,TypeError) as exc:
       errors.append({'run':run['id'],'query_id':q['id'],'stage':stage,'error':str(exc)});item['complete']=False
     item[stage]=list(seen.values())
    if r.get('valid_empty')!=(r.get('completed') and not item['final']):
     errors.append({'run':run['id'],'query_id':q['id'],'stage':'outcome','error':'valid_empty mismatch'});item['complete']=False
    independently_transit=bool(r.get('completed') and any(v['metrics']['boardings'] for v in item['final']))
    if r.get('transit')!=independently_transit:errors.append({'run':run['id'],'query_id':q['id'],'stage':'outcome','error':'transit mismatch'});item['complete']=False
    item['independent_transit']=independently_transit
    by={identity(j['identity']):j for j in item['final']}
    try:
     cfg=run['summary'].get('preference_config') or {};quality=r.get('recommendation_quality')
     if r.get('completed') and run['summary'].get('quality_enabled'):
      if quality is None:raise ValueError('requested quality output missing')
      if cfg.get('bounded') is not None and quality.get('continuous_choices') is None:raise ValueError('requested continuous selection missing')
      if cfg.get('delivery_policy')=='finite_preferences_v2' and not quality.get('choices'):raise ValueError('requested finite selection missing')
      if cfg.get('delivery_policy')=='pattern_anchors_v1' and not quality.get('selections'):raise ValueError('requested pattern selection missing')
     ids=selected_delivery_ids(r,cfg,run['delivery_k']) if r.get('completed') else [];item['display']=[by[identity(i)] for i in ids]
     if len(ids)>run['delivery_k'] or len({identity(i) for i in ids})!=len(ids):raise ValueError('requested top%d display count/duplicate'%run['delivery_k'])
    except (KeyError,ValueError,TypeError) as exc:errors.append({'run':run['id'],'query_id':q['id'],'stage':'display','error':str(exc)});item['complete']=False
    if r.get('completed') and not item['complete'] and item['status']=='complete':
     item['emitter_status']=item['status'];item['status']='independent_validation_error'
    for v in item['raw']+item['final']:
     pk=(dsha,q['id']);iv=identity(v['identity']);entry=pool[pk].setdefault(iv,{'journey':v,'families':set(),'contributors':set()});entry['families'].add(run['family']);entry['contributors'].add(run['variant_id'])
  import glob
  for path in sorted({str(Path(p).resolve()) for pattern in oracle_globs for p in glob.glob(pattern)}):
   if True:
    with open(path) as f:
     first=json.loads(next(f))
     if first.get('dataset_sha256')!=dsha:continue
     if first.get('kind')!='metadata' or first.get('weights_sha256')!=sha(ROOT/'selector-quality/configs/scalar9.json'):raise ValueError('oracle header weight binding mismatch')
     oracle_workload=None
     for candidate in (ROOT/'data-workload/workloads').rglob('*.reference.primary_1h_walk600.json'):
      if sha(candidate)==first.get('workload_sha256'):oracle_workload=read(candidate);break
     if oracle_workload is None or oracle_workload['dataset_sha256']!=dsha:raise ValueError('oracle header workload binding missing')
     oracle_expected={x['query']['id']:x['query'] for x in oracle_workload['items']};seen_oracle_slots=set()
     inputs[path]=sha(path)
     for line in f:
      z=json.loads(line)
      if z.get('kind')!='scalar_result':continue
      q=z['query'];res=z['result']
      slot_key=validate_oracle_slot(z,first,oracle_expected,scalar,seen_oracle_slots)
      semantic=(dsha,first['workload_sha256'],first['weights_sha256'],*slot_key)
      if semantic in oracle_semantic_slots:raise ValueError('duplicate oracle semantic slot across files')
      oracle_semantic_slots.add(semantic)
      if (dsha,q['id']) not in expected_queries:continue
      if q!=expected_queries[(dsha,q['id'])]:raise ValueError('oracle query differs from frozen offered query')
      slot={'dataset_sha256':dsha,'query_id':q['id'],'weight':z.get('weight'),'complete':res.get('complete',False),'found':res.get('found',False),'error':z.get('error'),'source':path}
      if res.get('complete') and res.get('found'):
       try:
        v=checker.check(q,res['journey']);slot['journey']=v;slot['score_seconds']=res.get('score_seconds')
        if abs(cost(v,z['weight'])-res['score_seconds'])>1e-7:raise ValueError('oracle score differs from independently reconstructed witness')
        iv=identity(v['identity']);entry=pool[(dsha,q['id'])].setdefault(iv,{'journey':v,'families':set(),'contributors':set()});entry['families'].add('independent_scalar_oracle');entry['contributors'].add('independent_scalar_oracle')
       except (legacy.ValidationError,KeyError,ValueError,TypeError) as exc:errors.append({'oracle':path,'query_id':q['id'],'error':str(exc)});slot['complete']=False
      oracle_slots.append(slot)
     # Expand the header-bound frozen request x weight product, not emitted rows.
     for qid,q in oracle_expected.items():
      if (dsha,qid) not in expected_queries:continue
      for wi,weight in enumerate(scalar):
       if (qid,wi) not in seen_oracle_slots:
        oracle_slots.append({'dataset_sha256':dsha,'query_id':qid,'weight':weight,'complete':False,'found':False,'error':'unresolved_missing_oracle_output','source':path})
  del checker
 # Apply independent finite-witness counterexamples before any success aggregation.
 native_counterexamples=[]
 for run in runs:
  for x in run['rows']:
   ref=[e['journey'] for e in pool[(run['dataset_sha256'],x['query']['id'])].values()]
   before=len(native_counterexamples)
   if x['complete'] and x['row']:
    certificates=x['row'].get('certificates',{})
    if certificates.get('arrival_boardings'):
     for witness in ref:
      cap=witness['metrics']['boardings'];want=witness['metrics']['arrival'];got=min((j['metrics']['arrival'] for j in x['final'] if j['metrics']['boardings']<=cap),default=None)
      if got is None or got>want:native_counterexamples.append({'run':run['id'],'query_id':x['query']['id'],'contract':'arrival_under_boarding_cap','cap':cap,'emitted_best':got,'independent_feasible_arrival':want,'reference_identity':witness['identity']})
    if certificates.get('arrival_boardings_walking'):
     for witness in ref:
      v=(witness['metrics']['arrival'],witness['metrics']['boardings'],witness['metrics']['walking_seconds'])
      if not any(all(a<=b for a,b in zip((j['metrics']['arrival'],j['metrics']['boardings'],j['metrics']['walking_seconds']),v)) for j in x['final']):native_counterexamples.append({'run':run['id'],'query_id':x['query']['id'],'contract':'3d_frontier_not_dominated','reference_vector':v,'reference_identity':witness['identity']})
   if len(native_counterexamples)>before:
    x['complete']=False;x['emitter_status']=x['status'];x['status']='native_contract_counterexample'
 # Score all native stages against fixed union and donor-family-excluded references.
 quality=JsonlSink(out/'QUALITY_ROWS.jsonl');metrics=JsonArraySink(out/'METRICS_BY_RUN.json');oracle_comparisons=JsonArraySink(out/'ORACLE_COMPARISONS.json');buckets={}
 oracle_by_query=collections.defaultdict(list)
 for slot in oracle_slots:oracle_by_query[(slot["dataset_sha256"],slot["query_id"])].append(slot)
 for run in runs:
  rows=run.pop('rows');run.pop('summary');summary_source=run.pop('_summary_source');sup=run.pop('supervisor')
  if summary_source and sha(summary_source)!=inputs[summary_source]:raise ValueError('summary changed before deferred metrics output')
  summary=read(summary_source) if summary_source else {}
  times=[x['row']['response_ns'] for x in rows if x['row'] and x['row'].get('attempted')];published=[x['row']['published_response_ns'] for x in rows if x['row'] and x['row'].get('published_response_ns') is not None]
  startup=sum(summary.get(k,{}).get('elapsed_ns',0) for k in ['preparation','checker_preparation','quality_preparation'])+summary.get('input_load_ns',0)
  accepted_first_answer=first_answer_acceptance(sup,rows)
  metric={**run,'offered':len(rows),'completed':sum(x['complete'] for x in rows),'statuses':dict(collections.Counter(x['status'] for x in rows)),'declared_native_valid_empty':sum(bool(x['row'] and x['row'].get('valid_empty')) for x in rows),'transit':sum(bool(x.get('independent_transit')) for x in rows),'all_attempted_response_ns':dist(times),'published_response_ns':dist(published),'published_deadline_misses':sum(bool(x['row'] and x['row'].get('published_response_ns',0)>summary.get('batch_deadline_ns',0)) for x in rows),'delivery_deadline_note':'publication deadline separately audited; historical compute response excludes serialization','complete_response_ns':dist([x['row']['response_ns'] for x in rows if x['complete']]),'transit_response_ns':dist([x['row']['response_ns'] for x in rows if x['complete'] and x.get('independent_transit')]),'common_pool_transit_response_ns':dist([x['row']['response_ns'] for x in rows if x['complete'] and any(e['journey']['metrics']['boardings'] for e in pool[(run['dataset_sha256'],x['query']['id'])].values())]),'startup_phase_sum_ns':startup,'preparation':summary.get('preparation'),'checker_preparation':summary.get('checker_preparation'),'quality_preparation':summary.get('quality_preparation'),'launch_to_first_available_answer_ns':sup.get('launch_to_first_available_answer_ns'),'sampled_peak_rss_bytes':sup.get('sampled_peak_process_group_rss_bytes'),'supervisor_ok':sup.get('ok'),'process_wall_s':sup.get('process_wall_s'),'source_sha256':summary.get('provenance',{}).get('runtime_tree_sha256')}
  metric.update(accepted_first_answer)
  metric.update(emitter_declared_transit=sum(bool(x['row'] and x['row'].get('transit')) for x in rows),independently_feasible_transit_rows_including_incomplete=sum(bool(x.get('independent_transit')) for x in rows),transit=sum(bool(x['complete'] and x.get('independent_transit')) for x in rows),independently_completed_empty_deliveries=sum(bool(x['complete'] and not x['final']) for x in rows))
  for x in rows:
   members=list(pool[(run['dataset_sha256'],x['query']['id'])].values())
   x['common_pool_cohort']='pool_has_transit' if any(e['journey']['metrics']['boardings'] for e in members) else 'pool_walk_only' if members else 'pool_empty_or_unknown'
  metric['common_pool_cohorts']={cohort:{'offered':sum(x['common_pool_cohort']==cohort for x in rows),'independently_complete':sum(x['common_pool_cohort']==cohort and x['complete'] for x in rows),'complete_response_ns':dist([x['row']['response_ns'] for x in rows if x['common_pool_cohort']==cohort and x['complete']])} for cohort in ['pool_has_transit','pool_walk_only','pool_empty_or_unknown']}
  cohort_offered[str(run['delivery_k'])]+=len(rows)
  metrics.append(metric);metric=None;summary=None
  for x in rows:
   pk=(run['dataset_sha256'],x['query']['id']);entries=list(pool[pk].values());ref=[e['journey'] for e in entries];outside=[e['journey'] for e in entries if e['families']-{run['family']}]
   for slot in oracle_by_query[pk]:
    for stage in ['raw','final','display']:
     row={'run':run['id'],'delivery_k':run['delivery_k'],'display_label':run['display_label'],'stage_label':run['display_label'] if stage=='display' else stage,'variant_id':run['variant_id'],'family':run['family'],'query_id':x['query']['id'],'stage':stage,'weight':slot['weight'],'reference_complete':slot['complete'],'reference_found':slot['found'],'candidate_complete':x['complete'],'candidate_found':bool(x[stage]),'reference_source':slot['source']}
     if slot['complete'] and slot['found'] and x['complete'] and x[stage]:
      got=min(cost(j,slot['weight']) for j in x[stage]);row.update(reference_optimum=slot['score_seconds'],candidate_best=got,signed_regret=got-slot['score_seconds'],normalized_regret=(got-slot['score_seconds'])/(1+slot['score_seconds']))
      if got<slot['score_seconds']-1e-7:errors.append({'run':run['id'],'query_id':x['query']['id'],'stage':stage,'error':'independently feasible candidate beats alleged complete scalar reference','delta':got-slot['score_seconds']})
     elif slot['complete'] and not slot['found'] and x['complete'] and x[stage]:errors.append({'run':run['id'],'query_id':x['query']['id'],'error':'feasible candidate contradicts complete scalar empty reference'})
     oracle_comparisons.append(row)
   for stage in ['raw','final','display']:
    score=score_stage(x[stage],ref,held,x['complete']);lofo=score_stage(x[stage],outside,held,x['complete'])
    quality_row={'run':run['id'],'delivery_k':run['delivery_k'],'display_label':run['display_label'],'stage_label':run['display_label'] if stage=='display' else stage,'variant_id':run['variant_id'],'algorithm':run['algorithm'],'family':run['family'],'dataset_sha256':run['dataset_sha256'],'query_id':x['query']['id'],'window':run['window'],'stratum':x['stratum'],'common_pool_cohort':x['common_pool_cohort'],'status':x['status'],'complete':x['complete'],'stage':stage,'pool_journeys':len(ref),'reference_scope':'incomplete union enriched by independently feasible scalar-oracle witnesses, not exhaustive393 optima','score':score,'leave_donor_family_out_signed':lofo,'candidate_patterns':len({j['pattern'] for j in x[stage]})}
    accumulate_delivery_quality_row(buckets,quality_row);quality.append(compact_quality_row(quality_row))
 quality.close();metrics.close();oracle_comparisons.close()
 aggregate=[]
 for (dataset_sha,window,variant,delivery_k,stage,stratum,panel),b in buckets.items():
  regrets=b.pop('regrets');normalized=b.pop('normalized');aggregate.append({'dataset_sha256':dataset_sha,'delivery_k':delivery_k,'display_label':'top%d'%delivery_k,'stage_label':'top%d'%delivery_k if stage=='display' else stage,'window':window,'variant_id':variant,'stage':stage,'stratum':stratum,'panel':panel,**b,'coverage':b['covered']/b['eligible'] if b['eligible'] else None,'regret_score_seconds':dist(regrets),'normalized_regret':dist(normalized),'negative_lofo_is_pool_deficiency_not_negative_global_regret':panel=='leave_family_out'})
 for name,value in [('QUALITY_AGGREGATE.json',aggregate),('INDEPENDENT_ORACLE_SLOTS.json',oracle_slots),('NATIVE_COUNTEREXAMPLES.json',native_counterexamples),('VALIDATION_ERRORS.json',errors)]: (out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
 report={'schema':'sg-independent-v2-certified-serving-delivery-v1','delivery_mode':delivery_mode,'delivery_contract':'Each serving run has exactly one frozen requested limit[3]or[5]; mixed/joint/legacy uncertified selection work is rejected; all offered rows retain their per-k denominator.','serving_cohort_offered':{str(k):cohort_offered[str(k)] for k in (3,5)},'accepted_bounded_source_sha256':ACCEPTED_BOUNDED_SHA256,'accepted_original_source_sha256':ACCEPTED_ORIGINAL_SHA256,'inputs':inputs,'offered_run_rows':metrics.offered,'runs':len(metrics),'independent_reconstruction_errors':len(errors),'native_contract_counterexamples':len(native_counterexamples),'oracle_offered_slots':len(oracle_slots),'oracle_complete_slots':sum(x['complete'] for x in oracle_slots),'oracle_scope':'Complete results establish only their exact9 weighted optima; pool enrichment does not establish393-profile/full3D completeness','limitations':['393 weights are frozen hypotheses, not passenger preference probabilities.','Union and leave-family-out pools are incomplete. Negative signed LOFO differences expose weaker pools, not better-than-global routing.','All offered errors/unknowns remain counted; model-empty lacks finite preference optimum.','Repeated process offers are not distinct OD demand.']};(out/'REPORT.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--campaign',action='append',required=True);p.add_argument('--oracle-glob',action='append',default=[]);p.add_argument('--out',required=True);p.add_argument('--delivery-k',choices=['3','5','per-run'],required=True);a=p.parse_args();evaluate(a.campaign,a.oracle_glob,Path(a.out),int(a.delivery_k) if a.delivery_k!='per-run' else 'per-run')
