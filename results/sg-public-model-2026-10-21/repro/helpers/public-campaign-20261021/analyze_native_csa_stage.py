#!/usr/bin/env python3
"""Same-query native strict-k10 versus point-anchor outcome/quality accounting."""
import argparse,json,pathlib,subprocess,sys,importlib.util,datetime,hashlib
R=pathlib.Path(__file__).resolve().parents[1];O=R/'public-campaign-20261021';P=O/'resumed-0130'
def mod(name,file):
 s=importlib.util.spec_from_file_location(name,file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
summ=mod('summ',O/'summarize_campaigns.py');cmp=mod('cmp',O/'compare_optimization.py')
def native_compare(left,right):
 p=cmp.compare(left,right);_,a=cmp.load(left);_,b=cmp.load(right);aa={v['query']['id']:v for v in a['records']};bb={v['query']['id']:v for v in b['records']};joint=lambda k:aa[k].get('completed') and bb[k].get('completed') and aa[k].get('status')=='complete' and bb[k].get('status')=='complete'
 complete=[v for v in p['semantic_mismatches'] if joint(v['query_id'])];unknown=[v for v in p['semantic_mismatches'] if not joint(v['query_id'])];p.update(raw_field_difference_count=p['semantic_mismatch_count'],joint_complete_native_witness_difference_count=len(complete),joint_complete_native_witness_differences=complete,unavailable_or_status_difference_count=len(unknown),unavailable_or_status_differences=unknown,classification_scope='Rawfielddifferences on deadlines/unavailable pairs are unknownnativeoutput, not demonstrated source correctness failures; originalfailuredenominators remain.')
 return p
def main():
 a=argparse.ArgumentParser();a.add_argument('--csa',type=pathlib.Path,required=True,action='append');a.add_argument('--anchors',type=pathlib.Path,required=True,action='append');a.add_argument('--prefix',required=True);a.add_argument('--stage',choices=['validation','test'],required=True);a.add_argument('--replication',type=pathlib.Path);x=a.parse_args()
 for c in x.csa+x.anchors+([x.replication] if x.replication else []):assert json.load(open(c/'status.json'))['state']=='completed'
 rows=[v for c in x.csa+x.anchors for v in summ.summarize(c)];rep=summ.summarize(x.replication) if x.replication else []
 m={'schema':'sg_native_csa90_outcome_metrics_v1','stage':x.stage,'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'rows':rows,'offered':sum(v['declared_offered_queries'] for v in rows),'complete':sum(v['complete'] for v in rows),'replication_rows_separate_not_new_demand':rep,'scope':'ALL90 registered screen requests/window,30unorderedparentODclusters,3departures, fourwindows, nooutcomefilter. Nativeidentitystrictk10 arrival/score versus2D/3Dpointanchors, not equivalentwork orprimary450qualification. Batch1 sharedcompatibility not batchinggain. Failureszero deliveredeligible coverage andnull regret; partialwitnesses diagnostic only.','topk_qualification':'csa-optimization-deliverable/INDEPENDENT_REVIEW.md plus exacttiny exhaustive k1/3/5/10tests; largeeval doesnotcertify identitytopk completeness.'};(P/f'{x.prefix}_METRICS.json').write_text(json.dumps(m,indent=2)+'\n')
 specs=[z for c in x.csa for z in json.load(open(c/'plan.json'))['runs']];aspecs=[z for c in x.anchors for z in json.load(open(c/'plan.json'))['runs']];origins={z['id']:c/z['id'] for c in x.csa+x.anchors for z in json.load(open(c/'plan.json'))['runs']};find=lambda ss,w,t:next(z for z in ss if f'-{w}-' in z['id'] and t in z['id'])
 pairs=[]
 for w in ['morning','midday','evening','overnight']:
  for key in ['arrival','score']:
   left=find(specs,w,'csa_'+key+'_single');right=find(specs,w,'csa_'+key+'_shared');p=native_compare(origins[left['id']],origins[right['id']]);p['scope']='Same90nativecontract outputs, singleversusshared atbatch1; anydeadline/completeness differences retained, not semanticparity failure for unavailablepairs.';pairs.append(p)
 if x.replication:
  old=find(specs,'morning','csa_score_single');new=json.load(open(x.replication/'plan.json'))['runs'][0];p=native_compare(origins[old['id']],x.replication/new['id']);p['scope']='Timingnoise-triggered same-source same-config replication; originalfailure remains, jointcomplete witnesses compared, no deadlineblame claim.';pairs.append(p)
 (P/f'{x.prefix}_PAIR_COMPARISONS.json').write_text(json.dumps({'pairs':pairs,'warning':'Status/certificate differences caused by genuine deadline failure remain unknownnativeoutput pairs; do not count as completewitnessmismatch or silentlydiscard.'},indent=2)+'\n')
 for w in ['morning','midday','evening','overnight']:
  q=O/f'bound-conservative600-v2/weekday-{w}-20261020.screen.{x.stage}.primary_1h_walk600.json';dataset=R/f'data-enriched/conservative600/weekday-{w}-20261020/dataset.json';out=P/f'evalkit-{x.stage}-csa90-default-{w}';cmd=[sys.executable,str(R/'evalkit/evalkit.py'),'--dataset',str(dataset),'--queries',str(q),'--query-metadata',str(q).replace('.json','.metadata.json'),'--out',str(out)]
  for z in [v for v in specs if f'-{w}-' in v['id']]:cmd+=['--run',str(origins[z['id']]/'artifact')]
  for z in [v for v in aspecs if f'-{w}-' in v['id']]:cmd+=['--run',str(origins[z['id']]/'artifact')]
  subprocess.run(cmd,check=True)
  anchor=find(aspecs,w,'mc-early-dense-labels500000-finite20');out2=P/f'evalkit-{x.stage}-csa90-finite-{w}';subprocess.run([sys.executable,str(R/'evalkit/evalkit.py'),'--dataset',str(dataset),'--queries',str(q),'--query-metadata',str(q).replace('.json','.metadata.json'),'--reference-pool',str(out/'pool.json'),'--config',str(O/'configs/evalkit-finite20-top3.json'),'--run',str(origins[anchor['id']]/'artifact'),'--out',str(out2)],check=True)
 for group in ['default','finite']:
  subprocess.run([sys.executable,str(O/'summarize_quality_windows.py'),*[str(P/f'evalkit-{x.stage}-csa90-{group}-{w}') for w in ['morning','midday','evening','overnight']],'--out',str(P/(f'{x.prefix}_QUALITY'+('' if group=='default' else '_FINITE')+'.json'))],check=True)
 print('nativeCSA90METRICS',m['offered'],m['complete'],flush=True)
if __name__=='__main__':main()
