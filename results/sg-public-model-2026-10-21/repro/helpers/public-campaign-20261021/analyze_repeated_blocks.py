#!/usr/bin/env python3
"""Read-only, failure-inclusive repeated tune source comparison, standard library."""
import argparse, collections, hashlib, json, math, random, statistics
from pathlib import Path
FIELDS=['query','raw','final','display_options','completed','attempted','valid_empty','transit','status','error','certificates','recommendation_quality']
WINDOWS=['morning','midday','evening','overnight']
PAIRS=[('ultra-control-baseline','ultra-control-dense'),('ultra-subset-baseline','ultra-subset-dense'),('raptor-baseline','raptor-walking'),('raptor-walking','raptor-dense'),('raptor-baseline','raptor-dense'),('ea_csa_layered-baseline','ea_csa_layered-dense'),('ea_csa_layered-baseline','ea_csa_layered-combined'),('ea_csa_layered-dense','ea_csa_layered-combined'),('mc-early-walking-labels500000','mc-early-walking-labels1000000')]
def read(p):return json.loads(p.read_text())
def quant(x):
 x=sorted(x)
 return {'n':len(x),**{k:(x[max(0,math.ceil(len(x)*v)-1)]/1e6 if x else None) for k,v in [('p50_ms',.5),('p95_ms',.95),('p99_ms',.99),('max_ms',1)]}}
def load(c):
 status=read(c/'status.json');assert status['state']=='completed',status['state']
 out={}
 for x in read(c/'plan.json')['runs']:
  rd=c/x['id'];pr=read(rd/'result.json');sfile=rd/'artifact/summary.json';key=x['id'].split('-',2)[2];window=x['id'].split('-',2)[1];query=Path(x['argv'][x['argv'].index('-queries')+1]);offered=len(read(query)['items']);meta=read(query.with_suffix('.metadata.json'));clusters={i['query_id']:i['od_cluster'] for i in meta['items']};item={'run_id':x['id'],'window':window,'variant':key,'process_ok':pr['ok'],'offered':offered,'unresolved':0,'complete':0,'records':{},'clusters':clusters,'statuses':{},'peak_rss_bytes':pr.get('sampled_peak_process_group_rss_bytes'),'process_wall_s':pr.get('process_wall_s')}
  if not sfile.exists():item['unresolved']=offered;item['statuses']={'process_unresolved':offered};out[window,key]=item;continue
  s=read(sfile);passes=[v for v in s['passes'] if not v.get('forced') and not v.get('warmup')];assert len(passes)==1;pp=read(sfile.parent/passes[0]['file']);rows=pp['records'];assert len(rows)==offered;assert len({v['query']['id'] for v in rows})==offered;assert set(v['query']['id'] for v in rows)==set(clusters)
  attempted=[v['response_ns'] for v in rows if v['attempted']];success=[v['response_ns'] for v in rows if v['completed'] and v['status']=='complete'];transit=[v['response_ns'] for v in rows if v['completed'] and v['status']=='complete' and v['transit']]
  item.update(complete=len(success),transit=len(transit),valid_empty=sum(bool(v['valid_empty']) for v in rows),attempted=len(attempted),statuses=dict(collections.Counter(v['status'] for v in rows)),attempted_response=quant(attempted),complete_response=quant(success),transit_response=quant(transit),first_offered_response_ms=rows[0]['response_ns']/1e6,allocated_bytes=sum(v.get('allocated_bytes',0) for v in pp['batches']),router_prep_s=s['preparation']['elapsed_ns']/1e9,router_prep_allocated_bytes=s['preparation'].get('allocated_bytes'),load_s=s['input_load_ns']/1e9,checker_prep_s=s['checker_preparation']['elapsed_ns']/1e9,quality_prep_s=s.get('quality_preparation',{}).get('elapsed_ns',0)/1e9,records={v['query']['id']:v for v in rows},dataset_sha256=s['dataset_sha256'],queries_sha256=s['queries_sha256'],provenance=s['provenance'])
  out[window,key]=item
 return out

def compare(a,b):
 assert a['offered']==b['offered']
 if a['records'].keys()!=b['records'].keys() or not a['records']:
  return {'baseline':a['run_id'],'candidate':b['run_id'],'offered_pairs':a['offered'],'joint_complete':0,'semantic_mismatches':[],'semantic_unknown_pairs':a['offered'],'unavailable_reason':'Missing process/row evidence; no intersection-only source comparison','paired':[]}
 assert a.get('queries_sha256')==b.get('queries_sha256');assert a.get('dataset_sha256')==b.get('dataset_sha256')
 mismatch=[];paired=[]
 for k,x in a['records'].items():
  y=b['records'][k];fs=[f for f in FIELDS if x.get(f)!=y.get(f)]
  if fs:mismatch.append({'query_id':k,'fields':fs})
  if x['completed'] and y['completed'] and x['status']=='complete' and y['status']=='complete':paired.append({'cluster':a['clusters'][k],'delta_ns':y['response_ns']-x['response_ns'],'ratio':y['response_ns']/x['response_ns']})
 return {'baseline':a['run_id'],'candidate':b['run_id'],'offered_pairs':a['offered'],'joint_complete':len(paired),'semantic_mismatches':mismatch,'median_paired_delta_ms':statistics.median([v['delta_ns'] for v in paired])/1e6 if paired else None,'median_paired_ratio':statistics.median([v['ratio'] for v in paired]) if paired else None,'paired':paired}

def main():
 p=argparse.ArgumentParser();p.add_argument('campaigns',nargs='+',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();blocks=[load(c) for c in a.campaigns];pairs=[]
 for n,block in enumerate(blocks,1):
  for w in WINDOWS:
   for x,y in PAIRS:
    if (w,x) in block and (w,y) in block:pairs.append({'block':n,'window':w,**compare(block[w,x],block[w,y])})
 repeat=[]
 if len(blocks)>1:
  for w,k in blocks[0]:
   for n,b in enumerate(blocks[1:],2):
    if (w,k) in b:repeat.append({'second_block':n,'window':w,'variant':k,**compare(blocks[0][w,k],b[w,k])})
 conditional_ci=[]
 for w in WINDOWS:
  for left,right in PAIRS:
   group=collections.defaultdict(list)
   for pair in pairs:
    if pair['window']==w and pair['baseline'].endswith('-'+left) and pair['candidate'].endswith('-'+right):
     for v in pair['paired']:group[v['cluster']].append(v)
   if len(group)<2:continue
   rng=random.Random(20261021);keys=sorted(group);med=[];delta=[]
   for _ in range(2000):
    sample=[v for k in rng.choices(keys,k=len(keys)) for v in group[k]];med.append(statistics.median(v['ratio'] for v in sample));delta.append(statistics.median(v['delta_ns'] for v in sample)/1e6)
   med.sort();delta.sort();conditional_ci.append({'window':w,'baseline_variant':left,'candidate_variant':right,'od_clusters':len(keys),'resamples':2000,'paired_response_ratio_median_ci95':[med[49],med[1949]],'paired_delta_ms_median_ci95':[delta[49],delta[1949]],'scope':'Percentile OD-cluster resampling conditional on the recorded process blocks; all recorded within-cluster departures and blocks retained for this window. Not process-noise, population, causal or SLA confidence.'})
 metrics=[{k:v for k,v in x.items() if k not in ['records','clusters']} for b in blocks for x in b.values()]
 result={'schema':'public-tune-repeated-comparison-v1','campaigns':[str(c) for c in a.campaigns],'measured_processes':len(metrics),'offered':sum(v['offered'] for v in metrics),'complete':sum(v['complete'] for v in metrics),'process_unresolved':sum(v['unresolved'] for v in metrics),'semantic_mismatch_total':sum(len(v['semantic_mismatches']) for v in pairs),'repeat_semantic_mismatch_total':sum(len(v['semantic_mismatches']) for v in repeat),'conditional_od_cluster_ci':conditional_ci,'metrics':metrics,'source_pairs':[{k:v for k,v in x.items() if k!='paired'} for x in pairs],'repeat_pairs':[{k:v for k,v in x.items() if k!='paired'} for x in repeat],'limitations':['Empirical nearest-rank tune quantiles, not population tails or SLA. Same OD clusters across windows/blocks; no independence or convergence claim.','All offered counts retained; attempted and transit latency conditioning explicit; not-run/unresolved no latency.','Fresh processes with no discarded warmup pass; load,router/checker/quality preparation separate; OS pages read by prelaunch hashes; not disk cold.','Cloud CPU affinity, not exclusive cores; soft memory limit and sampled RSS safeguards, not hard confinement.','Native2D and3D output contracts differ; no cross-contract equal-quality speedup or global optimality claim.']}
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['metrics','source_pairs','repeat_pairs','conditional_od_cluster_ci']},indent=2))
if __name__=='__main__':main()
