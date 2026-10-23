#!/usr/bin/env python3
"""Create-only absolute evidence-path repair and ACTUAL runner prelaunch gate.
Calls run_campaign.prepare_run only; NEVER run_one, process launch or router.
Original source, binaries, parser-qualified inputs and frozen plans stay intact.
"""
import argparse,copy,fcntl,json
from pathlib import Path
import run_campaign as runner
import campaign_gate
ROOT=Path(__file__).resolve().parents[1]
def write(p,v):
 with p.open('x') as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n')
def identity(p):return runner.file_identity(Path(p).resolve(strict=True))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--quiet-window-open',action='store_true');ap.add_argument('--original-dir',type=Path,required=True);ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--cpus',default='0-3');ap.add_argument('--sample-s',type=float,default=.2);a=ap.parse_args()
 if not a.quiet_window_open:raise SystemExit('Explicit quiet window required')
 lock=(runner.LEGACY_SETUP/'campaign.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 original=a.original_dir.resolve(strict=True);out=a.out_dir.resolve();out.mkdir(parents=True,exist_ok=False)
 freeze_path=original/'INPUT_SOURCE_BINARY_FREEZE.json';freeze=json.loads(freeze_path.read_text());composition_path=Path(freeze['composition']['path']);composition=json.loads(composition_path.read_text());expected_inputs={x['path']:x['sha256'] for x in freeze['input_files']};source_by_root={x['source_root']:x for x in composition['roles'].values()}
 campaign_gate.check_identity(freeze['composition'],ROOT,'Original composition')
 for entry in freeze['input_files']:campaign_gate.check_identity(entry,ROOT,'Original parser-qualified input')
 expected_bins={b['path']:b['sha256'] for r in composition['roles'].values() for b in r['binaries'].values()}
 names=['primary-tune-native-plan.json','native-domain-tune-plan.json'];original_ids={n:identity(original/n) for n in names}
 intent={'schema':'native-auxiliary-evidence-path-repair-intent-v4','reason':'Original relative composition evidence path resolved under bench cwd and would block before routing; normalize declared evidence inputs to absolute campaign-root paths.','original_plans':original_ids,'original_source_binary_input_freeze':identity(freeze_path),'composition':identity(composition_path),'repair_script':identity(Path(__file__)),'scope':'No source/binary/workload/config/argv changes, no router/constructor/benchmark; actual prepare_run preflight only.'};write(out/'REPAIR_INTENT.json',intent)
 pending={};rows=[];changes=[];env=runner.campaign_environment()
 for name in names:
  old=json.loads((original/name).read_text());plan=copy.deepcopy(old);registry=campaign_gate.load_registry(plan,out);campaign_gate.reject_execution_claims(plan,final_gate_passed=False)
  for before,spec in zip(old['runs'],plan['runs']):
   normalized=[]
   for text in spec['inputs']:
    path=Path(text)
    if not path.is_absolute():
     absolute=(ROOT/path).resolve(strict=True)
     if absolute!=composition_path:raise ValueError('Unexpected relative declared input; explicit repair review required:'+text)
     changes.append({'run_id':spec['id'],'old':text,'new':str(absolute)});text=str(absolute)
    normalized.append(text)
   spec['inputs']=normalized
   if {k:v for k,v in spec.items() if k!='inputs'}!={k:v for k,v in before.items() if k!='inputs'}:raise ValueError('Repair changed argv/source/resource/native contract')
   metadata,argv,cwd,run_env,roots,timeout=runner.prepare_run(spec,out/'__preflight_only__'/spec['id'],out/'__no_campaign_launched__',env,a.cpus,a.sample_s,registry,inspect_heldout=False)
   if argv!=before['argv'][:-1]+[str(out/'__preflight_only__'/spec['id']/'artifact')]:
    # Only run_dir output expansion may differ from the literal predeclared argv.
    expanded=[runner.expand(x,out/'__preflight_only__'/spec['id'],out/'__no_campaign_launched__') for x in before['argv']]
    if argv!=expanded:raise ValueError('Runner argv changed beyond output-directory expansion')
   if metadata['binary']['sha256']!=expected_bins[metadata['binary']['path']]:raise ValueError('Binary identity changed')
   for src in metadata['sources_before']:
    if src['go_source_hash_sha256']!=source_by_root[src['path']]['go_source_hash_sha256']:raise ValueError('Source identity changed')
   for inp in metadata['inputs']:
    if inp['path'] in expected_inputs and inp['sha256']!=expected_inputs[inp['path']]:raise ValueError('Parser-qualified input changed')
   gate=metadata['workload_gate']
   if gate['classification']!='registered_development' or gate['heldout_detected']:raise ValueError('Registry/split/heldout gate failed')
   if any(w['classification']!='tune' for w in gate['workloads']):raise ValueError('Native auxiliary plans remain tune-only')
   rows.append({'plan':name,'run_id':spec['id'],'accepted':True,'actual_prepare_run_metadata':metadata,'literal_argv_unchanged':spec['argv']==before['argv'],'cwd_source_roots_unchanged':spec['cwd']==before['cwd'] and spec['source_roots']==before['source_roots']})
  pending[name]=plan
 if len(rows)!=68 or len(changes)!=68:raise ValueError('Expected exactly68 qualified native slots and68 composition-path corrections')
 for name,ref in original_ids.items():campaign_gate.check_identity(ref,ROOT,'Original plan retained')
 report=out/'RUNNER_ENVELOPE_PREFLIGHT.json';write(report,{'schema':'actual-native-runner-envelope-preflight-v4','accepted':True,'runs':len(rows),'all_real_router_execution_performed':False,'scope':'Actual run_campaign.prepare_run, registry/environment/selector/source/binary/ALL declared evidence input gates; no subprocess router or benchmark launched.','original_plan_identities':original_ids,'original_parser_freeze':identity(freeze_path),'only_changes':changes,'campaign_environment':{k:env.get(k) for k in ('GOMAXPROCS','GOMEMLIMIT','GOGC','GOTOOLCHAIN','GOPROXY','GOSUMDB','GOCACHE','GOMODCACHE')},'rows':rows})
 repaired=[]
 for name,plan in pending.items():
  plan['path_projection_original_plan']=original_ids[name];plan['runner_envelope_preflight']=identity(report);plan['path_projection_repair_intent']=identity(out/'REPAIR_INTENT.json');write(out/name,plan);repaired.append(identity(out/name))
 receipt={'schema':'native-auxiliary-executable-plan-repair-v4','status':'PASS_RUNNER_ENVELOPE_PREFLIGHT_NO_EXECUTION','original_plans_unchanged':original_ids,'unchanged_actual_parser_freeze':identity(freeze_path),'source_and_binaries_unchanged':identity(composition_path),'repaired_plans':repaired,'runner_envelope_preflight':identity(report),'intent':identity(out/'REPAIR_INTENT.json'),'scope':'Only relative composition evidence paths converted to absolute. Native argv/source/config/workload/resource contracts unchanged. Original v5 plans preserved; use repaired projections for execution.'};write(out/'REPAIR_RECEIPT.json',receipt);print(json.dumps({'status':receipt['status'],'plans':repaired,'report':str(report),'receipt':str(out/'REPAIR_RECEIPT.json'),'runs':len(rows)}))
if __name__=='__main__':main()
