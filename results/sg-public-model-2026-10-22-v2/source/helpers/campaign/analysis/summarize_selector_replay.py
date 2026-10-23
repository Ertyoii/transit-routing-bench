#!/usr/bin/env python3
"""Compact, hash-bound diagnostics for the fixed-pool offline selector replay."""
import argparse,collections,hashlib,json
from pathlib import Path
def lines(p):
 with Path(p).open() as f:
  for s in f:yield json.loads(s)
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',required=True,type=Path);p.add_argument('--replay',required=True,type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();a.out.mkdir(exist_ok=False,parents=True);m=read(a.manifest/'MANIFEST.json');r=read(a.replay/'REPORT.json')
 assert r['manifest_sha256']==sha(a.manifest/'MANIFEST.json') and r['original_emitted_parity_all_passed']
 for name,h in m['outputs'].items():assert sha(a.manifest/name)==h
 agg=read(a.replay/'QUALITY_AGGREGATE.json');frontier=[]
 for panel in ['heldout393','wider_domain_stress257']:
  for reference in ['common','leave_donor_family_out_signed']:
   for k in [3,5]:
    for policy in sorted({z['policy_id'] for z in agg}):
     rs=[z for z in agg if z['variant_id']=='mc-early-storage' and z['panel']==panel and z['reference']==reference and z['limit']==k and z['policy_id']==policy];n=sum(z['eligible_weight_slots'] for z in rs);scored=sum(z['scored_weight_slots'] for z in rs)
     frontier.append(dict(panel=panel,reference=reference,limit=k,policy=policy,offered=sum(z['offered_rows'] for z in rs),available=sum(z['available_rows'] for z in rs),eligible_weight_slots=n,scored_weight_slots=scored,missing_weight_slots=sum(z['missing_weight_slots'] for z in rs),coverage=sum(z['covered'] for z in rs)/n if n else None,within30=sum(z['within30'] for z in rs)/n if n else None,within60=sum(z['within60'] for z in rs)/n if n else None,within1percent=sum(z['within1percent'] for z in rs)/n if n else None,mean_observed_signed_regret=sum(z['signed_regret_sum'] for z in rs)/scored if scored else None,mean_observed_normalized_regret=sum(z['normalized_signed_regret_sum'] for z in rs)/scored if scored else None,max_observed_signed_regret=max([z['max_observed_signed_regret'] for z in rs if z['max_observed_signed_regret'] is not None],default=None),max_observed_normalized_regret=max([z['max_observed_normalized_regret'] for z in rs if z['max_observed_normalized_regret'] is not None],default=None),negative_signed_slots=sum(z['negative_signed_slots'] for z in rs)))
 rows=list(lines(a.manifest/'CANDIDATE_ROWS.jsonl'));variantmap=collections.defaultdict(lambda:collections.defaultdict(collections.Counter))
 for z in rows:variantmap[z['variant_id']][(z['window'],z['query']['id'])][(z['candidate_pool_id'],z['independent_complete'],z['independent_status'])]+=1
 baseline=variantmap['mc-early-storage'];paired={}
 for variant in ['mc-early-control','mc-early-slab','mc-early-absolute-greedy','mc-early-absolute-hybrid','mc-early-normalized-greedy','mc-early-normalized-hybrid','mc-early-pattern-lean','mc-early-historical-finite20-full']:
  v=variantmap[variant];keys=set(baseline)|set(v);bad=[{'window':k[0],'query_id':k[1]} for k in sorted(keys) if baseline.get(k)!=v.get(k)];paired[variant]={'compared_semantic_queries':len(keys),'paired_offer_multiplicity_matches':not bad,'different_query_count':len(bad),'different_queries':bad}
 pools=list(lines(a.manifest/'CANDIDATE_POOLS.jsonl'));reductions=list(lines(a.replay/'REDUCTION_POOLS.jsonl'));reduction_stats={}
 for mode in sorted({z['reduction']['mode'] for z in reductions}):
  rs=[z['reduction'] for z in reductions if z['reduction']['mode']==mode];reduction_stats[mode]={'pools':len(rs),'complete':sum(z['complete'] for z in rs),'pools_losing_patterns':sum(z['lost_patterns']>0 for z in rs),'sum_lost_patterns':sum(z['lost_patterns'] for z in rs),'pools_with_equal_vector_different_patterns_before':sum(z['multi_pattern_equal_vector_groups_before']>0 for z in rs),'pools_with_equal_vector_different_patterns_after':sum(z['multi_pattern_equal_vector_groups_after']>0 for z in rs)}
 policies=collections.defaultdict(lambda:{'pool_limit_outputs':0,'complete_outputs':0,'incomplete_outputs':0,'methods':collections.Counter(),'subset_optimal_outputs':0,'selected_pattern_counts':collections.Counter(),'outputs_with_duplicate_selected_pattern':0,'nested_violation_pool_ids':set(),'errors':collections.Counter(),'original_scalar_statuses':collections.Counter()})
 for z in lines(a.replay/'POLICY_POOL_SCORES.jsonl'):
  s=policies[z['policy_id']];s['pool_limit_outputs']+=1;s['complete_outputs']+=z['complete'];s['incomplete_outputs']+=not z['complete'];d=z.get('details') or {};s['methods'][d.get('method','pattern_anchor_control')]+=1;s['subset_optimal_outputs']+=bool(d.get('subset_optimal'));s['selected_pattern_counts'][z['selected_patterns']]+=1;s['outputs_with_duplicate_selected_pattern']+=z['selected_patterns']<len(z['selected']);s['errors'][z.get('error','')]+=1
  if z['complete'] and z['nested_constraint_holds'] is False:s['nested_violation_pool_ids'].add(z['candidate_pool_id'])
  for slot in z['original_scalar_slots']:s['original_scalar_statuses'][slot['status']]+=1
  if 'distinct_patterns' in z['policy_id'] and z['complete']:assert z['selected_patterns']==len(z['selected'])
 for s in policies.values():s['nested_violation_pool_ids']=sorted(s['nested_violation_pool_ids'])
 summary={'schema':'sg-selector-offline-summary-v1','manifest_sha256':sha(a.manifest/'MANIFEST.json'),'replay_report_sha256':sha(a.replay/'REPORT.json'),'helper_sha256':sha(__file__),'offered_rows':len(rows),'native_pools':len(pools),'native_nonempty_pools':sum(bool(z['features']) for z in pools),'native_max_candidates':max(len(z['features']) for z in pools),'native_pattern_histogram':dict(collections.Counter(len({f['route_stop_walk_pattern'] for f in z['features']}) for z in pools)),'source_pool_pairing_against_mc_early_storage':paired,'reduction_by_mode':reduction_stats,'policy_diagnostics':dict(policies),'storage_common_and_signed_lofo_frontier':frontier,'oracle_slots_retained':m['oracle_slots_retained'],'oracle_complete_slots_retained':m['oracle_complete_slots_retained'],'limitations':['All quality is tune-only on frozen synthetic preference hypotheses, not authentic rider utility.','Repeated blocks weight the same240 queries twice and are not480 independent quality queries.','Common/LOFO feasible-witness unions are incomplete; only original complete scalar9 slots establish model optima.','Counterfactual joint[3,5] choices are not serving latency observations.','Max/mean regret conditions on scored reference slots; missing remains explicit.','No source, router, workload, validation or test bytes were altered.']}
 (a.out/'SUMMARY.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n');(a.out/'ARTIFACT_SHA256.json').write_text(json.dumps({str(p):sha(p) for directory in [a.manifest,a.replay,a.out] for p in sorted(directory.iterdir()) if p.is_file()},sort_keys=True,indent=2)+'\n');print(json.dumps({k:summary[k] for k in ['offered_rows','native_pools','native_nonempty_pools','native_max_candidates','source_pool_pairing_against_mc_early_storage','reduction_by_mode']}))
if __name__=='__main__':main()
