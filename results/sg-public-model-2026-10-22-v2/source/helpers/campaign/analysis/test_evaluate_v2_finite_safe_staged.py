#!/usr/bin/env python3
"""STATIC tests only. Not syntax checked, imported, or executed yet."""
import copy,importlib.util,json,unittest
from pathlib import Path
PATH=Path(__file__).with_name('evaluate_v2_certified_delivery_finite_safe_staged.py')
spec=importlib.util.spec_from_file_location('safe_staged',PATH);E=importlib.util.module_from_spec(spec);spec.loader.exec_module(E)
def config():
 prefs=[{'id':'t%d_w%d'%(t,w),'transfer_seconds':t,'extra_walk_weight':w} for t in (0,150,300,600,900) for w in (0,1,2,4)]
 baseline={'max_subsets':200000,'max_candidates':1024,'groups':[{'name':'explicit_twenty_hypotheses','preferences':prefs}],'lean_delivery':True,'delivery_policy':'finite_preferences_v2','delivery_limits':[3]}
 domain={'min_transfer_seconds':0,'max_transfer_seconds':900,'min_extra_walk_weight':0,'max_extra_walk_weight':4,'objective':'absolute','limits':[3],'distinct_patterns':False,'nested':False,'max_critical_points':100000,'max_work':50000000,'max_matrix_bytes':67108864,'exact_subset_search':True}
 nested={'baseline':baseline,'domain':domain,'max_candidates':64,'max_total_subset_states':200000}
 return {'max_candidates':64,'max_subsets':200000,'lean_delivery':True,'delivery_policy':'finite20_safe_v1','delivery_limits':[3],'finite20_safe':nested}
def fixture(empty=False):
 c=config();name='finite20_safe_absolute_exact_v1';identity=json.dumps([{'kind':'ride','ref':'a'}],separators=(',',':'));final=[] if empty else [{'identity':identity,'pattern':'pattern-a','duration_seconds':100,'metrics':{'arrival':100,'boardings':1,'transfers':0,'walking_seconds':0}}];ids=[] if empty else [identity];prefs=c['finite20_safe']['baseline']['groups'][0]['preferences']
 scores=[{'preference_id':p['id'],'candidate_best':None if empty else 100,'selected_best':None if empty else 100,'pool_relative_regret':None if empty else 0} for p in prefs]
 baseline={'method':'preference_minimax','limit':3,'selected':ids,'complete':True,'pool_optimal':True,'global_optimality_claim':False,'worst_pool_regret':None if empty else 0,'total_pool_regret':None if empty else 0,'covered_scenarios':0 if empty else 20,'evaluated_subsets':0 if empty else 1,'scores':scores}
 selection={'limit':3,'selected':ids,'complete':True,'subset_optimal':True,'global_optimality_claim':False,'method':'finite20_safe_empty_pool' if empty else 'finite20_safe_exhaustive_subset','distinct_pattern_count':0 if empty else 1,'evaluated_subsets':0 if empty else 1}
 # Independent hand-computed n=1 bounds: P4,S1,matrix224bytes,work107.
 preflight={'candidate_count':0 if empty else 1,'critical_points_upper_bound':0 if empty else 4,'baseline_states_upper_bound':0 if empty else 1,'repair_states_upper_bound':0 if empty else 1,'matrix_bytes_upper_bound':0 if empty else 224,'work_upper_bound':0 if empty else 107,'resource_feasible':True}
 constraints=[] if empty else [{'preference_id':p['id'],'baseline_selected_score':100,'repair_selected_score':100,'pointwise_nonworse':True} for p in prefs]
 result={'policy':name,'config':c['finite20_safe'],'complete':True,'baseline_complete':True,'input_candidates':len(final),'input_patterns':len(final),'preflight':preflight,'baseline':baseline,'selection':selection,'baseline_states':0 if empty else 1,'repair_states':0 if empty else 1,'critical_points':0 if empty else 4,'charged_work_including_conservative_baseline_and_branch_allowance':0 if empty else 99,'pointwise_constraints':constraints}
 row={'query':{'id':'fixture'},'completed':True,'final':final,'recommendation_quality':{'policy':name,'features':[],'selections':[],'finite20_safe_choices':result}}
 if empty:result.pop('pointwise_constraints') # Actual Go omitempty representation.
 return c,row,final
class FiniteSafeEvaluatorStagedTests(unittest.TestCase):
 def test_exact_requested_top3_and_integer_constraint_fixture(self):
  c,row,final=fixture();self.assertEqual(E.delivery_config(c,'per-run'),(3,'finite20_safe'));audit=E.validate_finite_safe_constraints(row,c,3,final);self.assertTrue(audit['pointwise20_reconstructed_nonworse']);self.assertFalse(audit['continuous_repair_optimality_independently_verified']);self.assertEqual(len(audit['constraints']),20)
 def test_empty_is_complete_without_finite_preference_optimum(self):
  c,row,final=fixture(True);audit=E.validate_finite_safe_constraints(row,c,3,final);self.assertEqual(audit['constraints'],[]);self.assertEqual(audit['selected'],[])
 def test_wrong_request_and_extra_controls_rejected(self):
  c,row,_=fixture()
  with self.assertRaises(ValueError):E.selected_delivery_ids(row,c,5)
  row['display_options']={'3':{'options':[]}}
  with self.assertRaises(ValueError):E.selected_delivery_ids(row,c,3)
 def test_changed_historical20_and_recursive_baseline_rejected(self):
  c,_,_=fixture();c['finite20_safe']['baseline']['groups'][0]['preferences'][0]['transfer_seconds']=1
  with self.assertRaises(ValueError):E.delivery_config(c)
  c,_,_=fixture();c['finite20_safe']['baseline']['finite20_safe']={}
  with self.assertRaises(ValueError):E.delivery_config(c)
 def test_tampered_baseline_or_emitted_constraints_rejected(self):
  for change in ['baseline_score','constraint_score','boolean_as_integer','missing_constraints']:
   c,row,final=fixture();r=row['recommendation_quality']['finite20_safe_choices']
   if change=='baseline_score':r['baseline']['scores'][0]['selected_best']=99
   elif change=='constraint_score':r['pointwise_constraints'][0]['repair_selected_score']=99
   elif change=='boolean_as_integer':r['baseline']['scores'][0]['pool_relative_regret']=False
   else:r['pointwise_constraints']=[]
   with self.subTest(change=change),self.assertRaises(ValueError):E.validate_finite_safe_constraints(row,c,3,final)
 def test_foreign_duplicate_and_missing_display_rejected(self):
  for change in ['foreign','duplicate','empty']:
   c,row,final=fixture();s=row['recommendation_quality']['finite20_safe_choices']['selection']
   if change=='foreign':s['selected']=['[{"kind":"ride","ref":"foreign"}]']
   elif change=='duplicate':s['selected']*=2
   else:s['selected']=[]
   with self.subTest(change=change),self.assertRaises(ValueError):E.validate_finite_safe_constraints(row,c,3,final)
 def test_wrong_preflight_and_subset_counts_rejected(self):
  for change in ['preflight','baseline_states','repair_states','charged_work']:
   c,row,final=fixture();r=row['recommendation_quality']['finite20_safe_choices']
   if change=='preflight':r['preflight']['matrix_bytes_upper_bound']=0
   elif change=='charged_work':r['charged_work_including_conservative_baseline_and_branch_allowance']=108
   else:r[change]=0
   with self.subTest(change=change),self.assertRaises(ValueError):E.validate_finite_safe_constraints(row,c,3,final)
 def test_no_hidden_safe_control_in_other_serving_schema(self):
  c,row,_=fixture();finite=c['finite20_safe']['baseline']
  with self.assertRaises(ValueError):E.selected_delivery_ids(row,finite,3)
 def test_historical_delivery_order_is_first_profile_not_identity(self):
  # Dominance tradeoff: a is slower with less walking; z is faster but walks100.
  # All20 force both, and historical describeChoice emits z then a by duration.
  final=[{'identity':'[{"kind":"ride","ref":"a"}]','pattern':'a','duration_seconds':101,'metrics':{'transfers':0,'walking_seconds':0}},{'identity':'[{"kind":"ride","ref":"z"}]','pattern':'z','duration_seconds':100,'metrics':{'transfers':0,'walking_seconds':100}}]
  got=E.independent_historical20_baseline(final,200000);self.assertEqual([json.loads(i)[0]['ref'] for i in got['selected']],['z','a']);self.assertEqual(got['states'],3)
if __name__=='__main__':unittest.main()
