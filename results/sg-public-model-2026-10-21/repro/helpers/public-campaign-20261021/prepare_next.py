import os
import copy,hashlib,json
from pathlib import Path
R=Path(os.environ['SG_ROOT']);O=R/'public-campaign-20261021';p=json.load(open(O/'broad-morning-plan.json'));runs=[]
for a in ['tp_destination_fixed_caps_experimental','tp_source_domain_retained_fixed_caps_experimental_v1']:
 src=O/'configs'/(a+'.json');v=json.load(open(src))
 fc=v['patterns']['patterns']['profile'] if 'patterns' in v else v['source_domain_patterns']['retained']['scope']['patterns']['profile']
 fc.pop('walking_policy',None);out=O/'configs'/(a+'-policy-fixed.json');out.write_text(json.dumps(v,indent=2)+'\n')
 run=copy.deepcopy(next(x for x in p['runs'] if x['id']==a));run['id']=a+'-policy-fixed';run['argv'][run['argv'].index('-scoped-config')+1]=str(out);runs.append(run)
p['runs']=runs;p['purpose']='Retry malformed TP profile policy only; original failed config attempts retained. Destination and source domain unchanged. Functional public modeled tune smoke.'
(O/'tp-config-retry-plan.json').write_text(json.dumps(p,indent=2)+'\n')
p=json.load(open(O/'broad-morning-plan.json'));p['runs']=[copy.deepcopy(x) for x in p['runs'] if x['id'].startswith('csa_')]
for run in p['runs']:
 run['argv'][0]=str(O/'familybench-csa-suffix');run['cwd']=str(R/'bench-csa-opt');run['id']+='-suffix-opt'
p['purpose']='Existing independently reviewed exact CSA destination-suffix feasibility candidate; same12 tune queries,k10,100k label limit and3s deadline as baseline. New availability/latency observation, not global optimum.'
(O/'csa-suffix-smoke-plan.json').write_text(json.dumps(p,indent=2)+'\n')
p=json.load(open(O/'first-baseline-plan.json'));proto=copy.deepcopy(p['runs'][0]);p['runs']=[]
algorithms=['raptor','raptor_early','mc_raptor','mc_raptor_early','ea_csa_layered','ultra_transfer_complete_capped','ultra_cap_safe_stay_witness_subset_v1']
for window in ['morning','midday','evening','overnight']:
 for a in algorithms:
  run=copy.deepcopy(proto);run['id']=f'{window}-{a}';run['argv'][run['argv'].index('-algorithm')+1]=a
  run['argv']=[x.replace('weekday-morning-',f'weekday-{window}-').replace('.smoke.tune.','.screen.tune.') for x in run['argv']]
  run['argv'][run['argv'].index('-prep-timeout')+1]='30s';run['timeout_s']=240
  run['inputs']=[x.replace('weekday-morning-',f'weekday-{window}-').replace('.smoke.tune.','.screen.tune.') for x in run['inputs']]
  if a.startswith('ultra_'):run['argv']+=['-scoped-config',str(O/'configs'/(a+'.json'))]
  p['runs'].append(run)
p['purpose']='Public-modeled screen tune only; frozen180 queries per window,4 windows,7 promising/baseline adapters; failed/empty/hard cases retained. Single measured pass and no warmup, not final steady-state tail.'
(O/'screen-tune-plan.json').write_text(json.dumps(p,indent=2)+'\n')
p=json.load(open(O/'screen-tune-plan.json'));p['runs']=[copy.deepcopy(x) for x in p['runs'] if x['id'] in ['morning-raptor','morning-raptor_early','morning-ea_csa_layered','morning-mc_raptor_early']]
for run in p['runs']:
 run['argv'][0]=str(R/'setup/familybench-profile');run['cwd']=str(R/'bench-profile');run['argv']+=['-cpu-profile','{run_dir}/cpu.pprof','-heap-profile','{run_dir}/heap.pprof'];run['id']+='-profile'
p['purpose']='Whole-run CPU/allocation diagnostic profiles on frozen morning180 tune queries. Instrumented timings not final latency measurements.'
(O/'profile-tune-plan.json').write_text(json.dumps(p,indent=2)+'\n')
