#!/usr/bin/env python3
"""Static-only source B fixtures; execute solely in an owner-allocated CPU slot."""
import copy,hashlib,importlib.util,json,tempfile,unittest
from pathlib import Path
PATH=Path(__file__).with_name('evaluate_v2_certified_delivery_safe_fill_B_staged.py')
spec=importlib.util.spec_from_file_location('fill_B_staged',PATH);E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
def config(k=3):
 finite={'max_subsets':200000,'max_candidates':1024,'groups':[{'name':'explicit_twenty_hypotheses','preferences':copy.deepcopy(E.HISTORICAL20)}],'lean_delivery':True,'delivery_policy':'finite_preferences_v2','delivery_limits':[k]}
 bounded={'min_transfer_seconds':0,'max_transfer_seconds':900,'min_extra_walk_weight':0,'max_extra_walk_weight':4,'objective':'absolute','limits':[k],'distinct_patterns':False,'nested':False,'max_critical_points':100000,'max_work':50000000,'max_matrix_bytes':67108864,'exact_subset_search':False,'exact_when_feasible':True}
 base={'max_candidates':1024,'max_subsets':200000,'bounded':bounded}
 fill={'base':base,'finite20':finite,'max_fill_subsets':200000,'max_fill_work':20000000,'max_fill_matrix_bytes':8388608}
 return {'max_candidates':1024,'max_subsets':200000,'lean_delivery':True,'delivery_policy':'bounded_absolute_hybrid_fill_v1','delivery_limits':[k],'absolute_hybrid_fill':fill}
def fixture(k=3,n=3):
 c=config(k);cfg=c['absolute_hybrid_fill'];fs=[{'identity':json.dumps([{'kind':'ride','ref':name}],separators=(',',':')),'pattern':name,'duration_seconds':d,'metrics':{'arrival':d,'boardings':i+1,'transfers':i,'walking_seconds':10*i}} for i,(name,d) in enumerate([('a',100),('b',200),('c',300)][:n])]
 ids=[f['identity'] for f in fs];baseids=ids[:1];required=n>1;bs={'limit':k,'selected':baseids,'complete':True,'subset_optimal':True,'global_optimality_claim':False,'method':'exhaustive_subset_resource_feasible' if n else 'empty_pool','distinct_pattern_count':min(n,1),'worst_pool_absolute_regret':0 if n else None,'worst_pool_normalized_regret':0 if n else None};base={'policy':'bounded_continuous_regret_v3','config':cfg['base']['bounded'],'complete':True,'input_candidates':n,'input_patterns':n,'selections':[bs]}
 selection={'limit':k,'base_selected':baseids,'added':[{'identity':i,'source':'default_feature_order'} for i in ids[1:]],'selected':ids,'complete':True,'set_inclusion_verified':True,'requested_cardinality':n,'fill_cardinality_satisfied':True,'base_subset_optimal':True,'filled_subset_optimal_claim':False,'base_patterns':min(n,1),'added_patterns':max(0,n-1),'final_patterns':n}
 if n:selection.update(worst_pool_absolute_regret_upper_bound=0,worst_pool_normalized_regret_upper_bound=0)
 result={'policy':'bounded_absolute_hybrid_fill_v1','config':cfg,'complete':True,'input_candidates':n,'input_patterns':n,'base':base,'fill_required':required,'charged_fill_work_upper_bound':0,'selection':selection}
 for key,value in [('config_value',cfg),('base_config_value',cfg['base'])]:
  raw=E._go_canonical_json(value);result[key+'_canonical_json']=raw;result[key+'_sha256']=hashlib.sha256(raw.encode()).hexdigest()
 if required:
  result['fill_preflight']=E.independent_fill_preflight(n,k,cfg);result['charged_fill_work_upper_bound']=result['fill_preflight']['work_upper_bound'];finite=E.independent_historical20_for_limit(fs,k,200000);result['finite20_control']={'limit':k,'selected':finite['selected'],'complete':True,'pool_optimal':True,'global_optimality_claim':False,'method':'preference_minimax','evaluated_subsets':finite.pop('states'),**{key:finite[key] for key in ['scores','worst_pool_regret','total_pool_regret','covered_scenarios']}};result['pattern_control']={'limit':k,'score_envelope_seconds':300,'selected':ids[:1]}
 row={'query':{'id':'literal-fill-fixture'},'completed':True,'final':fs,'recommendation_quality':{'policy':'bounded_absolute_hybrid_fill_v1','selections':[],'absolute_hybrid_fill_choices':result}}
 return c,row,fs
class HybridFillEvaluatorStagedTests(unittest.TestCase):
 def test_top3_top5_empty_full_and_underfilled(self):
  for k in (3,5):
   for n in (0,1,2,3):
    c,row,fs=fixture(k,n);self.assertEqual(E.delivery_config(c),(k,'absolute_hybrid_fill'));audit=E.validate_reconstructed_delivery(row,c,k,fs);self.assertTrue(audit['base_ids_preserved']);self.assertEqual(len(audit['selected']),n);self.assertFalse(audit['continuous_base_optimality_independently_verified'])
 def test_preflight_literal_arithmetic(self):
  c=config()['absolute_hybrid_fill'];self.assertEqual(E.independent_fill_preflight(3,3,c),{'candidate_count':3,'limit':3,'states_upper_bound':7,'work_upper_bound':711,'matrix_bytes_upper_bound':480,'resource_feasible':True});self.assertEqual(E.independent_fill_preflight(3,5,c)['work_upper_bound'],1131)
 def test_exact_budget_and_recursive_contract(self):
  for change in ('wrong_k','joint','normalized','greedy','safe','recursive','changed20','guard'):
   c=config();f=c['absolute_hybrid_fill']
   if change=='wrong_k':c['delivery_limits']=[5]
   elif change=='joint':c['delivery_limits']=[3,5]
   elif change=='normalized':f['base']['bounded']['objective']='normalized'
   elif change=='greedy':f['base']['bounded']['exact_when_feasible']=False
   elif change=='safe':c['finite20_safe']={}
   elif change=='recursive':f['base']['absolute_hybrid_fill']={}
   elif change=='changed20':f['finite20']['groups'][0]['preferences'][0]['transfer_seconds']=1
   else:f['max_fill_work']=20000001
   with self.subTest(change=change),self.assertRaises(ValueError):E.delivery_config(c)
 def test_selection_cardinality_identity_and_inclusion(self):
  for change in ('drop_base','duplicate','foreign','underfill','reorder','base_claim','exact_regret','provenance','pattern_count'):
   c,row,fs=fixture();s=row['recommendation_quality']['absolute_hybrid_fill_choices']['selection']
   if change=='drop_base':s['base_selected']=[]
   elif change=='duplicate':s['selected'][2]=s['selected'][1]
   elif change=='foreign':s['selected'][2]='[{"kind":"ride","ref":"foreign"}]'
   elif change=='underfill':s['selected'].pop()
   elif change=='reorder':s['selected'].reverse()
   elif change=='base_claim':s['base_subset_optimal']=False
   elif change=='exact_regret':s['worst_pool_absolute_regret']=0
   elif change=='provenance':s['added'][0]['source']='pattern_anchor_300'
   else:s['final_patterns']=False
   with self.subTest(change=change),self.assertRaises(ValueError):E.validate_reconstructed_delivery(row,c,3,fs)
 def test_hashes_controls_and_work(self):
  for change in ('sha','canonical','base_hash','finite_score','pattern_stream','work','matrix','finite_bool','upper_bound'):
   c,row,fs=fixture();r=row['recommendation_quality']['absolute_hybrid_fill_choices']
   if change=='sha':r['config_value_sha256']='0'*64
   elif change=='canonical':r['config_value_canonical_json']+=' ';r['config_value_sha256']=hashlib.sha256(r['config_value_canonical_json'].encode()).hexdigest()
   elif change=='base_hash':r['base_config_value_sha256']='0'*64
   elif change=='finite_score':r['finite20_control']['scores'][0]['selected_best']=99
   elif change=='pattern_stream':r['pattern_control']['selected']=[]
   elif change=='work':r['charged_fill_work_upper_bound']-=1
   elif change=='matrix':r['fill_preflight']['matrix_bytes_upper_bound']=0
   elif change=='finite_bool':r['finite20_control']['evaluated_subsets']=True
   else:r['selection']['worst_pool_absolute_regret_upper_bound']=True
   with self.subTest(change=change),self.assertRaises(ValueError):E.validate_reconstructed_delivery(row,c,3,fs)
 def test_conditional_no_unrequested_fill_work(self):
  for change in ('control','preflight','work'):
   c,row,fs=fixture(n=1);r=row['recommendation_quality']['absolute_hybrid_fill_choices']
   if change=='control':r['finite20_control']={}
   elif change=='preflight':r['fill_preflight']={}
   else:r['charged_fill_work_upper_bound']=1
   with self.subTest(change=change),self.assertRaises(ValueError):E.validate_reconstructed_delivery(row,c,3,fs)
 def test_no_hidden_mixed_controls(self):
  for field in ('display_options','choices','continuous_choices','finite20_safe_choices'):
   c,row,_=fixture()
   if field=='display_options':row[field]={'3':{'options':[]}}
   else:row['recommendation_quality'][field]={}
   with self.subTest(field=field),self.assertRaises(ValueError):E.selected_delivery_ids(row,c,3)
 def test_safe_A_fixtures_are_retained(self):
  path=Path(__file__).with_name('test_evaluate_v2_finite_safe_staged.py');sp=importlib.util.spec_from_file_location('safe_A_control',path);module=importlib.util.module_from_spec(sp);sp.loader.exec_module(module)
  for empty in (False,True):
   c,row,fs=module.fixture(empty);self.assertTrue(E.validate_reconstructed_delivery(row,c,3,fs)['pointwise20_reconstructed_nonworse'])
 def test_supervisor_config_and_lean_preparation_binding(self):
  c=config()
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'fill.json';path.write_text(json.dumps(c));digest=E.sha(path);args=['-quality','-display-k','-1','-preference-scenarios',str(path)];command={'argv':['/usr/bin/taskset','-c','0','bench']+args,'inputs':[{'path':str(path),'sha256':digest,'bytes':path.stat().st_size}]};summary={'quality_enabled':True,'preference_config_sha256':digest,'preference_config':copy.deepcopy(c),'quality_preparation':{'index_mode':'bounded_shared_checker_no_recovery'}}
   # Actual args begin with bench, as inherited certified-v2 supervisor binding requires.
   self.assertEqual(E.validate_delivery_binding(summary,command,['bench']+args,'per-run',{}),(3,'absolute_hybrid_fill'))
   summary['quality_preparation']['index_mode']='legacy_recovery'
   with self.assertRaises(ValueError):E.validate_delivery_binding(summary,command,['bench']+args,'per-run',{})
if __name__=='__main__':unittest.main()
