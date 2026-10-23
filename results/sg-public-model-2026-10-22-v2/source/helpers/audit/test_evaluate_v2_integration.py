"""Original synthetic integration mutations. Never runs a router or SG outcomes."""
import contextlib,copy,hashlib,importlib.util,io,json,pathlib,sys,tempfile,unittest
BASE=pathlib.Path('/workspace/shared/sg-coldstart');s=importlib.util.spec_from_file_location('ev2integration',BASE/'campaign-v2-20261021/analysis/evaluate_v2.py');e=importlib.util.module_from_spec(s);s.loader.exec_module(e);sys.path.insert(0,str(BASE/'evalkit'));import test_evalkit as f
H='1'*64

def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return e.sha(p)

class Integration(unittest.TestCase):
 def setup_files(self,root,rows):
  d=f.dataset();q=f.query();data=root/'dataset.json';dh=write(data,d);work=root/'work.json';wh=write(work,{'dataset_sha256':dh,'items':[{'stratum':'original_synthetic','query':q}]})
  configs=root/'selector-quality/configs';weights=[{'transfer_seconds':0,'extra_walk_weight':0},{'transfer_seconds':300,'extra_walk_weight':0}];write(configs/'heldout393.json',weights);write(configs/'scalar9.json',weights)
  campaign=root/'campaign';runs=[]
  for name,alg,r in rows:
   run=campaign/name;art=run/'artifact';payload={'algorithm':alg,'repetition':0,'warmup':False,'records':[r],'batches':[]};ph=write(art/'pass-00.json',payload)
   summary={'algorithm':alg,'kind':'pareto_walking' if alg.startswith('mc') else 'pareto','dataset_sha256':dh,'queries_sha256':wh,'provenance':{'runtime_matches_build':True,'source_binding':'embedded_build_source','build_source_sha256':H,'runtime_tree_sha256':H,'routing_source_sha256':H,'executable_sha256':H},'passes':[{'file':'pass-00.json','sha256':ph,'repetition':0,'warmup':False,'forced':False,'requested':1,'makespan_ns':1000}]}
   write(art/'summary.json',summary);write(run/'command.json',{'binary':{'sha256':H},'sources_before':[{'go_source_hash_sha256':H}]});write(run/'result.json',{'ok':True,'process_wall_s':1})
   runs.append({'id':name,'variant_id':name,'window':'synthetic','argv':['ignored','-dataset',str(data),'-queries',str(work),'-algorithm',alg]})
  write(campaign/'plan.json',{'runs':runs});return campaign,dh,work,weights
 def row(self,refs,pareto=True):
  c=e.legacy.Checker(f.dataset());q=f.query();r=f.row(c,q,[f.journey(*x) for x in refs]);r['recommendation_quality']={'continuous_choices':{'complete':True,'selections':[{'limit':3,'complete':True,'selected':[x['identity'] for x in r['final']]}]}};r['certificates']={'arrival_boardings':pareto,'earliest_arrival':True,'best_score':True};return r
 def evaluate(self,root,campaign,oracle=[]):
  previous=e.ROOT;e.ROOT=root
  try:
   with contextlib.redirect_stdout(io.StringIO()):e.evaluate([str(campaign)],oracle,root/'out')
  finally:e.ROOT=previous
  return root/'out'
 def test_valid_control_row_stays_complete(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);cp,*_=self.setup_files(root,[('one','raptor',self.row([('ax','bd'),('slow',)]))]);out=self.evaluate(root,cp);m=e.read(out/'METRICS_BY_RUN.json');self.assertEqual(m[0]['completed'],1)
 def test_native_falsifier_removes_success_metrics_and_quality(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);cp,*_=self.setup_files(root,[('bad','raptor',self.row([('slow',)])),('good','mc_raptor',self.row([('ax','bd'),('slow',)]))]);out=self.evaluate(root,cp);m={x['id']:x for x in e.read(out/'METRICS_BY_RUN.json')};self.assertGreater(len(e.read(out/'NATIVE_COUNTEREXAMPLES.json')),0);self.assertEqual(m['bad']['completed'],0);self.assertEqual(m['bad']['complete_response_ns']['count'],0)
   qr=[json.loads(z)for z in (out/'QUALITY_ROWS.jsonl').read_text().splitlines()];b=[x for x in qr if x['run']=='bad'];self.assertTrue(all(not x['complete'] and x['score'].get('covered',0)==0 for x in b))
 def test_duplicate_final_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);r=self.row([('slow',)]);r['final']*=2;cp,*_=self.setup_files(root,[('one','raptor',r)]);out=self.evaluate(root,cp);m=e.read(out/'METRICS_BY_RUN.json');self.assertEqual(m[0]['completed'],0);self.assertGreater(len(e.read(out/'VALIDATION_ERRORS.json')),0)
 def test_valid_empty_mismatch_removes_success(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);r=self.row([('slow',)]);r['valid_empty']=True;cp,*_=self.setup_files(root,[('one','raptor',r)]);out=self.evaluate(root,cp);m=e.read(out/'METRICS_BY_RUN.json');self.assertEqual(m[0]['completed'],0)
 def test_missing_oracle_slots_retained_in_denominator(self):
  with tempfile.TemporaryDirectory() as td:
   root=pathlib.Path(td);r=self.row([('slow',)]);cp,dh,work,weights=self.setup_files(root,[('one','raptor',r)]);reference=root/'data-workload/workloads/synthetic.reference.primary_1h_walk600.json';wh=write(reference,e.read(work));p=root/'oracle.jsonl';q=f.query();header={'kind':'metadata','dataset_sha256':dh,'workload_sha256':wh,'weights_sha256':e.sha(root/'selector-quality/configs/scalar9.json'),'build_source_sha256':H,'max_labels':100,'max_transitions':1000,'timeout':'1s'};slot={'kind':'scalar_result','query':q,'weight_index':0,'weight':weights[0],'result':{'complete':False,'found':False},'error':'synthetic_budget'};p.write_text(json.dumps(header)+'\n'+json.dumps(slot)+'\n');out=self.evaluate(root,cp,[str(p)]);rep=e.read(out/'REPORT.json');self.assertEqual(rep['oracle_offered_slots'],2);slots=e.read(out/'INDEPENDENT_ORACLE_SLOTS.json');self.assertEqual(len(slots),2);self.assertTrue(all(not x['complete'] for x in slots))

if __name__=='__main__':unittest.main(verbosity=2)
