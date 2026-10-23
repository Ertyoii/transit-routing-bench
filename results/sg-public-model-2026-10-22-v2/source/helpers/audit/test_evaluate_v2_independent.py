"""Original synthetic negative evaluator tests; no SG outcomes or routing runs."""
import copy,hashlib,importlib.util,json,pathlib,sys,tempfile,unittest
P=pathlib.Path('/workspace/shared/sg-coldstart');TARGET=P/'campaign-v2-20261021/analysis/evaluate_v2.py'
s=importlib.util.spec_from_file_location('eval_v2_review',TARGET);e=importlib.util.module_from_spec(s);s.loader.exec_module(e)
sys.path.insert(0,str(P/'evalkit'));import test_evalkit as fixture
H='1'*64

def summary():return {'algorithm':'raptor','dataset_sha256':H,'queries_sha256':H,'provenance':{'runtime_matches_build':True,'source_binding':'embedded_build_source','build_source_sha256':H,'runtime_tree_sha256':H,'routing_source_sha256':H,'executable_sha256':H}}
def command():return {'binary':{'sha256':H},'sources_before':[{'go_source_hash_sha256':H}]}
def timing():return {'response_ns':100,'quality_ns':10,'validation_rank_ns':20,'core_ns':50,'published_response_ns':105,'serialization_ns':5,'service_start_offset_ns':0,'search_done_offset_ns':50,'validation_start_offset_ns':80}

class Helpers(unittest.TestCase):
 def test_good_summary(self):e.validate_summary_binding(summary(),command(),'raptor',H,H)
 def test_summary_missing_hash_digests_rejected(self):
  x=summary();x['provenance'].pop('routing_source_sha256');x['provenance'].pop('executable_sha256')
  with self.assertRaises(ValueError):e.validate_summary_binding(x,{},'raptor',H,H)
 def test_summary_nonhex_matching_source_rejected(self):
  x=summary();x['provenance']['build_source_sha256']=x['provenance']['runtime_tree_sha256']='bogus'
  with self.assertRaises(ValueError):e.validate_summary_binding(x,{},'raptor',H,H)
 def test_summary_missing_embedded_binding_rejected(self):
  x=summary();x['provenance']['source_binding']='unbound'
  with self.assertRaises(ValueError):e.validate_summary_binding(x,command(),'raptor',H,H)
 def test_summary_supervisor_binary_mismatch(self):
  c=command();c['binary']['sha256']='2'*64
  with self.assertRaises(ValueError):e.validate_summary_binding(summary(),c,'raptor',H,H)
 def test_pass_wrong_hash_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'pass.json';p.write_text('{}')
   with self.assertRaises(ValueError):e.validate_pass_binding({'records':[],'algorithm':'raptor','repetition':0,'warmup':False},{'sha256':H,'repetition':0,'warmup':False},'raptor',p)
 def test_pass_unsafe_filename_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'pass.json';p.write_text('{}')
   with self.assertRaises(ValueError):e.validate_pass_binding({'records':[],'algorithm':'raptor','repetition':0,'warmup':False},{'file':'../outside.json','sha256':e.sha(p),'repetition':0,'warmup':False},'raptor',p)
 def test_good_timing(self):e.validate_row_timing(timing())
 def test_negative_serialization_rejected(self):
  r=timing();r['serialization_ns']=-1
  with self.assertRaises(ValueError):e.validate_row_timing(r)
 def test_serialization_longer_than_publication_gap_rejected(self):
  r=timing();r['serialization_ns']=50
  with self.assertRaises(ValueError):e.validate_row_timing(r)
 def test_boolean_core_timing_rejected(self):
  r=timing();r['core_ns']=True
  with self.assertRaises(ValueError):e.validate_row_timing(r)
 def test_core_exceeds_search_interval_rejected(self):
  r=timing();r['core_ns']=60
  with self.assertRaises(ValueError):e.validate_row_timing(r)
 def test_published_before_response_rejected(self):
  r=timing();r['published_response_ns']=99
  with self.assertRaises(ValueError):e.validate_row_timing(r)
 def test_default_display_schema(self):
  q=fixture.query();c=e.legacy.Checker(fixture.dataset());r=fixture.row(c,q,[fixture.journey('slow')]);self.assertEqual(e.selected_ids(r),[r['final'][0]['identity']])
 def test_continuous_missing_does_not_fallback(self):
  with self.assertRaises(ValueError):e.selected_ids({'recommendation_quality':{'continuous_choices':{'complete':True,'selections':[]}},'display_options':{'3':{'options':[]}}})
 def test_finite_incomplete_does_not_fallback(self):
  with self.assertRaises(ValueError):e.selected_ids({'recommendation_quality':{'choices':{'complete':False,'groups':[{'selections':[{'limit':3,'method':'preference_minimax','complete':True,'selected':['pretend']}]}]}}})
 def test_oracle_changed_frozen_query(self):
  q=fixture.query();z={'query':dict(q,departure=1),'weight_index':0,'weight':{'transfer_seconds':0,'extra_walk_weight':0}}
  with self.assertRaises(ValueError):e.validate_oracle_slot(z,{}, {'q':q},[z['weight']],set())
 def test_oracle_boolean_index_rejected(self):
  q=fixture.query();ws=[{'transfer_seconds':0,'extra_walk_weight':0},{'transfer_seconds':1,'extra_walk_weight':0}];z={'query':q,'weight_index':True,'weight':ws[1]}
  with self.assertRaises(ValueError):e.validate_oracle_slot(z,{}, {'q':q},ws,set())
 def test_oracle_duplicate_slots(self):
  q=fixture.query();w={'transfer_seconds':0,'extra_walk_weight':0};z={'query':q,'weight_index':0,'weight':w};seen=set();e.validate_oracle_slot(z,{}, {'q':q},[w],seen)
  with self.assertRaises(ValueError):e.validate_oracle_slot(z,{}, {'q':q},[w],seen)
 def test_failure_coverage_denominator(self):
  v={'duration_seconds':10,'metrics':{'transfers':0,'walking_seconds':0}};w=[{'transfer_seconds':0,'extra_walk_weight':0}];r=e.score_stage([v],[v],w,False);self.assertEqual((r['eligible'],r['covered'],r['missing']),(1,0,True));self.assertIsNone(r.get('regret'))
 def test_empty_unknown_not_perfect(self):
  r=e.score_stage([],[],[{'transfer_seconds':0,'extra_walk_weight':0}],True);self.assertEqual(r['eligible'],0);self.assertTrue(r['reference_empty_or_unavailable'])
 def test_lofo_negative_is_reference_deficiency(self):
  a={'duration_seconds':10,'metrics':{'transfers':0,'walking_seconds':0}};b={'duration_seconds':20,'metrics':{'transfers':0,'walking_seconds':0}};r=e.score_stage([a],[b],[{'transfer_seconds':0,'extra_walk_weight':0}],True);self.assertEqual(r['regrets'],[-10]);self.assertEqual(r['counterexample_slots'],1)

if __name__=='__main__':unittest.main(verbosity=2)
