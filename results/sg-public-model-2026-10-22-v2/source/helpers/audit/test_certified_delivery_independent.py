"""Original end-to-end tiny fixtures for requested3/5 certified delivery, no routers."""
import collections,contextlib,copy,hashlib,importlib.util,io,json,pathlib,tempfile,unittest
import test_evaluate_v2_integration as old
C=pathlib.Path('/workspace/shared/sg-coldstart/campaign-v2-20261021');s=importlib.util.spec_from_file_location('certified_independent',C/'analysis/evaluate_v2_certified_delivery.py');n=importlib.util.module_from_spec(s);s.loader.exec_module(n)
class Certified(unittest.TestCase):
 def execute(self,ks=(3,5),mutation=None):
  td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);root=pathlib.Path(td.name);f=old.Integration();rows=[];configs={}
  for k in ks:
   r=f.row([('slow',)]);r['display_options']={};cfg={'bounded':{'limits':[k],'objective':'absolute','min_transfer_seconds':0,'max_transfer_seconds':900,'min_extra_walk_weight':0,'max_extra_walk_weight':4}};r['recommendation_quality']={'continuous_choices':{'complete':True,'config':cfg['bounded'],'selections':[{'limit':k,'complete':True,'selected':[v['identity']for v in r['final']]}]}};rows.append(('run'+str(k),'raptor',r));configs[k]=cfg
  cp,*_=f.setup_files(root,rows)
  for k in ks:
   run=cp/('run'+str(k));art=run/'artifact';cfgp=root/('cfg'+str(k)+'.json');digest=old.write(cfgp,configs[k]);summary=n.read(art/'summary.json');summary.update(quality_enabled=True,preference_config=configs[k],preference_config_sha256=digest,display_k=[]);old.write(art/'summary.json',summary);plan=n.read(cp/'plan.json');r=next(z for z in plan['runs']if z['id']=='run'+str(k));r['argv']+=['-quality','-display-k','-1','-preference-scenarios',str(cfgp),'-out-dir',str(art)];old.write(cp/'plan.json',plan);command=n.read(run/'command.json');command.update(argv=['/usr/bin/taskset','-c','0-3']+r['argv'],inputs=[{'path':str(cfgp),'bytes':cfgp.stat().st_size,'sha256':digest}]);old.write(run/'command.json',command)
   if mutation:
    p=n.read(art/'pass-00.json');mutation(k,p['records'][0]);ph=old.write(art/'pass-00.json',p);summary=n.read(art/'summary.json');summary['passes'][0]['sha256']=ph;old.write(art/'summary.json',summary)
  previous=n.ROOT;n.ROOT=root
  try:
   with contextlib.redirect_stdout(io.StringIO()):n.evaluate([str(cp)],[],root/'out','per-run')
  finally:n.ROOT=previous
  return root/'out'
 def test_real_pipeline_top3_and_top5_are_distinct_complete_cohorts(self):
  out=self.execute();m=n.read(out/'METRICS_BY_RUN.json');self.assertEqual({z['delivery_k']for z in m},{3,5});self.assertTrue(all(z['completed']==1 for z in m));q=n.read(out/'QUALITY_AGGREGATE.json');self.assertEqual({z['delivery_k']for z in q},{3,5});self.assertEqual({z['display_label']for z in q},{'top3','top5'})
 def test_pipeline_wrong_requested_limit_is_not_accepted(self):
  def change(k,r):r['recommendation_quality']['continuous_choices']['selections'][0]['limit']=8-k
  out=self.execute(mutation=change);self.assertTrue(all(z['completed']==0 for z in n.read(out/'METRICS_BY_RUN.json')))
 def test_pipeline_duplicate_identity_is_not_accepted(self):
  def change(k,r):r['recommendation_quality']['continuous_choices']['selections'][0]['selected']*=2
  out=self.execute(mutation=change);self.assertTrue(all(z['completed']==0 for z in n.read(out/'METRICS_BY_RUN.json')))
 def test_pipeline_unrequested_display_rankings_are_not_certified(self):
  def change(k,r):r['display_options']={'3':{'options':[]}}
  out=self.execute(mutation=change);self.assertTrue(all(z['completed']==0 for z in n.read(out/'METRICS_BY_RUN.json')))
 def test_pure_binding_changed_file_bytes_rejected(self):
  with tempfile.TemporaryDirectory()as td:
   p=pathlib.Path(td)/'c.json';p.write_text(json.dumps({'lean_delivery':True,'delivery_policy':'finite_preferences_v2','delivery_limits':[5],'groups':[{}]}));digest=n.sha(p);args=['/binary','-quality','-display-k','-1','-preference-scenarios',str(p)];summary={'quality_enabled':True,'preference_config_sha256':digest,'preference_config':n.read(p),'display_k':[]};command={'argv':['/usr/bin/taskset','-c','0-3']+args,'inputs':[{'path':str(p),'bytes':p.stat().st_size,'sha256':digest}]};p.write_text(p.read_text()+' ')
   with self.assertRaises(ValueError):n.validate_delivery_binding(summary,command,args,'per-run',{})
if __name__=='__main__':unittest.main(verbosity=2)
