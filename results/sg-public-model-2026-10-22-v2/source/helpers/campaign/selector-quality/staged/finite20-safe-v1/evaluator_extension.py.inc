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
