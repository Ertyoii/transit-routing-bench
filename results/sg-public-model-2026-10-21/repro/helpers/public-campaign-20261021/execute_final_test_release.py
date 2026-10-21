#!/usr/bin/env python3
"""Create all public seals first, then optionally execute the unchanged blind slate serially."""
import argparse,datetime,hashlib,json,pathlib,subprocess,sys
R=pathlib.Path(__file__).resolve().parents[1];RUNNER=R/'setup/run_campaign.py'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(pathlib.Path(p).read_text())
def check(ref):
 p=pathlib.Path(ref['path']).resolve(strict=True);assert sha(p)==ref['sha256'],('changed',str(p));return p
def validate_master(master):
 d=read(master);assert d['schema']=='sg_public_model_master_finalist_release_v1';assert d['test_outcomes_exposed_at_freeze'] is False;assert len(d['entries'])==19;assert len({x['name'] for x in d['entries']})==19
 for x in d['entries']:
  plan=read(check(x['plan']));assert plan['evaluation_mode']=='public_model_final_evaluation';assert plan['continue_on_failure'] is True;assert len(plan['runs'])==4;assert all(str(master.resolve()) in z['inputs'] for z in plan['runs'])
 for ref in d['validation_evidence']:check(ref)
 return d

def main():
 a=argparse.ArgumentParser();a.add_argument('--release-dir',type=pathlib.Path,required=True);a.add_argument('--seal-all',action='store_true');a.add_argument('--launch-manifest-sha256');a.add_argument('--run',action='store_true');x=a.parse_args();master=x.release_dir/'FINALIST_RELEASE.json';d=validate_master(master);launch=x.release_dir/'TEST_LAUNCH_MANIFEST.json'
 assert x.seal_all != x.run,'choose exactly --seal-all or --run'
 if x.seal_all:
  assert not launch.exists();sealdir=x.release_dir/'seals';sealdir.mkdir(exist_ok=False);entries=[]
  for entry in d['entries']:
   check(entry['plan']);sf=sealdir/(entry['name']+'-seal.json');cmd=[sys.executable,str(RUNNER),'seal-finalists','--plan',entry['plan']['path'],'--out',str(sf)];p=subprocess.run(cmd,capture_output=True,text=True);(sealdir/(entry['name']+'-seal.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(entry['name'],p.stderr)
   ref={'path':str(sf),'sha256':sha(sf)};cmd=[sys.executable,str(RUNNER),'validate-seal','--plan',entry['plan']['path'],'--seal',str(sf),'--seal-sha256',ref['sha256'],'--require-public-model-data'];p=subprocess.run(cmd,capture_output=True,text=True);(sealdir/(entry['name']+'-validation.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(entry['name'],p.stderr);v=json.loads(p.stdout);assert v['public_model_data_gate_passed'] is True and v['official_data_gate_passed'] is False
   entries.append({'name':entry['name'],'plan':entry['plan'],'seal':ref,'output':str(x.release_dir/('out-'+entry['name']))});print('SEALED_AND_PUBLIC_VALIDATED',entry['name'],flush=True)
  payload={'schema':'sg_public_model_blind_test_launch_manifest_v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'master_release':{'path':str(master),'sha256':sha(master)},'all_seals_before_any_test':True,'entries':entries,'launcher_sha256':sha(__file__),'runner_sha256':sha(RUNNER),'qualification':'public-model only; officiallatestauthenticity false','adaptation_policy':'No testconditioned changes; preservefailures and stop ongating/runnererror, no silentunsealed fallback.'};launch.write_text(json.dumps(payload,indent=2)+'\n');print(json.dumps({'launch_manifest':str(launch),'sha256':sha(launch),'sealed_subcampaigns':len(entries),'routers_executed':0}),flush=True);return
 assert x.launch_manifest_sha256 and sha(launch)==x.launch_manifest_sha256,'exact launchmanifestsha required';l=read(launch);check(l['master_release']);assert l['launcher_sha256']==sha(__file__) and l['runner_sha256']==sha(RUNNER);assert l['all_seals_before_any_test'] is True;assert [e['name'] for e in l['entries']]==[e['name'] for e in d['entries']]
 for e in l['entries']:check(e['plan']);check(e['seal']);assert not pathlib.Path(e['output']).exists(),e['output']
 for e in l['entries']:
  # Every subplan and seal is rechecked before each untouched planned process group.
  validate_master(master)
  for ee in l['entries']:check(ee['plan']);check(ee['seal'])
  cmd=[sys.executable,str(RUNNER),'run','--plan',e['plan']['path'],'--out',e['output'],'--seal',e['seal']['path'],'--seal-sha256',e['seal']['sha256'],'--continue-on-failure'];print('EXECUTING',json.dumps(cmd),flush=True);p=subprocess.run(cmd);s=read(pathlib.Path(e['output'])/'status.json');assert s['state']=='completed',(e['name'],s['state'],p.returncode)
 print('ALL_DECLARED_SEALED_TEST_SUBCAMPAIGNS_TERMINAL',flush=True)
if __name__=='__main__':main()
