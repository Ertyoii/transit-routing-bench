#!/usr/bin/env python3
import argparse,csv,json,statistics
from pathlib import Path

def q(v,p):
 if not v:return None
 v=sorted(v);import math;return v[max(0,math.ceil(len(v)*p)-1)]/1e6

def summarize(campaign):
 rows=[]
 for spec in json.load(open(campaign/'plan.json'))['runs']:
  rd=campaign/spec['id']; sf=rd/'artifact/summary.json';pf=rd/'result.json'
  query_path=Path(spec['argv'][spec['argv'].index('-queries')+1]);declared_queries=len(json.load(open(query_path))['items'])
  base={'declared_offered_queries':declared_queries,'campaign':campaign.name,'run_id':spec['id'],'offered_queries_per_pass':None,'measured_rows':0,'process_ok':None,'process_wall_s':None,'sampled_peak_group_rss_bytes':None,'prep_status':None,'prep_s':None,'load_s':None,'checker_prep_s':None,'attempted':0,'not_run':0,'complete':0,'transit':0,'valid_empty':0,'statuses':{},'successful_response_median_ms':None,'successful_response_max_ms':None,'transit_response_median_ms':None,'transit_response_max_ms':None,'attempted_response_max_ms':None,'forced_rows_excluded':0,'warmup_rows_excluded':0,'summary':str(sf)}
  if pf.exists():
   p=json.load(open(pf));base.update(process_ok=p['ok'],process_wall_s=p.get('process_wall_s'),sampled_peak_group_rss_bytes=p.get('sampled_peak_process_group_rss_bytes'),wait4_ru_maxrss_kib=p.get('wait4_ru_maxrss_kib'),wait4_ru_maxrss_note=p.get('wait4_ru_maxrss_note'),process_user_cpu_s=p.get('user_cpu_s'),process_system_cpu_s=p.get('system_cpu_s'))
  resource_stop=rd/'artifact/resource-stop.json'
  if resource_stop.exists():base.update(process_outcome='observed_rss_safety_stop',unresolved_offered_queries=declared_queries,resource_stop=json.load(open(resource_stop)))
  elif pf.exists() and not sf.exists():base.update(process_outcome='process_failure_no_summary',unresolved_offered_queries=declared_queries)
  if sf.exists():
   s=json.load(open(sf));prep=s.get('preparation',{});base.update(algorithm=s['algorithm'],prep_status=prep.get('status'),prep_error=prep.get('error'),prep_s=prep.get('elapsed_ns',0)/1e9,load_s=s.get('input_load_ns',0)/1e9,checker_prep_s=s.get('checker_preparation',{}).get('elapsed_ns',0)/1e9)
   for label,key in [('router','preparation'),('checker','checker_preparation'),('quality','quality_preparation')]:
    v=s.get(key,{}) or {};base[label+'_preparation_s']=v.get('elapsed_ns',0)/1e9;base[label+'_preparation_allocated_bytes']=v.get('allocated_bytes');base[label+'_preparation_resources_cumulative']=v.get('resources')
   base['resources_final_cumulative']=s.get('resources_final');base['resource_accounting']='Preparation allocation deltas and time phases separate; cumulative heap/RSS snapshots overlap and must not be summed. wait4ru_maxrss leader wholeprocess distinct from sampled summedprocessgroupRSS.'
   base['explicit_startup_phase_sum_s']=sum(s.get(key,{}).get('elapsed_ns',0) for key in ['preparation','checker_preparation','quality_preparation'])/1e9+s.get('input_load_ns',0)/1e9
   base['startup_sum_scope']='Sum of separately timed parsing/router/checker/quality-index phases only; excludes process launch, prelaunch hashing, uninstrumented gaps and transport/artifact I/O. Not complete process-cold first-byte latency.'
   succ=[];trans=[];att=[];allocated=0;quality_times=[]
   for ps in s.get('passes',[]):
    if ps.get('forced'):base['forced_rows_excluded']+=ps['requested'];continue
    if ps.get('warmup'):base['warmup_rows_excluded']+=ps['requested'];continue
    pp=json.load(open(sf.parent/ps['file'])); rs=pp['records'];allocated+=sum(b.get('allocated_bytes',0) for b in pp.get('batches',[]));base['offered_queries_per_pass']=ps['requested'];base['measured_rows']+=len(rs);base['attempted']+=ps.get('attempted',0);base['not_run']+=ps.get('not_run',0)
    if rs and 'first_measured_status' not in base:
     first=rs[0];base['first_measured_status']=first['status'];base['first_measured_response_ms']=first.get('response_ns',0)/1e6 if first.get('attempted') else None;base['first_setup_plus_response_components_s']=base['explicit_startup_phase_sum_s']+first['response_ns']/1e9 if first.get('attempted') else None
    for r in rs:
     if r.get('attempted') and 'quality_ns' in r:quality_times.append(r['quality_ns'])
     st=r['status'];base['statuses'][st]=base['statuses'].get(st,0)+1
     if r.get('attempted'):att.append(r['response_ns'])
     if r.get('completed') and st=='complete':
      base['complete']+=1;succ.append(r['response_ns']);base['transit']+=bool(r['transit']);base['valid_empty']+=bool(r['valid_empty'])
      if r['transit']:trans.append(r['response_ns'])
   base.update(successful_response_median_ms=q(succ,.5),successful_response_max_ms=q(succ,1),transit_response_median_ms=q(trans,.5),transit_response_max_ms=q(trans,1),attempted_response_max_ms=q(att,1),successful_response_p95_ms=q(succ,.95),successful_response_p99_ms=q(succ,.99),transit_response_p95_ms=q(trans,.95),transit_response_p99_ms=q(trans,.99),attempted_response_p50_ms=q(att,.5),attempted_response_p95_ms=q(att,.95),attempted_response_p99_ms=q(att,.99),measured_batch_allocated_bytes=allocated,attempted_quality_phase_p50_ms=q(quality_times,.5),attempted_quality_phase_p95_ms=q(quality_times,.95),attempted_quality_phase_p99_ms=q(quality_times,.99))
  rows.append(base)
 return rows
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('campaigns',nargs='+',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();out={'tier':'public_modeled_pipeline_validation','claim':'Functional smoke/tune observations, not held-out performance, production latency, official timetable authenticity or global optimization. Response excludes load/prep/checker/serialization. Success-conditioned observations must be read with all offered failures.','rows':[r for c in a.campaigns for r in summarize(c)]};a.out.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
