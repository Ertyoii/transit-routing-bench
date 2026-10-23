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
