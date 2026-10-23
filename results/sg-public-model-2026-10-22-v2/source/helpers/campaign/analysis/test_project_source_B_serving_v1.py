#!/usr/bin/env python3
"""STATIC tests. No execution until measurement release and owner analysis slot."""
import importlib.util,json,types,unittest
from pathlib import Path
P=Path(__file__).with_name('project_source_B_serving_v1.py');spec=importlib.util.spec_from_file_location('projection_static_fixture',P);M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
class ProjectionTests(unittest.TestCase):
 def test_clock_quantiles_pool_observations_not_quantiles(self):
  values=[1]*19+[100];d=M.dist(values);self.assertEqual(d['p95'],1);self.assertEqual(d['p99'],100);self.assertEqual(d['mean'],5.95);self.assertIsNone(M.dist([])['p95'])
 def test_quality_counts_weighted_mean_and_no_pooled_p95(self):
  b=M.new_quality()
  for count,mean,worst,eligible,covered in [(2,1,2,2,1),(1,10,10,1,0)]:M.add_quality(b,{'eligible':eligible,'covered':covered,'regret_score_seconds':{'count':count,'mean':mean,'max':worst,'p95':worst},'normalized_regret':{'count':count,'mean':mean/100,'max':worst/100}},True)
  M.add_quality(b,{'eligible':3,'missing':True},False);v=M.finish_quality(b);self.assertEqual(v['eligible_slots'],6);self.assertEqual(v['missing_slots'],3);self.assertEqual(v['regret_score_seconds_mean'],4);self.assertEqual(v['regret_score_seconds_max'],10);self.assertEqual(v['coverage_including_unavailable'],1/6);self.assertNotIn('p95',v)
 def test_native_complete_mismatch_and_incomplete_unknown(self):
  parity=types.SimpleNamespace(FIELDS=('completed','raw','status'));a={'q':{'completed':True,'raw':[1,2],'status':'complete'}};b={'q':{'completed':True,'raw':[2,1],'status':'complete'}};self.assertEqual(M.exact_pair(parity,a,a)['status'],'exact');self.assertEqual(M.exact_pair(parity,a,b)['status'],'mismatch');b['q']['completed']=False;b['q']['status']='budget';v=M.exact_pair(parity,a,b);self.assertEqual(v['status'],'unknown');self.assertEqual(v['incomplete_query_ids'],['q']);self.assertTrue(v['incomplete_outcome_differences']);self.assertEqual(M.exact_pair(parity,None,a,'missing',None)['status'],'unknown')
 def test_projection_cells_do_not_mix_budgets_blocks_or_windows(self):
  run={'variant_id':'finite20-lean-k5','requested_selector_limit':5,'block':1,'window':'w'};self.assertEqual(M.projections(run),[('finite20-lean-k5',5,1,'w'),('finite20-lean-k5',5,1,'all_windows'),('finite20-lean-k5',5,'both_blocks','w'),('finite20-lean-k5',5,'both_blocks','all_windows')])
 def test_independent_rule_adjusted_slack_after_walk_and_continuation(self):
  rides={'a':{'trip_id':'t','sequence':0,'arrival':10,'departure':0},'b':{'trip_id':'t','sequence':1,'arrival':20,'departure':11},'c':{'trip_id':'u','sequence':0,'arrival':50,'departure':40}};checker=types.SimpleNamespace(rides=rides,transfer=lambda a,b,f:(True,15));q={'departure':0,'transfer_buffer':0};v={'journey':{'legs':[{'kind':'ride','ref':'a','arrival':10},{'kind':'ride','ref':'b','arrival':20},{'kind':'walk','ref':'w','arrival':30},{'kind':'ride','ref':'c','arrival':50}]}};self.assertEqual(M.observed_slacks(checker,q,v),[5]);v['journey']['legs'][2]['arrival']=38;self.assertEqual(M.observed_slacks(checker,q,v),[2])
 def test_ride_patterns_exclude_all_walk_and_fill_does_not_imply_finite20_dominance(self):
  features={'a':{'pattern':json.dumps([{'kind':'walk','footpath':'w'}])},'b':{'pattern':json.dumps([{'kind':'ride','route':'r','stops':['a','b']}])}};physical,ride=M.pattern_sets(features,['a','b']);self.assertEqual((len(physical),len(ride)),(2,1));self.assertEqual(len(M.pattern_sets(features,['a'])[1]),0);self.assertIsNone(M.pattern_overlap(set(),set())['jaccard']);self.assertEqual(M.pattern_overlap({'a'},{'b','c'})['pattern_count_delta_vs_finite20'],-1)
if __name__=='__main__':unittest.main()
