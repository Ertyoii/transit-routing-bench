#!/usr/bin/env python3
"""Quiet-window input-only qualification/freeze, then create registry-split plans.
NEVER launches a router or campaign: actual driver invocations require
-input-only and emit source-bound acceptance before constructors. Preparation
creates no runnable plan until EVERY exact consuming-driver/config check passed.
"""
import argparse,fcntl,hashlib,json,os,signal,subprocess,time
from pathlib import Path
from compose_native_auxiliary_v2 import ROOT,SETUP,runtime_hash,sha,write_new,TREX_SOURCE_SHA
import run_campaign

def load(p):return json.loads(Path(p).read_text())
TREX_FAMILIES=('trex_fixed_transfer_cap_ranked_defined_probe_verified_experimental_v1','trex_static_caps_mandatory_verified_experimental')
def compact_trex_slots(base_slots,start_order):
 """Exactly eight nonmutating, equal-config/cap source contrasts, not families."""
 controls=[x for x in base_slots if x['family'] in TREX_FAMILIES]
 if len(controls)!=8 or any(sum(x['family']==fam for x in controls)!=4 for fam in TREX_FAMILIES):raise ValueError('Compact TREX needs exactly both native families in all four windows')
 if len({(x['family'],x['window']) for x in controls})!=8 or any(len({x['window'] for x in controls if x['family']==fam})!=4 for fam in TREX_FAMILIES):raise ValueError('Duplicate/missing compact TREX family-window contrasts')
 rows=[]
 for ix,slot in enumerate(controls):
  name=Path(slot['scoped_config']).name
  fixed=slot['family']==TREX_FAMILIES[0]
  if (fixed and ('bounded600' not in name or 'fullmetric' in name)) or (not fixed and 'fullmetric' not in name):raise ValueError('Compact TREX walking metric label mismatch')
  rows.append(dict(slot,order=start_order+ix,source_role='qualified_compact_trex',contrast='compact_trex_equal_caps',walking_metric='bounded_transfer600' if fixed else 'full_metric',equal_caps_control={'family':slot['family'],'window':slot['window'],'source_role':slot['source_role'],'scoped_config':slot['scoped_config']}))
 return rows
def split_registry_runs(prepared,registry,extra_inputs):
 """Project one registry without mutating shared prepared rows or inputs."""
 return [dict((k,(list(v)+list(extra_inputs) if k=='inputs' else v))
              for k,v in row.items() if k!='registry')
         for row in prepared if row['registry']==str(registry)]
def identity(p):
 p=Path(p).resolve(strict=True);return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def capture(argv,cwd,env,base,timeout=180):
 out=base.with_suffix('.stdout');err=base.with_suffix('.stderr');start=time.monotonic();peak=0;reason=None
 with out.open('x') as o,err.open('x') as e:
  child=subprocess.Popen([str(x) for x in argv],cwd=cwd,env=env,stdout=o,stderr=e,preexec_fn=run_campaign.child_setup)
  while child.poll() is None:
   rss,_=run_campaign.group_rss(child.pid);peak=max(peak,rss)
   if rss>=7000000000:reason='rss_stop7GB'
   if time.monotonic()-start>timeout:reason='input_only_timeout'
   if reason:
    os.killpg(child.pid,signal.SIGKILL);break
   time.sleep(.2)
  code=child.wait()
  if run_campaign.group_exists(child.pid):
   os.killpg(child.pid,signal.SIGKILL)
   raise RuntimeError('input-only descendant group leaked; stopped before next slot')
 if code or reason:raise RuntimeError(f'Input-only check failed:{base.name},exit{code},reason{reason}; preserve logs')
 return out.read_text(),{'stdout':identity(out),'stderr':identity(err),'peak_sampled_group_rss_bytes':peak,'elapsed_s':time.monotonic()-start}
def get_flag(argv,key,default=''):
 values=[argv[i+1] for i,x in enumerate(argv[:-1]) if x==key]
 if len(values)>1:raise ValueError('duplicate flag '+key)
 return values[0] if values else default
def family_argv(binary,slot,prefs):
 a=[binary,'-algorithm',slot['family'],'-dataset',slot['dataset']['path'],'-queries',slot['queries'],'-batch-size','1','-batch-timeout','3s','-prep-timeout',str(slot['prep_timeout_s'])+'s','-warmups','0','-repetitions','1','-rss-safety-stop','7000000000','-stream-responses','-quality','-preference-scenarios',str(prefs),'-display-k','-1','-max-transfers',str(slot.get('max_transfers',100000000)),'-max-work','2000000000','-max-witnesses','2000000']
 if slot.get('scoped_config'):a+=['-scoped-config',slot['scoped_config']]
 return a

def argv_for(binary,slot,prefs):
 driver=slot['driver']
 if driver=='familybench':return family_argv(binary,slot,prefs)
 a=[binary,'-dataset',slot['dataset']['path'],'-queries',slot['queries'],'-warmups','0','-repetitions','1','-timeout','3s']
 if driver=='profilebench':a+=['-algorithms','range_raptor','-point-workload','-ready-span-seconds','60','-max-window-seconds','600','-max-visits','10000000','-max-labels','2000000','-max-departures','10000']
 elif driver=='tadbench':a+=['-algorithms','tad','-max-labels','2000000','-max-visits','10000000','-max-walk-visits','10000000']
 elif driver=='ultrabench':a+=['-active-routes','-reuse-departures','-route-mode','non_overtaking_groups','-max-runs','10000','-prep-timeout',str(slot['prep_timeout_s'])+'s']
 elif driver=='corechgraphbench':a+=['-maximum-duration','600','-witness-settled','128','-max-witness-settled','30000000','-max-witness-edges','150000000','-maximum-average-core-out-degree','14','-prep-timeout',str(slot['prep_timeout_s'])+'s']
 else:raise ValueError(driver)
 return a

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--quiet-window-open',action='store_true');p.add_argument('--composition',required=True,type=Path);p.add_argument('--out-dir',required=True,type=Path);p.add_argument('--include-fullmetric-fixed-controls',action='store_true');p.add_argument('--preferences',type=Path,default=ROOT/'selector-quality/configs/finite20-lean-delivery-top3.json');a=p.parse_args()
 if not a.quiet_window_open:raise SystemExit('Refusing without explicit quiet-window acknowledgement; no parsing/hashing/preflight executed')
 lock=(SETUP/'campaign.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 composition=load(a.composition)
 if composition['status']!='QUALIFIED_BUILT_SOURCE_FROZEN_INPUT_PREFLIGHT_PENDING':raise ValueError('composition not qualified/built')
 compact=composition['roles'].get('trex-compact',{})
 if not compact.get('equal_caps_only') or compact.get('upstream_compact_source',{}).get('source_file_list_sha256')!=TREX_SOURCE_SHA:raise ValueError('V2 plans require the qualified distinct compact TREX role before any input preflight')
 proposal=load(ROOT/'experiments/SERIAL_NATIVE_AUXILIARY_PROPOSAL.json')
 if proposal['native_domains_split']!='tune_only' or proposal['initial_processes']!=56:raise ValueError('unexpected native plan contract')
 a.out_dir=a.out_dir.resolve();a.out_dir.mkdir(parents=True,exist_ok=False);evidence=a.out_dir/'input-only';evidence.mkdir();roles=composition['roles'];env=dict(os.environ,GOMAXPROCS='2')
 for r in roles.values():
  if runtime_hash(Path(r['source_root']))!=r['go_source_hash_sha256']:raise ValueError('source changed since composition')
  for b in r['binaries'].values():
   if sha(Path(b['path']))!=b['sha256']:raise ValueError('binary changed since composition')
 slots=[dict(x) for x in proposal['initial_slots']]
 # Additional frozen native range controls are a SOURCE contrast, not a family.
 for slot in reversed(list(slots)):
  if slot['family']=='range_raptor':
   control=dict(slot,order=len(slots),source_role='dense_range_control',contrast='frozen_native_range_control');slots.append(control)
 if a.include_fullmetric_fixed_controls:
  for slot in list(proposal['initial_slots']):
   fam=slot['family'];w=slot['window']
   if not(fam.startswith('tp_') or fam.startswith('trex_fixed_transfer_cap')):continue
   if fam.startswith('tp_'):c=ROOT/'configs/native-preparation-v3-fullmetric'/f'{w}-{fam}-policy-fixed-fullmetric-closure9m-transfers100000000.json'
   else:c=ROOT/'configs/native-preparation-v2'/f'{fam}-fullmetric-closure9m-transfers50m-overlay200m.json'
   slots.append(dict(slot,order=len(slots),scoped_config=str(c),source_role='old_fullmetric_fixed_control',contrast='explicit_old_fullmetric_fixed_builder'))
 slots.extend(compact_trex_slots(proposal['initial_slots'],len(slots)))
 prepared=[];coverage=[];bound_inputs={};primary_registry=ROOT/'data-workload/workloads/phase_hash_a_conservative600/registry.json';native_registry=ROOT/'native-domains/registry.json'
 registry_payloads={str(x):load(x) for x in (primary_registry,native_registry)}
 for ix,slot in enumerate(slots):
  fam=slot['family'];driver=slot['driver'];source_role=slot['source_role'];role='trex-compact' if source_role=='qualified_compact_trex' else ('range' if source_role=='dense_range_candidate' else ('range-control' if source_role=='dense_range_control' else ('fullmetric-fixed' if source_role=='old_fullmetric_fixed_control' else 'prep')))
  if role=='trex-compact' and (fam not in TREX_FAMILIES or driver!='familybench'):raise ValueError('Compact role may execute only the two declared TREX native families')
  record=roles[role];binary=record['binaries'][driver]['path'];cwd=record['source_root'];base_argv=argv_for(binary,slot,a.preferences)
  if role=='trex-compact':
   controls=[x for x in proposal['initial_slots'] if x['family']==fam and x['window']==slot['window']]
   if len(controls)!=1 or base_argv[1:]!=argv_for(roles['prep']['binaries'][driver]['path'],controls[0],a.preferences)[1:]:raise ValueError('Compact TREX contrast changed caps/config/input/requested driver work')
  if 'csa' in fam.lower():raise ValueError('CSA excluded')
  if driver=='profilebench' and get_flag(base_argv,'-algorithms')!='range_raptor':raise ValueError('unsafe profile selection')
  if driver=='tadbench' and get_flag(base_argv,'-algorithms')!='tad':raise ValueError('unsafe TAD selection')
  fixed=fam.startswith('tp_') or fam.startswith('trex_fixed_transfer_cap');config=slot.get('scoped_config');name=Path(config).name if config else ''
  if fixed and (('fullmetric' in name)!=(role=='fullmetric-fixed')):raise ValueError('fixed-builder metric label/source mismatch')
  if fixed and role!='fullmetric-fixed' and 'bounded600' not in name:raise ValueError('missing explicit bounded600 name')
  registry=native_registry if fam.startswith('tp_') else primary_registry
  allowed={str(Path(e['workload']['path']).resolve()):e for e in registry_payloads[str(registry)]['entries']}
  if str(Path(slot['queries']).resolve()) not in allowed:raise ValueError('query not in correct registry')
  if allowed[str(Path(slot['queries']).resolve())]['split']!='tune':raise ValueError('auxiliary native proposal is TUNE ONLY')
  schema='profile-from-point' if driver=='profilebench' else 'point';rid=f'naux-{ix:03d}-{fam[:24]}-{slot["window"].split("-")[1]}'
  for path in [slot['dataset']['path'],slot['queries'],*( [config] if config else []),*( [str(a.preferences)] if driver=='familybench' else [])]:
   if path not in bound_inputs:bound_inputs[path]=identity(path)
  for key,path in [('dataset',slot['dataset']['path']),('queries',slot['queries'])]:
   expected=slot['dataset']['sha256'] if key=='dataset' else allowed[str(Path(path).resolve())]['workload']['sha256']
   if bound_inputs[path]['sha256']!=expected:raise ValueError('input changed from declared registry/domain')
  generic=[record['binaries']['inputpreflight']['path'],'-dataset',slot['dataset']['path'],'-queries',slot['queries'],'-schema',schema,'-algorithm',fam,'-ready-span-seconds','60','-max-window-seconds','600']
  if config:generic+=['-scoped-config',config]
  if driver=='familybench':generic+=['-preference-scenarios',str(a.preferences)]
  # Existing inputpreflight flag is -preferences, not familybench's argv name.
  generic=['-preferences' if x=='-preference-scenarios' else x for x in generic]
  gout,glog=capture(generic,cwd,env,evidence/f'{ix:03d}-schema');grows=[json.loads(x) for x in gout.splitlines() if x.startswith('{')]
  if len(grows)!=1 or not grows[0].get('accepted'):raise ValueError('generic strict config/schema preflight failed')
  actual=base_argv+['-out-dir',str(evidence/f'{ix:03d}-actual-output'),'-input-only'];output,log=capture(actual,cwd,env,evidence/f'{ix:03d}-actual')
  markers=[json.loads(x) for x in output.splitlines() if x.startswith('{')];accepted=[x for x in markers if x.get('event')=='input_only_acceptance']
  if len(accepted)!=1 or any(x.get('event')=='first_available_answer' for x in markers):raise ValueError('input-only marker or ordinary output violation')
  accepted=accepted[0]
  if accepted['driver']!=driver or accepted['provenance']['runtime_tree_sha256']!=record['go_source_hash_sha256'] or not accepted['provenance']['runtime_matches_build']:raise ValueError('actual consuming driver/source mismatch')
  if accepted['queries_sha256']!=bound_inputs[slot['queries']]['sha256'] or accepted['dataset_sha256']!=bound_inputs[slot['dataset']['path']]['sha256']:raise ValueError('actual parser byte binding mismatch')
  if config and accepted['scoped_configuration_sha256']!=bound_inputs[config]['sha256']:raise ValueError('actual scoped config byte binding mismatch')
  if accepted['seed_metadata']!=grows[0]['seed_metadata']:raise ValueError('actual driver seed differs from qualified generic mapping')
  coverage.append({'run_id':rid,'source_role':role,'source_hash':record['go_source_hash_sha256'],'binary':record['binaries'][driver],'driver':driver,'actual_schema':accepted['schema'],'generic_schema':schema,'algorithm':fam,'scoped_config':bound_inputs.get(config),'dataset':bound_inputs[slot['dataset']['path']],'queries':bound_inputs[slot['queries']],'accepted':True,'actual_acceptance':accepted,'actual_invocation':actual,'generic_log':glog,'actual_log':log,'contrast':slot.get('contrast'),'equal_caps_control':slot.get('equal_caps_control'),'walking_metric':slot.get('walking_metric')})
  prepared.append({'id':rid,'variant_id':f'{fam}-{role}','window':slot['window'],'argv':base_argv+['-out-dir','{run_dir}/artifact'],'cwd':cwd,'source_roots':[cwd],'timeout_s':slot['outer_timeout_s'],'rss_safety_stop_bytes':7000000000,'env':{},'registry':str(registry),'family':fam,'contrast':slot.get('contrast'),'equal_caps_control':slot.get('equal_caps_control'),'walking_metric':slot.get('walking_metric'),'inputs':[str(Path(slot['queries']).with_suffix('.metadata.json')),str(ROOT/'protocol/PROTOCOL_DRAFT.md')]})
 # Qualify native-profile schema on the ACTUAL consuming profilebench separately.
 # These derived input-only fixtures are not registered ordinary benchmark runs.
 for ix,slot in enumerate(x for x in slots[:56] if x['family']=='range_raptor'):
  old=load(slot['queries']);derived=dict(old);derived['method']='input-only-schema-profile-derived:'+old['method'];derived['items']=[{'stratum':x['stratum'],'query':{'base':x['query'],'ready_window_end_inclusive':x['query']['departure']+60}} for x in old['items']]
  path=evidence/f'native-profile-{ix}.json';write_new(path,derived);r=roles['range'];b=r['binaries']['profilebench'];argv=[b['path'],'-algorithms','range_raptor','-dataset',slot['dataset']['path'],'-queries',str(path),'-max-window-seconds','600','-warmups','0','-repetitions','1','-timeout','3s','-out-dir',str(evidence/f'native-profile-{ix}-output'),'-input-only'];out,log=capture(argv,r['source_root'],env,evidence/f'native-profile-{ix}-actual');values=[json.loads(x) for x in out.splitlines() if x.startswith('{')];ok=[x for x in values if x.get('event')=='input_only_acceptance']
  if len(ok)!=1 or ok[0]['schema']!='profile' or ok[0]['provenance']['runtime_tree_sha256']!=r['go_source_hash_sha256']:raise ValueError('native-profile consuming parser not qualified')
  coverage.append({'run_id':f'input-only-native-profile-{ix}','benchmark_run':False,'driver':'profilebench','actual_schema':'profile','source_hash':r['go_source_hash_sha256'],'binary':b,'queries':identity(path),'parent_unchanged_point_workload':bound_inputs[slot['queries']],'actual_acceptance':ok[0],'actual_invocation':argv,'actual_log':log,'accepted':True})
 # Recheck every original byte binding and source after preflight. No mutation
 # between this freeze and the later serial runner is allowed.
 for path,ref in bound_inputs.items():
  if sha(Path(path))!=ref['sha256']:raise ValueError('original input mutated during input-only preflight')
 for r in roles.values():
  if runtime_hash(Path(r['source_root']))!=r['go_source_hash_sha256']:raise ValueError('source changed during preflight')
 index=a.out_dir/'DRIVER_SCHEMA_SOURCE_COVERAGE.json';write_new(index,{'schema':'actual-consuming-native-driver-coverage-v1','scope':'Input-only parser/config compatibility; NO constructors, searches or routing outcomes. Generic preflight alone does not qualify another driver.','ordinary_run_slots':len(prepared),'base_proposal_slots':56,'compact_trex_equal_caps_contrasts':8,'native_profile_extra_input_only_rows':4,'rows':coverage,'accepted':True})
 freeze=a.out_dir/'INPUT_SOURCE_BINARY_FREEZE.json';write_new(freeze,{'status':'FROZEN_AFTER_ALL_ACTUAL_DRIVER_INPUT_ONLY_CHECKS','composition':identity(a.composition),'coverage_index':identity(index),'input_files':list(bound_inputs.values()),'source_roles':roles,'native_domain_split':'tune_only','compact_trex_equal_caps_contrasts':8,'all_csa_execution_excluded':True,'scope':'Public-modeled diagnostic native contracts only; not final evaluation or arbitraryOD evidence from scoped domains.'})
 for registry in (primary_registry,native_registry):
  selected=split_registry_runs(prepared,registry,[str(freeze),str(index),str(a.composition)])
  filename='native-domain-tune-plan.json' if registry==native_registry else 'primary-tune-native-plan.json'
  plan={'schema':'sg-coldstart-campaign-v2','evaluation_mode':'diagnostic','dataset_tier':'public_modeled_pipeline_validation','purpose':'Frozen source-bound native non-CSA auxiliary tune attempts. Exact family/metric/domain contracts; no final or primary arbitraryOD claim from scoped TP.','continue_on_failure':True,'workload_registry':identity(registry),'auxiliary_input_source_freeze':identity(freeze),'actual_driver_coverage':identity(index),'runs':selected}
  write_new(a.out_dir/filename,plan)
 print(json.dumps({'status':'PLANS_FROZEN_NOT_EXECUTED','plans':[str(a.out_dir/'primary-tune-native-plan.json'),str(a.out_dir/'native-domain-tune-plan.json')],'coverage':str(index),'runs':len(prepared),'scope':'No campaign launched. Release all CPU workers before invoking serial runner.'}))
if __name__=='__main__':main()
