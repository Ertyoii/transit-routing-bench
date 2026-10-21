#!/usr/bin/env python3
import argparse,json,collections
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('dirs',nargs='+',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args();rows=[];agg={}
for d in a.dirs:
 s=json.load(open(d/'scorecard.json'));window=d.name.rsplit('-',1)[-1]
 for x in s['algorithms']:
  alg=x['algorithm'];v={'window':window,'algorithm':alg,'offered':x['requested'],'complete_valid':x['completed_valid'],'statuses':x['statuses'],'cohorts':x['outcome_cohorts'],'pool_sha256':s['binding']['pool_sha256'],'stages':{}}
  ag=agg.setdefault(alg,{'algorithm':alg,'offered':0,'complete_valid':0,'stages':{}});ag['offered']+=x['requested'];ag['complete_valid']+=x['completed_valid']
  for st,stage in x['stages'].items():
   v['stages'][st]={k:stage[k] for k in ['eligible_query_profile_slots','covered_query_profile_slots','missing_query_profile_slots','pool_profile_coverage_including_failures','pool_relative_regret_seconds_observed_only']};v['stages'][st]['walking_averse_t300_w4']=next(z for z in stage['profiles'] if z['profile_id']=='t300_w4')
   z=ag['stages'].setdefault(st,{'eligible':0,'covered':0,'missing':0,'maximum_pool_relative_regret_score_seconds':0});z['eligible']+=stage['eligible_query_profile_slots'];z['covered']+=stage['covered_query_profile_slots'];z['missing']+=stage['missing_query_profile_slots'];z['maximum_pool_relative_regret_score_seconds']=max(z['maximum_pool_relative_regret_score_seconds'],stage['pool_relative_regret_seconds_observed_only'].get('max') or 0)
  rows.append(v)
for x in agg.values():
 for z in x['stages'].values():z['grid_coverage']=z['covered']/z['eligible'] if z['eligible'] else None
out={'schema':'public-modeled-quality-fourwindow-summary-v1','source_dirs':[str(d) for d in a.dirs],'all_window_rows':rows,'aggregate_descriptive_only':list(agg.values()),'scope':'Same20 explicit hypothetical preference grid and incomplete observed witness pool per window; not externally validated passenger preferences, population probabilities, global optimum or travel-time regrets. Eligibility is profile-query slots with a nonempty common pool; model-empty queries retain outcome denominators but have no finite optimum. Cross-window pooled descriptive weights are not observed demand. Score-second regret may include transfer/walking penalties.'};a.out.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out['aggregate_descriptive_only'],indent=2))
