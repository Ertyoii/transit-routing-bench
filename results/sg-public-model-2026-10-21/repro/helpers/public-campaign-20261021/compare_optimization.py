#!/usr/bin/env python3
import argparse,json,math,statistics
from pathlib import Path
FIELDS=['query','raw','final','display_options','completed','attempted','valid_empty','transit','status','error','certificates','recommendation_quality']
def load(rd):
 s=json.load(open(rd/'artifact/summary.json'));ps=[p for p in s['passes'] if not p.get('warmup') and not p.get('forced')];assert len(ps)==1
 p=json.load(open(rd/'artifact'/ps[0]['file']));return s,p

def compare(a,b):
 sa,pa=load(a);sb,pb=load(b);assert sa['dataset_sha256']==sb['dataset_sha256'];ra={r['query']['id']:r for r in pa['records']};rb={r['query']['id']:r for r in pb['records']};assert ra.keys()==rb.keys()
 diff=[];deltas=[];ratios=[]
 for k,x in ra.items():
  y=rb[k];fs=[f for f in FIELDS if x.get(f)!=y.get(f)]
  if fs:diff.append({'query_id':k,'fields':fs})
  if x['completed'] and y['completed']:
   deltas.append((y['response_ns']-x['response_ns'])/1e6)
   if x['response_ns']>0:ratios.append(y['response_ns']/x['response_ns'])
 def metric(s,p):
  ps=[x for x in s['passes'] if not x.get('forced') and not x.get('warmup')][0];pr=json.load(open((a if s is sa else b)/'result.json'))
  return {'offered':ps['requested'],'complete':ps['complete'],'statuses':ps['statuses'],'response_p50_ms':None if not ps['complete'] else ps['completed_response_ns']['p50']/1e6,'response_max_ms':None if not ps['complete'] else ps['completed_response_ns']['max']/1e6,'batch_allocation_bytes':sum(x.get('allocated_bytes',0) for x in p['batches']),'load_s':s['input_load_ns']/1e9,'router_prep_s':s['preparation']['elapsed_ns']/1e9,'router_prep_alloc_bytes':s['preparation']['allocated_bytes'],'sampled_peak_group_rss_bytes':pr['sampled_peak_process_group_rss_bytes']}
 return {'baseline':str(a),'candidate':str(b),'offered_pairs':len(ra),'semantic_mismatch_count':len(diff),'semantic_mismatches':diff,'comparison_fields':FIELDS,'joint_complete':len(deltas),'median_paired_response_delta_ms':statistics.median(deltas) if deltas else None,'median_paired_response_ratio':statistics.median(ratios) if ratios else None,'baseline_metrics':metric(sa,pa),'candidate_metrics':metric(sb,pb),'scope':'One measured process/pass, tune only. Exact emitted witness/status/certificate preservation checked; no global optimum, convergence, independent full-network oracle, or production tail claim.'}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path);p.add_argument('--out',type=Path,required=True);x=p.parse_args();r=compare(x.baseline,x.candidate);x.out.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
