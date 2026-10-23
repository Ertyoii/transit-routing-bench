"""Independent tiny synthetic receipt/parity/count mutation checks; never routes."""
import contextlib,copy,importlib.util,io,json,pathlib,tempfile,unittest
import test_evaluate_v2_integration as integ
E=integ.e
P=pathlib.Path('/workspace/shared/sg-coldstart/campaign-v2-20261021/analysis/compare_native_outputs.py')
s=importlib.util.spec_from_file_location('native_parity_review',P);p=importlib.util.module_from_spec(s);s.loader.exec_module(p)

def receipt():
 rows=[{'query':{'id':'q'},'status':'complete','complete':True,'row':{'batch':0,'published_response_ns':105,'serialization_ns':5}}]
 sup={'first_available_answer_events':[{'supervisor_received_since_spawn_ns':200,'payload':{'query_id':'q','process_elapsed_ns':150,'published_response_ns':105,'serialization_ns':5}}],'publication_receipt':{'valid':True},'launch_to_first_available_answer_ns':200}
 return sup,rows

class FirstAnswer(unittest.TestCase):
 def test_good(self):
  s,r=receipt();v=E.first_answer_acceptance(s,r);self.assertEqual(v['accepted_native_launch_to_first_available_answer_ns'],200);self.assertTrue(v['first_marker_matches_first_offered_query'])
 def test_bad_event_cardinality(self):
  for n in [0,2]:
   s,r=receipt();s['first_available_answer_events']*=n;self.assertIsNone(E.first_answer_acceptance(s,r)['accepted_native_launch_to_first_available_answer_ns'])
 def test_invalidated_first_not_replaced_by_later(self):
  s,r=receipt();r[0]['complete']=False;r[0]['status']='native_contract_counterexample';r.append({'query':{'id':'later'},'status':'complete','complete':True,'row':{'batch':1}});v=E.first_answer_acceptance(s,r);self.assertIsNone(v['accepted_native_launch_to_first_available_answer_ns']);self.assertFalse(v['first_offered_native_complete'])
 def test_wrong_or_duplicate_query(self):
  for duplicate in [False,True]:
   s,r=receipt()
   if duplicate:r*=2
   else:s['first_available_answer_events'][0]['payload']['query_id']='absent'
   self.assertIsNone(E.first_answer_acceptance(s,r)['accepted_native_launch_to_first_available_answer_ns'])
 def test_clock_mutations(self):
  for field,value in [('process_elapsed_ns',True),('process_elapsed_ns',-1),('process_elapsed_ns',201),('process_elapsed_ns',104),('published_response_ns',106),('serialization_ns',4),('serialization_ns',106)]:
   s,r=receipt();s['first_available_answer_events'][0]['payload'][field]=value;self.assertIsNone(E.first_answer_acceptance(s,r)['accepted_native_launch_to_first_available_answer_ns'],(field,value))
 def test_receipt_or_metric_mismatch(self):
  for key in ['receipt','metric']:
   s,r=receipt()
   if key=='receipt':s['publication_receipt']['valid']=False
   else:s['launch_to_first_available_answer_ns']=201
   self.assertIsNone(E.first_answer_acceptance(s,r)['accepted_native_launch_to_first_available_answer_ns'])
 def test_later_first_marker_is_named_not_silently_equalized(self):
  s,r=receipt();r[0]['row']['batch']=1;r.insert(0,{'query':{'id':'earlier'},'status':'deadline','complete':False,'row':{'batch':0}});v=E.first_answer_acceptance(s,r);self.assertEqual(v['accepted_native_launch_to_first_available_answer_ns'],200);self.assertFalse(v['first_marker_matches_first_offered_query']);self.assertEqual(v['first_offered_query_id'],'earlier')
 def test_multirequest_first_batch_is_not_unique_first_request(self):
  s,r=receipt();r.append({'query':{'id':'other'},'status':'deadline','complete':False,'row':{'batch':0}});v=E.first_answer_acceptance(s,r);self.assertIsNone(v['first_marker_matches_first_offered_query']);self.assertEqual(v['first_offered_batch_query_ids'],['other','q'])

class Parity(unittest.TestCase):
 def setup_pair(self,root):
  query={'id':'q','origin':'a','destination':'b'};work=root/'work.json';integ.write(work,{'items':[{'query':query,'stratum':'s'}]});runs=[]
  for name in ['raptor-control','raptor-storage']:
   run={'id':name,'variant_id':name,'block':0,'window':'s','argv':['-queries',str(work),'-algorithm','raptor']};runs.append(run);art=root/name/'artifact'
   row={'query':query,'stratum':'s','raw':[{'legs':[1,2]}],'final':[{'identity':'x'}],'completed':True,'attempted':True,'valid_empty':False,'transit':True,'status':'complete','error':'','certificates':{'earliest_arrival':True}}
   pay={'algorithm':'raptor','repetition':0,'warmup':False,'records':[row]};digest=integ.write(art/'pass.json',pay);integ.write(art/'summary.json',{'algorithm':'raptor','queries_sha256':p.sha(work),'preparation':{'complete':True},'passes':[{'file':'pass.json','sha256':digest,'repetition':0,'warmup':False,'forced':False}]});integ.write(root/name/'result.json',{'ok':True})
  integ.write(root/'plan.json',{'runs':runs});return runs
 def mutate_pass(self,root,fn):
  art=root/'raptor-storage/artifact';pay=p.read(art/'pass.json');fn(pay);digest=integ.write(art/'pass.json',pay);summary=p.read(art/'summary.json');summary['passes'][0]['sha256']=digest;integ.write(art/'summary.json',summary)
 def result(self,root):
  with contextlib.redirect_stdout(io.StringIO()):p.compare(root,root/'report.json')
  return p.read(root/'report.json')
 def test_good_exact_and_forced_excluded(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);self.setup_pair(root);sp=root/'raptor-storage/artifact/summary.json';v=p.read(sp);v['passes'].append({'forced':True,'file':'must-not-read.json'});integ.write(sp,v);v=self.result(root);self.assertEqual(v['exact_checks'],1)
 def test_no_ordinary_or_missing_record_is_unknown(self):
  for mode in ['no_pass','empty_records','missing_file']:
   with tempfile.TemporaryDirectory() as td:
    root=pathlib.Path(td);self.setup_pair(root)
    if mode=='empty_records':self.mutate_pass(root,lambda x:x.update(records=[]))
    elif mode=='missing_file':(root/'raptor-storage/artifact/summary.json').unlink()
    else:
     sp=root/'raptor-storage/artifact/summary.json';v=p.read(sp);v['passes']=[];integ.write(sp,v)
    self.assertEqual(self.result(root)['unknown_checks'],1)
 def test_bad_pass_binding(self):
  for field,val in [('algorithm','other'),('repetition',1),('warmup',True)]:
   with tempfile.TemporaryDirectory() as td:
    root=pathlib.Path(td);self.setup_pair(root);self.mutate_pass(root,lambda x:x.update({field:val}))
    with self.assertRaises(ValueError):self.result(root)
 def test_bad_query_binding(self):
  for field,val in [('query',{'id':'q','origin':'changed','destination':'b'}),('stratum','wrong')]:
   with tempfile.TemporaryDirectory() as td:
    root=pathlib.Path(td);self.setup_pair(root);self.mutate_pass(root,lambda x:x['records'][0].update({field:val}))
    with self.assertRaises(ValueError):self.result(root)
 def test_complete_witness_or_certificate_difference(self):
  for field,val in [('raw',[{'legs':[2,1]}]),('final',[{'identity':'different'}]),('certificates',{})]:
   with tempfile.TemporaryDirectory() as td:
    root=pathlib.Path(td);self.setup_pair(root);self.mutate_pass(root,lambda x:x['records'][0].update({field:val}));v=self.result(root);self.assertEqual(v['mismatch_checks'],1);self.assertIn(field,v['checks'][0]['differences'][0]['fields'])
 def test_incomplete_is_unknown_not_mismatch(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);self.setup_pair(root);self.mutate_pass(root,lambda x:x['records'][0].update(completed=False,status='deadline',final=[]));v=self.result(root);self.assertEqual(v['unknown_checks'],1);self.assertEqual(v['mismatch_checks'],0);self.assertTrue(v['checks'][0]['incomplete_outcome_differences'])

class DeliveredCounts(unittest.TestCase):
 def evaluate(self,refs):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=pathlib.Path(temp.name);fixture=integ.Integration();rows=[]
  for name,alg,journeys,change in refs:
   row=fixture.row(journeys);row.update(change);rows.append((name,alg,row))
  cp,*_=fixture.setup_files(root,rows);out=fixture.evaluate(root,cp);return {x['id']:x for x in E.read(out/'METRICS_BY_RUN.json')}
 def test_native_rejected_transit_not_delivered(self):
  m=self.evaluate([('bad','raptor',[('slow',)],{}),('good','mc_raptor',[('ax','bd'),('slow',)],{})]);b=m['bad'];self.assertEqual(b['emitter_declared_transit'],1);self.assertEqual(b['independently_feasible_transit_rows_including_incomplete'],1);self.assertEqual(b['transit'],0);self.assertEqual(b['transit_response_ns']['count'],0);self.assertEqual(b['common_pool_cohorts']['pool_has_transit']['offered'],1);self.assertEqual(b['common_pool_cohorts']['pool_has_transit']['independently_complete'],0)
 def test_rejected_empty_claim_not_delivered(self):
  b=self.evaluate([('bad','raptor',[('slow',)],{'valid_empty':True})])['bad'];self.assertEqual(b['declared_native_valid_empty'],1);self.assertEqual(b['independently_completed_empty_deliveries'],0);self.assertEqual(b['statuses'],{'independent_validation_error':1})
 def test_true_empty_explicit_unknown_pool_cohort(self):
  b=self.evaluate([('empty','raptor',[],{})])['empty'];self.assertEqual(b['independently_completed_empty_deliveries'],1);self.assertEqual(b['common_pool_cohorts']['pool_empty_or_unknown']['offered'],1);self.assertEqual(b['common_pool_cohorts']['pool_empty_or_unknown']['complete_response_ns']['count'],1);self.assertEqual(b['common_pool_cohorts']['pool_walk_only']['offered'],0)
 def test_walk_only_cohort(self):
  b=self.evaluate([('walk','raptor',[('od',)],{})])['walk'];self.assertEqual(b['transit'],0);self.assertEqual(b['common_pool_cohorts']['pool_walk_only']['offered'],1);self.assertEqual(b['common_pool_cohorts']['pool_walk_only']['complete_response_ns']['count'],1);self.assertEqual(b['common_pool_transit_response_ns']['count'],0)

if __name__=='__main__':unittest.main(verbosity=2)
