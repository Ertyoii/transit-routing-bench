import os
import copy,json
from pathlib import Path
R=Path(os.environ['SG_ROOT']);O=R/'public-campaign-20261021'; C=O/'configs';C.mkdir(exist_ok=True)
flash={'cells':8,'max_boardings':4,'semantics':'static_stop_pair_v1','walking_policy':'query_role_caps_v1','limits':{'max_stops':10000,'max_trips':100000,'max_closure_paths':1000000,'max_walk_settled':2000000,'max_transfers':5000000,'max_runs':200000,'max_work':2000000000,'max_flag_bytes':100000000,'max_suffix_bytes':1500000000,'max_witnesses':2000000,'max_query_segments':1000000,'max_snapshot_transfers':5000000}}
patterns={'patterns':{'profile':copy.deepcopy(flash),'max_patterns':2000000,'max_nodes':4000000,'max_edges':6000000,'max_direct_entries':5000000,'max_build_work':2000000000,'max_query_work':2000000,'max_query_labels':1000000},'destination':'33019','walking_limits':{'access_seconds':600,'egress_seconds':600,'transfer_seconds':600,'direct_seconds':600},'profile_max_legs':1024,'profile_max_walking_seconds':3000,'max_profile_records':1000000,'max_profile_sources':10000,'max_profile_queries':2000000,'max_profile_queued_segments':1000000}
patterns['patterns']['profile']['cells']=1
u={'max_runs':200000,'max_connection_visits':2000000000,'max_walk_settled':2000000,'max_walk_edges':2000000000,'max_shortcuts':5000000,'max_output_legs':2000000}
trex={'levels':3,'max_boardings':4,'exact_storage':True,'limits':{'max_stops':10000,'max_trips':100000,'max_input_edges':1000000,'max_closure_paths':1000000,'max_walk_settled':2000000,'max_transfers':5000000,'max_runs':200000,'max_work':2000000000,'max_witnesses':2000000,'max_overlay_entries':20000000,'max_queued_segments':1000000,'max_query_work':2000000}}
configs={
 'trip_based_capped':{'trip_based':{'transfer_walking_limit':600,'max_queued_segments':1000000,'max_precomputed_transfers':5000000}},
 'ultra_transfer_complete_capped':{'ultra':{'transfer_walking_limit':600,'accessible_only':False,'limits':u},'ultra_query':u},
 'ultra_cap_safe_stay_witness_subset_v1':{'ultra_sparse':{'capped':{'transfer_walking_limit':600,'accessible_only':False,'limits':u},'transfer_buffer':0,'max_proof_checks':2000000000},'ultra_query':u},
 'flash_tb_static_stop_pair_suffix_flags_role_caps_v1':{'flash':flash},
 'tp_destination_fixed_caps_experimental':{'patterns':patterns},
 'tp_source_domain_retained_fixed_caps_experimental_v1':{'source_domain_patterns':{'retained':{'scope':copy.deepcopy(patterns),'max_pending_segments':1000000,'max_source_seed_events':2000000},'sources':['96179']}},
 'trex_static_caps_mandatory_verified_experimental':{'trex':trex,'verification':{'max_states':1000000,'max_journeys':1000000,'max_scans':200000000}},
 'trex_fixed_transfer_cap_ranked_defined_probe_verified_experimental_v1':{'trex':trex,'verification':{'max_states':1000000,'max_journeys':1000000,'max_scans':200000000},'trex_fixed_transfer_cap':600,'verification_preparation':{'max_rows':1000000,'max_work':200000000,'max_payload_bytes':1500000000}},
}
for a,c in configs.items():(C/(a+'.json')).write_text(json.dumps(c,indent=2)+'\n')
p=json.load(open(O/'first-baseline-plan.json')); prototype=p['runs'][0];p['runs']=[]
algs=['raptor','mc_raptor','csa_arrival_single','csa_score_single','csa_arrival_shared','csa_score_shared',*configs,'trip_based','flash_tb','transfer_patterns','scalable_tp','trex']
for a in algs:
 v=copy.deepcopy(prototype);v['id']=a;v['argv'][v['argv'].index('-algorithm')+1]=a
 if a in configs:v['argv']+=['-scoped-config',str(C/(a+'.json'))]
 p['runs'].append(v)
p['purpose']='User-authorized public-modeled broad capability baseline: 19 remaining familybench adapters; all offered slots and preparation/query failures preserved. TP destination33019, retained source96179 domain is explicit; no outside-domain claim.'
(O/'broad-morning-plan.json').write_text(json.dumps(p,indent=2)+'\n')
