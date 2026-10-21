#!/usr/bin/env python3
"""Failure-inclusive primary validation/test source comparisons and static witness audit."""
import argparse,json,pathlib,subprocess,sys,importlib.util,datetime,hashlib
R=pathlib.Path(__file__).resolve().parents[1];O=R/'public-campaign-20261021';P=O/'resumed-0130'
def module(n,f):
 s=importlib.util.spec_from_file_location(n,f);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
summary=module('summarize_campaigns',O/'summarize_campaigns.py');cmp=module('compare_optimization',O/'compare_optimization.py')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--campaign',type=pathlib.Path,required=True);ap.add_argument('--prefix',required=True);ap.add_argument('--stage',choices=['validation','test'],required=True);ap.add_argument('--supplement',type=pathlib.Path,action='append',default=[]);a=ap.parse_args();c=a.campaign;s=json.load(open(c/'status.json'))
 campaigns=[c]+a.supplement;origins={};states=[];byid={}
 for campaign in campaigns:
  status=json.load(open(campaign/'status.json'));states.append({'campaign':str(campaign),'state':status['state'],'status_sha256':hashlib.sha256((campaign/'status.json').read_bytes()).hexdigest(),'completed_processes':len(status['completed_runs'])})
  assert status['state']=='completed' or (campaign==c and a.supplement and status['state']=='runner_error'),status['state']
  completed={x['id'] for x in status['completed_runs']}
  for row in summary.summarize(campaign):
   if row['run_id'] in completed:
    assert row['run_id'] not in origins, row['run_id'];origins[row['run_id']]=campaign/row['run_id'];byid[row['run_id']]=row
 all_specs=[x for cp in campaigns for x in json.load(open(cp/'plan.json'))['runs']];expected={x['id'] for x in (json.load(open(c/'plan.json'))['runs'] if a.stage=='validation' else all_specs)};assert set(origins)==expected,(expected-set(origins),set(origins)-expected)
 locate=lambda runid:origins[runid]
 ordered_specs=json.load(open(c/'plan.json'))['runs'] if a.stage=='validation' else all_specs;rows=[byid[x['id']] for x in ordered_specs];metrics={'schema':'sg_primary_offered_outcome_metrics_v1','stage':a.stage,'campaign':str(c),'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_campaign_states':states,'analysis_accounting':'Unique predeclared logical runs; original prelaunch-unstarted slots are retained in originalrunnerstatus, not counted as new native attempts. Continuation origins explicit; original runner_error is not relabeled completed.','rows':rows,'offered':sum(x['declared_offered_queries'] for x in rows),'complete':sum(x['complete'] for x in rows),'limitations':['Nearest-rank empirical attempted/success/transit quantiles separately, all offered failures retained.','Public community-frequency modeled timetable and conservative OSM walking, not latest-official or physical reachability.','In-process queued response includes checker/ranking/quality, excludes parsing/prep/serialization; soft/sample memory safeguards, no hard exclusivity or disk-cold guarantee.','Native2D/3D/topk contracts distinct; no cross-contract equalquality speedup/globalconvergence claim.']};(P/f'{a.prefix}_METRICS.json').write_text(json.dumps(metrics,indent=2)+'\n')
 pairs=[]
 for w in ['morning','midday','evening','overnight']:
  for x,y in [('raptor-baseline','raptor-dense'),('raptor-early-baseline','raptor-early-dense'),('ea-baseline','ea-combined'),('ultra-control-baseline','ultra-control-dense'),('mc-dense-labels500000-finite20','mc-dense-labels1000000-finite20'),('mc-early-dense-labels500000-finite20','mc-early-dense-labels1000000-finite20')]:
   left=origins.get(f'{a.stage}-{w}-{x}',c/f'{a.stage}-{w}-{x}');right=origins.get(f'{a.stage}-{w}-{y}',c/f'{a.stage}-{w}-{y}')
   if left.exists() and right.exists():
    try:r=cmp.compare(left,right);r['scope']=f'{a.stage} exactnative emitted witness/status/certification comparison; resource/deadline differences remain visible, not fullmodel independent oracle';pairs.append(r)
    except (OSError,AssertionError,KeyError,StopIteration) as e:pairs.append({'baseline':str(left),'candidate':str(right),'unavailable_reason':repr(e),'semantic_unknown':True})
 (P/f'{a.prefix}_SOURCE_PARITY.json').write_text(json.dumps({'stage':a.stage,'pairs':pairs,'semantic_mismatch_count':sum(x.get('semantic_mismatch_count',0) for x in pairs),'unknown_pairs':sum(bool(x.get('semantic_unknown')) for x in pairs)},indent=2)+'\n')
 print('METRICS',a.prefix,metrics['offered'],metrics['complete'],'source_mismatches',sum(x.get('semantic_mismatch_count',0) for x in pairs),flush=True)
 # Stable, unique native algorithm IDs in shared union.500k is budget selection target;
 # validation1m forms commonpool so any500k failures can be scored against it.
 labels='1000000' if a.stage=='validation' else '500000'
 for w in ['morning','midday','evening','overnight']:
  q=O/f'bound-conservative600-v2/weekday-{w}-20261020.full.{a.stage}.primary_1h_walk600.json';dataset=R/f'data-enriched/conservative600/weekday-{w}-20261020/dataset.json'
  tails=['raptor-early-dense','ea-combined','ultra-control-dense','ultra-subset-dense',f'mc-dense-labels{labels}-finite20',f'mc-early-dense-labels{labels}-finite20','trip-based-capped-100m']
  if a.stage=='test':tails.insert(0,'raptor-dense')
  # Explicit suffix matching protects against accidentally changing pool membership.
  specs=ordered_specs;runs=[]
  for t in tails:
   hits=[x for x in specs if x['id'].startswith(f'{a.stage}-{w}-') and x['id'].endswith(t)];assert len(hits)==1,(w,t,[x['id'] for x in hits]);runs.append(locate(hits[0]['id'])/'artifact')
  out=P/f'evalkit-{a.stage}-primary-default-{w}';cmd=[sys.executable,str(R/'evalkit/evalkit.py'),'--dataset',str(dataset),'--queries',str(q),'--query-metadata',str(q).replace('.json','.metadata.json'),'--out',str(out)]
  for d in runs:cmd+=['--run',str(d)]
  subprocess.run(cmd,check=True)
  for budget in ([1000000,500000] if a.stage=='validation' else [500000]):
   runs2=[locate(f'{a.stage}-{w}-mc-dense-labels{budget}-finite20')/'artifact',locate(f'{a.stage}-{w}-mc-early-dense-labels{budget}-finite20')/'artifact'];out2=P/f'evalkit-{a.stage}-primary-finite{budget}-{w}';cmd=[sys.executable,str(R/'evalkit/evalkit.py'),'--dataset',str(dataset),'--queries',str(q),'--query-metadata',str(q).replace('.json','.metadata.json'),'--reference-pool',str(out/'pool.json'),'--config',str(O/'configs/evalkit-finite20-top3.json'),'--out',str(out2)]
   for d in runs2:cmd+=['--run',str(d)]
   subprocess.run(cmd,check=True)
 for group in ['default']+(['finite1000000','finite500000'] if a.stage=='validation' else ['finite500000']):
  cmd=[sys.executable,str(O/'summarize_quality_windows.py'),*[str(P/f'evalkit-{a.stage}-primary-{group}-{w}') for w in ['morning','midday','evening','overnight']],'--out',str(P/f'{a.prefix}_QUALITY_{group.upper()}.json')];subprocess.run(cmd,check=True)
if __name__=='__main__':main()
