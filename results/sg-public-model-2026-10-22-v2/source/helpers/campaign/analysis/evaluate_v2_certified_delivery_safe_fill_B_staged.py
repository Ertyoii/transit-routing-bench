#!/usr/bin/env python3
"""STATIC UNQUALIFIED finite20-safe extension of certified-delivery-v2.

No execution or actual mixed-serving qualification is implied by this source.
Certified single-limit serving delivery revision of bounded-memory v2.

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


ACCEPTED_SAFE_A_EVALUATOR_SHA256='c521b3ed461fe1d6bc986647c9b59fd9ba32a9b6c85f4c7bec7b550808347cb9'
ACCEPTED_CERTIFIED_V2_SHA256='3679cdd044ea4eed5ac7354af10c3c59a86970b8761f4ec1458251d2d8f7e615'
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
 if row.get('display_options') not in (None,{}):raise ValueError('unrequested display-ranking payload in certified serving row')
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


# STATIC, UNQUALIFIED finite20-safe extension. Original certified-v2 helpers above
# are retained as bases; non-safe serving paths retain their original behavior.
_base_normalize_serving_config=normalize_serving_config
_base_delivery_config=delivery_config
_base_selected_delivery_ids=selected_delivery_ids
_base_validate_delivery_binding=validate_delivery_binding
HISTORICAL20=[{'id':'t%d_w%d'%(t,w),'transfer_seconds':t,'extra_walk_weight':w} for t in (0,150,300,600,900) for w in (0,1,2,4)]

def _safe_same(a,b):return json.dumps(a,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(b,sort_keys=True,separators=(',',':'),allow_nan=False)

def _safe_int(value,name,minimum=0,maximum=None):
 if type(value) is not int or value<minimum or maximum is not None and value>maximum:raise ValueError('finite20-safe '+name+' invalid integer/range')
 return value

def normalize_finite_safe_config(config):
 fields={'baseline':None,'domain':None,'max_candidates':0,'max_total_subset_states':0}
 if not isinstance(config,dict) or set(config)-set(fields):raise ValueError('unknown/malformed finite20-safe config')
 out={**fields,**config};baseline=out['baseline']
 if not isinstance(baseline,dict) or baseline.get('finite20_safe') is not None:raise ValueError('finite20-safe recursive/missing baseline')
 baseline=dict(baseline);baseline.pop('finite20_safe',None);out['baseline']=_base_normalize_serving_config(baseline)
 domain=out['domain']
 if not isinstance(domain,dict):raise ValueError('finite20-safe domain missing')
 domain=dict(domain);auto=domain.pop('exact_when_feasible',False)
 if auto is not False:raise ValueError('finite20-safe auto-exact is not the preregistered exact mode')
 out['domain']=_base_normalize_serving_config({'bounded':domain})['bounded'];out['domain']['exact_when_feasible']=False
 return out

def normalize_serving_config(config):
 if not isinstance(config,dict):raise ValueError('malformed serving config')
 raw=dict(config);safe=raw.pop('finite20_safe',None);out=_base_normalize_serving_config(raw)
 out['finite20_safe']=normalize_finite_safe_config(safe) if safe is not None else None
 return out

def _finite_safe_config_contract(config):
 normalized=normalize_serving_config(config);c=normalized['finite20_safe']
 if c is None:return None
 if normalized['bounded'] is not None or normalized['lean_delivery'] is not True or normalized['delivery_policy']!='finite20_safe_v1' or normalized['delivery_limits']!=[3] or normalized['groups'] not in (None,[]):raise ValueError('finite20-safe outer named top3 contract differs')
 n=_safe_int(c['max_candidates'],'candidate guard',1,64);states=_safe_int(c['max_total_subset_states'],'state guard',1,200000)
 if type(normalized['max_candidates']) is not int or normalized['max_candidates']!=n or type(normalized['max_subsets']) is not int or normalized['max_subsets']!=states:raise ValueError('finite20-safe outer/nested guards differ')
 d=c['domain']
 fixed={'min_transfer_seconds':0,'max_transfer_seconds':900,'min_extra_walk_weight':0,'max_extra_walk_weight':4,'limits':[3],'distinct_patterns':False,'nested':False,'exact_subset_search':True,'exact_when_feasible':False,'max_matrix_bytes':67108864}
 for key,value in fixed.items():
  if d[key]!=value or type(value) is bool and type(d[key]) is not bool:raise ValueError('finite20-safe domain contract differs: '+key)
 for key in ['min_transfer_seconds','max_transfer_seconds','min_extra_walk_weight','max_extra_walk_weight']:
  if type(d[key]) not in (int,float) or not math.isfinite(d[key]):raise ValueError('finite20-safe domain numeric type differs')
 if d['objective'] not in ('absolute','normalized'):raise ValueError('finite20-safe objective differs')
 _safe_int(d['max_critical_points'],'point guard',4,100000);_safe_int(d['max_work'],'work guard',1,50000000);_safe_int(d['max_matrix_bytes'],'matrix guard',1,67108864)
 b=c['baseline']
 if b['bounded'] is not None or b['lean_delivery'] is not True or b['delivery_policy']!='finite_preferences_v2' or b['delivery_limits']!=[3] or not isinstance(b['groups'],list) or len(b['groups'])!=1:raise ValueError('finite20-safe historical baseline schema differs')
 _safe_int(b['max_candidates'],'historical candidate guard',1,10000);_safe_int(b['max_subsets'],'historical subset guard',1,10000000)
 if not _safe_same(b['groups'][0]['preferences'],HISTORICAL20):raise ValueError('finite20-safe historical20 IDs/order/coefficients changed')
 return c

def delivery_config(config,requested='per-run'):
 if isinstance(config,dict) and config.get('finite20_safe') is not None:
  _finite_safe_config_contract(config)
  if requested!='per-run' and (type(requested) is not int or requested!=3):raise ValueError('finite20-safe requested limit differs from top3')
  return 3,'finite20_safe'
 if isinstance(config,dict) and config.get('finite20_safe') is None:
  config=dict(config);config.pop('finite20_safe',None)
 return _base_delivery_config(config,requested)

def validate_delivery_binding(summary,command,args,requested,inputs):
 k,kind=_base_validate_delivery_binding(summary,command,args,requested,inputs)
 if kind=='finite20_safe' and summary:
  prep=summary.get('quality_preparation')
  if not isinstance(prep,dict) or prep.get('index_mode')!='bounded_shared_checker_no_recovery':raise ValueError('finite20-safe requires shared-checker no-recovery preparation mode')
 return k,kind

def _safe_identity_list(value,name,k,nonempty):
 if not isinstance(value,list) or any(not isinstance(i,str) for i in value) or len(value)>k:raise ValueError('finite20-safe '+name+' malformed/over cap')
 ids=[identity(i) for i in value]
 if len(ids)!=len(set(ids)) or nonempty and not ids:raise ValueError('finite20-safe '+name+' duplicate/missing')
 return value

def selected_delivery_ids(row,config,k):
 _,kind=delivery_config(config,k)
 if kind!='finite20_safe':
  if (row.get('recommendation_quality') or {}).get('finite20_safe_choices') is not None:raise ValueError('unrequested finite20-safe control in another serving schema')
  return _base_selected_delivery_ids(row,config,k)
 if row.get('display_options') not in (None,{}):raise ValueError('unrequested display-ranking payload in finite20-safe row')
 q=row.get('recommendation_quality')
 if not isinstance(q,dict) or q.get('continuous_choices') is not None or q.get('choices') is not None or q.get('selections'):raise ValueError('missing/mixed finite20-safe quality payload')
 result=q.get('finite20_safe_choices');c=_finite_safe_config_contract(config);name='finite20_safe_'+c['domain']['objective']+'_exact_v1'
 if not isinstance(result,dict) or result.get('complete') is not True or result.get('baseline_complete') is not True or result.get('error') or result.get('failure_stage'):raise ValueError('requested finite20-safe result absent/incomplete')
 if result.get('policy')!=name or q.get('policy')!=name or normalize_finite_safe_config(result.get('config'))!=c:raise ValueError('finite20-safe output policy/config differs')
 selection=result.get('selection');baseline=result.get('baseline');nonempty=bool(row.get('final'))
 if not isinstance(selection,dict) or type(selection.get('limit')) is not int or selection['limit']!=3 or selection.get('complete') is not True or selection.get('subset_optimal') is not True or selection.get('global_optimality_claim') is not False:raise ValueError('finite20-safe selected top3 certificate differs')
 expected_method='finite20_safe_exhaustive_subset' if nonempty else 'finite20_safe_empty_pool'
 if selection.get('method')!=expected_method:raise ValueError('finite20-safe repair method differs')
 if not isinstance(baseline,dict) or baseline.get('method')!='preference_minimax' or type(baseline.get('limit')) is not int or baseline['limit']!=3 or baseline.get('complete') is not True or baseline.get('pool_optimal') is not True or baseline.get('global_optimality_claim') is not False:raise ValueError('finite20-safe baseline certificate differs')
 _safe_identity_list(baseline.get('selected'),'baseline identities',3,nonempty)
 return _safe_identity_list(selection.get('selected'),'selected identities',3,nonempty)

def _go_identity(value):
 tokens=json.loads(value)
 if not isinstance(tokens,list):raise ValueError('malformed reconstructed identity')
 out=json.dumps([{'kind':t['kind'],'ref':t['ref']} for t in tokens],separators=(',',':'),ensure_ascii=False)
 return out.replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

def independent_historical20_baseline(final,max_subsets):
 """Independent Python integer exhaustive replay, not a call to native selector.

 Reproduces historical score-only representatives and worst/total,size,identity
 tie contract. Delivery order is first-profile score THEN Go identity, as the
 original describeChoice specifies; it is not simply identity order.
 """
 from itertools import combinations
 ordered=sorted(final,key=lambda v:_go_identity(v['identity']));seen=set();pool=[]
 vector=lambda v:(v['duration_seconds'],v['metrics']['transfers'],v['metrics']['walking_seconds'])
 for v in ordered:
  a=vector(v)
  if a in seen:continue
  seen.add(a)
  if any(vector(o)!=a and all(x<=y for x,y in zip(vector(o),a)) for o in ordered):continue
  pool.append(v)
 if not pool:return {'selected':[],'states':0,'pool':[],'scores':[{'preference_id':p['id'],'candidate_best':None,'selected_best':None,'pool_relative_regret':None} for p in HISTORICAL20],'worst_pool_regret':None,'total_pool_regret':None,'covered_scenarios':0}
 costrows=[[cost(v,p) for p in HISTORICAL20] for v in pool];opt=[min(z[j] for z in costrows) for j in range(20)];best=None;key=None;states=0;stop=False
 for size in range(1,min(3,len(pool))+1):
  for chosen in combinations(range(len(pool)),size):
   if states>=max_subsets:raise ValueError('independent historical20 baseline subset guard: no qualification')
   states+=1;got=[min(costrows[i][j] for i in chosen) for j in range(20)];ds=[a-b for a,b in zip(got,opt)];value=(max(ds),sum(ds))
   if best is None or value<key:best=chosen;key=value
   if value[0]==0:stop=True;break
  if stop:break
 selected=sorted((pool[i] for i in best),key=lambda v:(cost(v,HISTORICAL20[0]),_go_identity(v['identity'])))
 got=[min(cost(v,p) for v in selected) for p in HISTORICAL20]
 return {'selected':[identity(v['identity']) for v in selected],'states':states,'pool':pool,'scores':[{'preference_id':p['id'],'candidate_best':a,'selected_best':b,'pool_relative_regret':b-a} for p,a,b in zip(HISTORICAL20,opt,got)],'worst_pool_regret':max(b-a for a,b in zip(opt,got)),'total_pool_regret':sum(b-a for a,b in zip(opt,got)),'covered_scenarios':sum(a==b for a,b in zip(opt,got))}

def independent_finite_safe_preflight(n,c):
 if n==0:return {'candidate_count':0,'critical_points_upper_bound':0,'baseline_states_upper_bound':0,'repair_states_upper_bound':0,'matrix_bytes_upper_bound':0,'work_upper_bound':0,'resource_feasible':True}
 k=min(3,n);pairs=math.comb(n,2) if n>=2 else 0;triples=math.comb(n,3) if n>=3 else 0;points=4+4*pairs+triples
 states=sum(math.comb(n,s) for s in range(1,k+1));weighted=sum(math.comb(n,s)*s for s in range(1,k+1));branch=states*n*(k+1)*(k+1)
 matrix=16*n*points+8*20*n;baseline=3*n*n+20*n+branch+20*weighted;geometry=4+4*pairs+triples+2*n*points;repair=branch+20*n+20*weighted+weighted*points;work=baseline+geometry+repair;d=c['domain']
 feasible=n<=c['max_candidates'] and n<=c['baseline']['max_candidates'] and 2*states<=c['max_total_subset_states'] and states<=c['baseline']['max_subsets'] and points<=d['max_critical_points'] and matrix<=d['max_matrix_bytes'] and work<=d['max_work']
 return {'candidate_count':n,'critical_points_upper_bound':points,'baseline_states_upper_bound':states,'repair_states_upper_bound':states,'matrix_bytes_upper_bound':matrix,'work_upper_bound':work,'resource_feasible':feasible}

def validate_finite_safe_constraints(row,config,k,final):
 """Called only with the main evaluator's independently reconstructed final C."""
 _,kind=delivery_config(config,k)
 if kind!='finite20_safe':return None
 selected=selected_delivery_ids(row,config,k);c=_finite_safe_config_contract(config);result=row['recommendation_quality']['finite20_safe_choices'];by={identity(v['identity']):v for v in final}
 if len(by)!=len(final):raise ValueError('independent final identities duplicated')
 n=len(final)
 if n>c['max_candidates'] or n>c['baseline']['max_candidates']:raise ValueError('finite20-safe candidate guard exceeded')
 for name in ['input_candidates']:
  if type(result.get(name)) is not int or result[name]!=n:raise ValueError('finite20-safe native candidate count differs')
 pats=len({v['pattern'] for v in final})
 if type(result.get('input_patterns')) is not int or result['input_patterns']!=pats:raise ValueError('finite20-safe native pattern count differs')
 preflight=independent_finite_safe_preflight(n,c)
 if not preflight['resource_feasible'] or not _safe_same(result.get('preflight'),preflight):raise ValueError('finite20-safe preflight differs from independent conservative bound')
 _safe_int(result.get('charged_work_including_conservative_baseline_and_branch_allowance'),'charged work',0,preflight['work_upper_bound'])
 _safe_int(result.get('critical_points'),'actual critical points',4 if n else 0,preflight['critical_points_upper_bound'])
 expected_states=sum(math.comb(n,s) for s in range(1,min(3,n)+1))
 if 2*expected_states>c['max_total_subset_states'] or expected_states>c['baseline']['max_subsets']:raise ValueError('finite20-safe exact search cannot meet preregistered conservative state guard')
 for raw_id in selected+result['baseline']['selected']:
  if identity(raw_id) not in by:raise ValueError('finite20-safe selected/baseline identity absent from independently valid final C')
 baseline=independent_historical20_baseline(final,c['baseline']['max_subsets']);emitted=result['baseline']
 if [identity(i) for i in emitted['selected']]!=baseline['selected']:raise ValueError('finite20-safe historical baseline differs from independent exact replay')
 for key in ['scores','worst_pool_regret','total_pool_regret','covered_scenarios']:
  if not _safe_same(emitted.get(key),baseline[key]):raise ValueError('finite20-safe emitted historical baseline score differs: '+key)
 for key,want in [('baseline_states',baseline['states']),('repair_states',expected_states)]:
  if type(result.get(key)) is not int or result[key]!=want:raise ValueError('finite20-safe subset count differs: '+key)
 if type(result['selection'].get('evaluated_subsets')) is not int or result['selection']['evaluated_subsets']!=expected_states:raise ValueError('finite20-safe repair enumeration count differs')
 if type(emitted.get('evaluated_subsets')) is not int or emitted['evaluated_subsets']!=baseline['states']:raise ValueError('finite20-safe baseline evaluated-subsets differs')
 chosen=[by[identity(i)] for i in selected];bs=[by[i] for i in baseline['selected']];constraints=[]
 if final:
  if not chosen or not bs:raise ValueError('finite20-safe nonempty C lacks selected/baseline witness')
  if [_go_identity(i) for i in selected]!=sorted(_go_identity(i) for i in selected):raise ValueError('finite20-safe repair identity order differs')
  for p in HISTORICAL20:
   b=min(cost(v,p) for v in bs);s=min(cost(v,p) for v in chosen)
   if type(b) is not int or type(s) is not int or s>b:raise ValueError('finite20-safe independently reconstructed historical20 pointwise regression')
   constraints.append({'preference_id':p['id'],'baseline_selected_score':b,'repair_selected_score':s,'pointwise_nonworse':True})
 emitted_constraints=result.get('pointwise_constraints')
 if not final and emitted_constraints is None:emitted_constraints=[] # Known Go omitempty for the empty slice only.
 if not _safe_same(emitted_constraints,constraints):raise ValueError('finite20-safe emitted20 constraints differ from independent reconstruction')
 if result['selection'].get('distinct_pattern_count',0)!=len({v['pattern'] for v in chosen}):raise ValueError('finite20-safe selected pattern count differs')
 return {'query_id':row['query']['id'],'policy':result['policy'],'delivery_k':k,'complete':True,'historical_baseline_independently_exhaustive':True,'historical_baseline_states':baseline['states'],'repair_enumeration_count_matches':True,'pointwise20_reconstructed_nonworse':True,'constraints':constraints,'selected':[identity(i) for i in selected],'baseline_selected':baseline['selected'],'continuous_repair_optimality_independently_verified':False,'main_quality_native_certificate_counterexamples_still_apply':True,'scope':'exact historical20 baseline and integer pointwise safeguard only; continuous geometry/search exactness is separately qualified, no393/stress optimization or serving latency claim'}


# STATIC UNQUALIFIED fill-B additions. Integrate only into a NEW bound evaluator.
_safeA_normalize_serving_config=normalize_serving_config
_safeA_delivery_config=delivery_config
_safeA_selected_delivery_ids=selected_delivery_ids
_safeA_validate_delivery_binding=validate_delivery_binding

def normalize_hybrid_fill_config(config):
 defaults={'base':None,'finite20':None,'max_fill_subsets':0,'max_fill_work':0,'max_fill_matrix_bytes':0}
 if not isinstance(config,dict) or set(config)-set(defaults):raise ValueError('unknown/malformed absolute-hybrid fill config')
 out={**defaults,**config}
 for key in ['base','finite20']:
  v=out[key]
  if not isinstance(v,dict) or v.get('finite20_safe') is not None or v.get('absolute_hybrid_fill') is not None:raise ValueError('recursive/mixed fill base/control config')
  v=dict(v);v.pop('absolute_hybrid_fill',None);out[key]=normalize_serving_config(v)
 return out

def normalize_serving_config(config):
 if not isinstance(config,dict):raise ValueError('malformed serving config')
 raw=dict(config);fill=raw.pop('absolute_hybrid_fill',None);auto=False
 if isinstance(raw.get('bounded'),dict):
  b=dict(raw['bounded']);auto=b.pop('exact_when_feasible',False)
  if type(auto) is not bool:raise ValueError('auto-exact field must be a boolean')
  raw['bounded']=b
 out=_safeA_normalize_serving_config(raw)
 if out['bounded'] is not None:out['bounded']['exact_when_feasible']=auto
 if out.get('finite20_safe') is not None and fill is not None:raise ValueError('mixed safe and fill serving policies')
 out['absolute_hybrid_fill']=normalize_hybrid_fill_config(fill) if fill is not None else None
 return out

def _hybrid_fill_config_contract(config):
 normalized=normalize_serving_config(config);c=normalized['absolute_hybrid_fill']
 if c is None:return None
 if normalized['finite20_safe'] is not None or normalized['bounded'] is not None or normalized['lean_delivery'] is not True or normalized['delivery_policy']!='bounded_absolute_hybrid_fill_v1' or normalized['groups'] not in (None,[]):raise ValueError('absolute-hybrid fill outer named config differs')
 limits=normalized['delivery_limits']
 if not isinstance(limits,list) or len(limits)!=1 or type(limits[0]) is not int or limits[0] not in (3,5):raise ValueError('fill needs exactly requested limit3or5')
 k=limits[0];base=c['base'];b=base['bounded']
 if base['finite20_safe'] is not None or base['absolute_hybrid_fill'] is not None or base['lean_delivery'] is not False or base['groups'] not in (None,[]) or base['max_candidates']!=1024 or base['max_subsets']!=200000 or not isinstance(b,dict):raise ValueError('fill base differs from original absolute hybrid')
 fixed={'min_transfer_seconds':0,'max_transfer_seconds':900,'min_extra_walk_weight':0,'max_extra_walk_weight':4,'objective':'absolute','limits':[k],'distinct_patterns':False,'nested':False,'max_critical_points':100000,'max_work':50000000,'max_matrix_bytes':67108864,'exact_subset_search':False,'exact_when_feasible':True}
 if not _safe_same(b,fixed):raise ValueError('fill must not change base domain/exact decision/resource guards')
 if type(normalized['max_candidates']) is not int or normalized['max_candidates']!=1024 or type(normalized['max_subsets']) is not int or normalized['max_subsets']!=200000:raise ValueError('fill outer/base guard differs')
 _safe_int(c['max_fill_subsets'],'fill subset guard',1,200000);_safe_int(c['max_fill_work'],'fill work guard',1,20000000);_safe_int(c['max_fill_matrix_bytes'],'fill matrix guard',1,8388608)
 finite=c['finite20']
 if finite['bounded'] is not None or finite['finite20_safe'] is not None or finite['absolute_hybrid_fill'] is not None or finite['lean_delivery'] is not True or finite['delivery_policy']!='finite_preferences_v2' or finite['delivery_limits']!=[k] or finite['max_candidates']!=1024 or finite['max_subsets']!=c['max_fill_subsets'] or not isinstance(finite['groups'],list) or len(finite['groups'])!=1 or not _safe_same(finite['groups'][0]['preferences'],HISTORICAL20):raise ValueError('fill historical20 priority control changed')
 return c

def delivery_config(config,requested='per-run'):
 if isinstance(config,dict) and config.get('absolute_hybrid_fill') is not None:
  c=_hybrid_fill_config_contract(config);k=c['base']['bounded']['limits'][0]
  if requested!='per-run' and (type(requested) is not int or requested!=k):raise ValueError('requested fill k differs')
  return k,'absolute_hybrid_fill'
 if isinstance(config,dict):config=dict(config);config.pop('absolute_hybrid_fill',None)
 return _safeA_delivery_config(config,requested)

def validate_delivery_binding(summary,command,args,requested,inputs):
 k,kind=_safeA_validate_delivery_binding(summary,command,args,requested,inputs)
 if kind=='absolute_hybrid_fill' and summary:
  prep=summary.get('quality_preparation')
  if not isinstance(prep,dict) or prep.get('index_mode')!='bounded_shared_checker_no_recovery':raise ValueError('fill requires shared-checker no-recovery preparation')
 return k,kind

def selected_delivery_ids(row,config,k):
 _,kind=delivery_config(config,k)
 if kind!='absolute_hybrid_fill':
  if (row.get('recommendation_quality') or {}).get('absolute_hybrid_fill_choices') is not None:raise ValueError('unrequested fill control in another serving policy')
  return _safeA_selected_delivery_ids(row,config,k)
 if row.get('display_options') not in (None,{}):raise ValueError('unrequested ranking payload in fill endpoint')
 q=row.get('recommendation_quality')
 if not isinstance(q,dict) or q.get('finite20_safe_choices') is not None or q.get('continuous_choices') is not None or q.get('choices') is not None or q.get('selections'):raise ValueError('mixed/missing fill result')
 result=q.get('absolute_hybrid_fill_choices');c=_hybrid_fill_config_contract(config)
 if not isinstance(result,dict) or result.get('complete') is not True or result.get('error') or result.get('failure_stage') or result.get('policy')!='bounded_absolute_hybrid_fill_v1' or q.get('policy')!='bounded_absolute_hybrid_fill_v1' or normalize_hybrid_fill_config(result.get('config'))!=c:raise ValueError('fill result policy/config/status differs')
 base=result.get('base')
 if not isinstance(base,dict) or base.get('complete') is not True or base.get('error') or base.get('policy')!='bounded_continuous_regret_v3':raise ValueError('fill base absent/incomplete')
 if normalize_serving_config(dict(c['base'],bounded=base.get('config')))!=c['base']:raise ValueError('fill emitted base config differs')
 bs=base.get('selections')
 if not isinstance(bs,list) or len(bs)!=1 or type(bs[0].get('limit')) is not int or bs[0]['limit']!=k or bs[0].get('complete') is not True or type(bs[0].get('subset_optimal')) is not bool or bs[0].get('global_optimality_claim') is not False:raise ValueError('fill base exact requested selection differs')
 if bs[0].get('method') not in ('empty_pool','exhaustive_subset_resource_feasible','greedy_best_swap_local'):raise ValueError('fill base method differs from unchanged resource hybrid')
 _safe_identity_list(bs[0].get('selected'),'fill-base identities',k,bool(row.get('final')))
 selection=result.get('selection')
 if not isinstance(selection,dict) or type(selection.get('limit')) is not int or selection['limit']!=k or selection.get('complete') is not True or selection.get('set_inclusion_verified') is not True or selection.get('fill_cardinality_satisfied') is not True or selection.get('filled_subset_optimal_claim') is not False or type(selection.get('base_subset_optimal')) is not bool or selection['base_subset_optimal']!=bs[0]['subset_optimal']:raise ValueError('fill final selection/status contract differs')
 if any(key in selection for key in ['worst_pool_absolute_regret','worst_pool_normalized_regret','absolute_worst_weight','normalized_worst_weight','subset_optimal']):raise ValueError('filled set copied base exact maximum/optimality claim')
 return _safe_identity_list(selection.get('selected'),'filled identities',k,bool(row.get('final')))

def independent_historical20_for_limit(final,k,max_subsets):
 from itertools import combinations
 ordered=sorted(final,key=lambda v:_go_identity(v['identity']));pool=[];seen=set();vector=lambda v:(v['duration_seconds'],v['metrics']['transfers'],v['metrics']['walking_seconds'])
 for v in ordered:
  a=vector(v)
  if a in seen:continue
  seen.add(a)
  if any(vector(o)!=a and all(x<=y for x,y in zip(vector(o),a)) for o in ordered):continue
  pool.append(v)
 if not pool:return {'selected':[],'states':0,'scores':[{'preference_id':p['id'],'candidate_best':None,'selected_best':None,'pool_relative_regret':None} for p in HISTORICAL20],'worst_pool_regret':None,'total_pool_regret':None,'covered_scenarios':0}
 costs=[[cost(v,p) for p in HISTORICAL20] for v in pool];opt=[min(v[j] for v in costs) for j in range(20)];best=None;value=None;states=0;stop=False
 for size in range(1,min(k,len(pool))+1):
  for chosen in combinations(range(len(pool)),size):
   if states>=max_subsets:raise ValueError('independent fill finite20 subset guard')
   states+=1;ds=[min(costs[i][j] for i in chosen)-opt[j] for j in range(20)];key=(max(ds),sum(ds))
   if best is None or key<value:best=chosen;value=key
   if key[0]==0:stop=True;break
  if stop:break
 selected=sorted((pool[i] for i in best),key=lambda v:(cost(v,HISTORICAL20[0]),_go_identity(v['identity'])));got=[min(cost(v,p) for v in selected) for p in HISTORICAL20]
 return {'selected':[identity(v['identity']) for v in selected],'states':states,'scores':[{'preference_id':p['id'],'candidate_best':a,'selected_best':b,'pool_relative_regret':b-a} for p,a,b in zip(HISTORICAL20,opt,got)],'worst_pool_regret':max(b-a for a,b in zip(opt,got)),'total_pool_regret':sum(b-a for a,b in zip(opt,got)),'covered_scenarios':sum(a==b for a,b in zip(opt,got))}

def _default_feature_key(v):return (v['duration_seconds']+300*v['metrics']['transfers'],v['metrics']['arrival'],v['metrics']['walking_seconds'],_go_identity(v['identity']))
def independent_pattern_anchor_ids(final,k):
 ranked=sorted(final,key=_default_feature_key)
 if not ranked:return []
 score=lambda v:v['duration_seconds']+300*v['metrics']['transfers'];best=score(ranked[0]);seen=set();eligible=[]
 for v in ranked:
  if score(v)>best+300:continue
  if v['pattern'] in seen:continue
  seen.add(v['pattern']);b=v['metrics']
  if any(all(a[key]<=b[key] for key in ['arrival','boardings','walking_seconds']) and any(a[key]<b[key] for key in ['arrival','boardings','walking_seconds']) for a in (o['metrics'] for o in final)):continue
  eligible.append(v)
 ids=[]
 def add(v):
  i=identity(v['identity'])
  if len(ids)<k and i not in ids:ids.append(i)
 if not eligible:return []
 add(eligible[0])
 for metric in ['arrival','walking_seconds','transfers']:add(min(eligible,key=lambda v:(v['metrics'][metric],_default_feature_key(v))))
 for v in eligible:add(v)
 return ids

def independent_fill_preflight(n,k,c):
 states=sum(math.comb(n,s) for s in range(1,min(n,k)+1));weighted=sum(math.comb(n,s)*s for s in range(1,min(n,k)+1));work=7*n*n+20*n+states*n*(k+1)*(k+1)+20*weighted+4*n;matrix=8*20*n
 return {'candidate_count':n,'limit':k,'states_upper_bound':states,'work_upper_bound':work,'matrix_bytes_upper_bound':matrix,'resource_feasible':states<=c['max_fill_subsets'] and work<=c['max_fill_work'] and matrix<=c['max_fill_matrix_bytes']}
def _go_canonical_json(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
def _verify_config_value_hash(result,string_key,hash_key,expected,normalizer):
 raw=result.get(string_key);digest=result.get(hash_key)
 if not isinstance(raw,str) or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or hashlib.sha256(raw.encode()).hexdigest()!=digest:raise ValueError('fill config semantic SHA/string binding differs')
 value=json.loads(raw)
 if _go_canonical_json(value)!=raw or normalizer(value)!=expected:raise ValueError('fill canonical config differs from requested value')

def validate_hybrid_fill_constraints(row,config,k,final):
 _,kind=delivery_config(config,k)
 if kind!='absolute_hybrid_fill':return None
 ids=selected_delivery_ids(row,config,k);result=row['recommendation_quality']['absolute_hybrid_fill_choices'];c=_hybrid_fill_config_contract(config);selection=result['selection'];bs=result['base']['selections'][0];baseids=bs['selected'];by={identity(v['identity']):v for v in final};n=len(final);target=min(k,n)
 if len(by)!=n:raise ValueError('duplicate independently valid native identities')
 _verify_config_value_hash(result,'config_value_canonical_json','config_value_sha256',c,normalize_hybrid_fill_config);_verify_config_value_hash(result,'base_config_value_canonical_json','base_config_value_sha256',c['base'],normalize_serving_config)
 if type(result.get('input_candidates')) is not int or result['input_candidates']!=n or type(result.get('input_patterns')) is not int or result['input_patterns']!=len({v['pattern'] for v in final}):raise ValueError('fill original native counts differ')
 if type(result['base'].get('input_candidates')) is not int or result['base']['input_candidates']!=n or type(result['base'].get('input_patterns')) is not int or result['base']['input_patterns']!=len({v['pattern'] for v in final}):raise ValueError('fill base original native counts differ')
 sem=[identity(i) for i in ids];base=[identity(i) for i in baseids]
 if any(i not in by for i in sem+base) or len(sem)!=target or len(set(sem))!=len(sem) or not set(base)<=set(sem) or sem[:len(base)]!=base:raise ValueError('fill native membership/cardinality/base prefix inclusion failed')
 if [identity(i) for i in selection.get('base_selected',[])]!=base or type(selection.get('requested_cardinality')) is not int or selection['requested_cardinality']!=target:raise ValueError('fill declared base/cardinality differs')
 required=len(base)<target
 if type(result.get('fill_required')) is not bool or result['fill_required']!=required:raise ValueError('fill conditional work flag differs')
 expected=list(base);added=[]
 if required:
  pf=independent_fill_preflight(n,k,c)
  if not pf['resource_feasible'] or not _safe_same(result.get('fill_preflight'),pf) or type(result.get('charged_fill_work_upper_bound')) is not int or result['charged_fill_work_upper_bound']!=pf['work_upper_bound']:raise ValueError('fill conservative resource preflight differs')
  finite=independent_historical20_for_limit(final,k,c['max_fill_subsets']);fc=result.get('finite20_control')
  if not isinstance(fc,dict) or type(fc.get('limit')) is not int or fc['limit']!=k or fc.get('complete') is not True or fc.get('pool_optimal') is not True or fc.get('global_optimality_claim') is not False or fc.get('method')!='preference_minimax' or [identity(i) for i in fc.get('selected',[])]!=finite['selected'] or type(fc.get('evaluated_subsets')) is not int or fc['evaluated_subsets']!=finite['states']:raise ValueError('fill finite20 control differs from independent exact replay')
  for key in ['scores','worst_pool_regret','total_pool_regret','covered_scenarios']:
   if not _safe_same(fc.get(key),finite[key]):raise ValueError('fill finite20 scores differ')
  pattern=independent_pattern_anchor_ids(final,k);pc=result.get('pattern_control')
  if not isinstance(pc,dict) or type(pc.get('limit')) is not int or pc['limit']!=k or pc.get('score_envelope_seconds')!=300 or [identity(i) for i in pc.get('selected',[])]!=pattern:raise ValueError('fill pattern-anchor priority differs')
  remaining=[identity(v['identity']) for v in sorted(final,key=_default_feature_key)]
  for source,stream in [('historical_finite20',finite['selected']),('pattern_anchor_300',pattern),('default_feature_order',remaining)]:
   for i in stream:
    if len(expected)>=target:break
    if i not in expected:expected.append(i);added.append({'identity':i,'source':source})
   if len(expected)>=target:break
 else:
  if result.get('fill_preflight') is not None or result.get('finite20_control') is not None or result.get('pattern_control') is not None or type(result.get('charged_fill_work_upper_bound')) is not int or result['charged_fill_work_upper_bound']!=0:raise ValueError('unrequested fill controls/work when base already meets cardinality')
 if sem!=expected:raise ValueError('fill output does not follow preregistered fixed streams')
 actual_added=selection.get('added')
 if not isinstance(actual_added,list) or any(not isinstance(v,dict) or set(v)!={'identity','source'} for v in actual_added) or [{'identity':identity(v['identity']),'source':v['source']} for v in actual_added]!=added:raise ValueError('fill added identities/provenance differs')
 for field,want in [('base_patterns',len({by[i]['pattern'] for i in base})),('added_patterns',len({by[i['identity']]['pattern'] for i in added})),('final_patterns',len({by[i]['pattern'] for i in sem}))]:
  if type(selection.get(field)) is not int or selection[field]!=want:raise ValueError('fill pattern count differs')
 for bound,basefield in [('worst_pool_absolute_regret_upper_bound','worst_pool_absolute_regret'),('worst_pool_normalized_regret_upper_bound','worst_pool_normalized_regret')]:
  value=bs.get(basefield)
  if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):raise ValueError('invalid base numeric regret')
  got=selection.get(bound)
  if (value is not None and type(got) not in (int,float)) or got!=value:raise ValueError('copied fill upper bound differs from base')
 return {'query_id':row['query']['id'],'policy':'bounded_absolute_hybrid_fill_v1','delivery_k':k,'complete':True,'base_ids_preserved':True,'requested_cardinality_verified':True,'fixed_stream_priority_independently_replayed':True,'selected':sem,'base_selected':base,'added':added,'config_value_sha256':result['config_value_sha256'],'base_config_value_sha256':result['base_config_value_sha256'],'filled_regret_fields_are_upper_bounds_only':True,'continuous_base_optimality_independently_verified':False,'scope':'set inclusion and all deterministic fill streams/cardinality/config hashes independently verified; unchanged base continuous exactness is a separate qualification, no finite20 dominance or393/stress guarantee'}

def validate_reconstructed_delivery(row,config,k,independently_reconstructed_final):
 _,kind=delivery_config(config,k)
 if kind=='absolute_hybrid_fill':return validate_hybrid_fill_constraints(row,config,k,independently_reconstructed_final)
 return validate_finite_safe_constraints(row,config,k,independently_reconstructed_final)


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
 for name,expected in [('evaluate_v2_certified_delivery_finite_safe_staged.py',ACCEPTED_SAFE_A_EVALUATOR_SHA256),('evaluate_v2_certified_delivery_v2.py',ACCEPTED_CERTIFIED_V2_SHA256),('evaluate_v2.py',ACCEPTED_ORIGINAL_SHA256),('evaluate_v2_bounded_memory.py',ACCEPTED_BOUNDED_SHA256)]:
  if sha(Path(__file__).with_name(name))!=expected:raise ValueError('accepted evaluator source changed: '+name)
 out.mkdir(parents=True,exist_ok=False)
 held=read(ROOT/'selector-quality/configs/heldout393.json');scalar=read(ROOT/'selector-quality/configs/scalar9.json')
 scalar=scalar.get('weights',scalar) if isinstance(scalar,dict) else scalar
 expected_queries={};scope={};runs=[];pool=collections.defaultdict(dict);errors=[];inputs={};oracle_slots=[];oracle_semantic_slots=set();cohort_offered=collections.Counter()
 for dependency in [Path(__file__),Path(__file__).with_name('evaluate_v2_certified_delivery_finite_safe_staged.py'),Path(__file__).with_name('evaluate_v2_certified_delivery_v2.py'),ROOT/'selector-quality/PREFERENCE_EXPOSURE_LEDGER.json',Path(__file__).with_name('evaluate_v2.py'),Path(__file__).with_name('evaluate_v2_bounded_memory.py'),ROOT.parent/'evalkit/evalkit.py',ROOT/'selector-quality/configs/heldout393.json',ROOT/'selector-quality/configs/scalar9.json',ROOT/'selector-quality/PREFERENCE_SEAL.json']:
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
 candidate_delivery_contracts=JsonlSink(out/'CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl');candidate_delivery_contract_count=0
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
     if r.get('completed'):
      safe_audit=validate_reconstructed_delivery(r,cfg,run['delivery_k'],item['final'])
      if safe_audit is not None:
       candidate_delivery_contracts.append(dict(safe_audit,run=run['id'],dataset_sha256=dsha));candidate_delivery_contract_count+=1
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
 candidate_delivery_contracts.close()
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
 report={'schema':'sg-independent-v2-certified-serving-safe-fill-B-staged-v1','safe_A_evaluator_dependency_sha256':ACCEPTED_SAFE_A_EVALUATOR_SHA256,'certified_v2_dependency_sha256':ACCEPTED_CERTIFIED_V2_SHA256,'candidate_aware_delivery_contract_rows':candidate_delivery_contract_count,'finite20_safe_scope':'Independently reconstructed historical20 exact baseline and pointwise integer safeguards; per-row continuous repair optimality is not independently certified here','delivery_mode':delivery_mode,'delivery_contract':'Each serving run has exactly one frozen requested limit[3]or[5]; mixed/joint/legacy uncertified selection work is rejected; all offered rows retain their per-k denominator.','serving_cohort_offered':{str(k):cohort_offered[str(k)] for k in (3,5)},'accepted_bounded_source_sha256':ACCEPTED_BOUNDED_SHA256,'accepted_original_source_sha256':ACCEPTED_ORIGINAL_SHA256,'inputs':inputs,'offered_run_rows':metrics.offered,'runs':len(metrics),'independent_reconstruction_errors':len(errors),'native_contract_counterexamples':len(native_counterexamples),'oracle_offered_slots':len(oracle_slots),'oracle_complete_slots':sum(x['complete'] for x in oracle_slots),'oracle_scope':'Complete results establish only their exact9 weighted optima; pool enrichment does not establish393-profile/full3D completeness','limitations':['393 weights are exposed tune diagnostics and frozen hypotheses, not untouched preference generalization or passenger preference probabilities.','Union and leave-family-out pools are incomplete. Negative signed LOFO differences expose weaker pools, not better-than-global routing.','All offered errors/unknowns remain counted; model-empty lacks finite preference optimum.','Repeated process offers are not distinct OD demand.']};(out/'REPORT.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--campaign',action='append',required=True);p.add_argument('--oracle-glob',action='append',default=[]);p.add_argument('--out',required=True);p.add_argument('--delivery-k',choices=['3','5','per-run'],required=True);a=p.parse_args();evaluate(a.campaign,a.oracle_glob,Path(a.out),int(a.delivery_k) if a.delivery_k!='per-run' else 'per-run')
