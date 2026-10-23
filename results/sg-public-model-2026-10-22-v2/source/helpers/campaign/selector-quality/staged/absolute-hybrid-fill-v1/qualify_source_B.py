#!/usr/bin/env python3
"""Static prepared runner. Explicit owner slot required; takes global lock itself."""
import argparse,datetime,fcntl,hashlib,json,os,resource,subprocess,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];SETUP=ROOT.parent/'setup';HERE=Path(__file__).resolve().parent
GO=SETUP/'toolchain/go/bin/go';COMMON_SHA='72c399c1fbc5bc0ce4568cf1607df039ad3d66fd63cec7d79655dc96ece3dcfc'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
 with Path(path).open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--quiet-window-open',action='store_true');p.add_argument('--prefix',default='safe-fill-B-q01');a=p.parse_args()
 if not a.quiet_window_open:raise SystemExit('Owner must explicitly allocate the quiet CPU slot')
 if not a.prefix or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in a.prefix):raise ValueError('fresh alphanumeric/hyphen prefix required')
 with (SETUP/'campaign.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  source=ROOT/'src'/('bench-'+a.prefix);evidence=ROOT/'source-evidence'/a.prefix;replay=ROOT/'analysis'/(a.prefix+'-replay-attempt01');binaries={cmd:ROOT/'bin'/(cmd+'-'+a.prefix) for cmd in ['hybridfillprobe','finitesafeprobe','familybench']}
  for target in [source,evidence,replay,*binaries.values()]:
   if target.exists():raise FileExistsError('preserve prior attempt: '+str(target))
  evidence.mkdir();started=datetime.datetime.now(datetime.timezone.utc).isoformat();write(evidence/'STARTED.json',{'started_utc':started,'scope':'one authorized absolute-hybrid fill policy at separate3/5 plus unchanged safe controls; no real router or validation/test','memory_info':Path('/proc/meminfo').read_text(),'rlimits':{name:list(resource.getrlimit(getattr(resource,name))) for name in ['RLIMIT_AS','RLIMIT_DATA','RLIMIT_STACK','RLIMIT_NOFILE']},'cpu_lock':'global campaign.lock held by this process'})
  env=dict(os.environ,GOTOOLCHAIN='local',GOWORK='off',GOPROXY='off',GOSUMDB='off',GOMAXPROCS='2',GOCACHE=str(SETUP/'cache/go-build'),GOMODCACHE=str(SETUP/'cache/go-mod'));env['PATH']=str(GO.parent)+os.pathsep+env.get('PATH','')
  def run(name,args,cwd=ROOT):
   print(name,flush=True)
   with (evidence/(name+'.log')).open('x') as log:
    log.write('COMMAND '+json.dumps([str(x) for x in args])+'\n');log.flush();subprocess.run([str(x) for x in args],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
  try:
   run('01-compose',['python3',ROOT/'selector-quality/staged/finite20-safe-v1/prepare_source.py','--source-root',ROOT/'src/bench-sparse-lean-v3','--out-root',source,'--expected-source-sha256',COMMON_SHA,'--base-receipt',ROOT/'source-evidence/sparse-lean-v3/QUALIFIED_SOURCE.json','--include-fill'])
   run('02-recommend-tests',[GO,'test','-count=1','-buildvcs=false','-mod=vendor','./vendor/github.com/ertyoii/transit-routing-go/recommend'],source)
   run('03-lean-adapter-tests',[GO,'test','-count=1','-buildvcs=false','-mod=vendor','./regression','-run','FiniteSafe|HybridFill'],source)
   run('04-publisher-tests',[GO,'test','-count=1','-buildvcs=false','-mod=vendor','./cmd/familybench','-run','ResponsePublisher|ResponseStreamProcessBoundary'],source)
   modules=['analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py','analysis/test_evaluate_v2_safe_fill_B_staged.py','analysis/replay_absolute_hybrid_fill_candidates.py']
   run('05-python-syntax',['python3','-m','py_compile',*modules])
   for name in ['test_evaluate_v2_safe_fill_B_staged.py','test_evaluate_v2_finite_safe_staged.py','test_evaluate_v2_certified_delivery_v2.py']:
    run('06-'+name[:-3],['python3','-m','unittest','discover','-s','analysis','-p',name])
   print('07-sourcehash-and-build',flush=True)
   source_sha=subprocess.check_output([str(GO),'run','-buildvcs=false','-mod=vendor','./cmd/sourcehash'],cwd=source,env=env,text=True).strip();(source/'SOURCE_SHA256.txt').write_text(source_sha+'\n')
   for name,binary in binaries.items():run('07-build-'+name,[GO,'build','-buildvcs=false','-mod=vendor','-trimpath','-ldflags','-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256='+source_sha,'-o',binary,'./cmd/'+name],source)
   (source/'BINARY_SHA256.txt').write_text(''.join(sha(binary)+'  '+os.path.relpath(binary,source)+'\n' for binary in binaries.values()))
   configs=source/'serving-configs';configs.mkdir()
   for matrix in ['FINITE_SAFE_MATRIX.json','HYBRID_FILL_MATRIX.json']:
    for policy in json.loads((source/matrix).read_text())['policies']:write(configs/(policy['id']+'.json'),policy['config'])
   run('08-synthetic-cli',['python3',ROOT/'analysis/replay_absolute_hybrid_fill_candidates.py','--probe-root',source,'--probe',binaries['hybridfillprobe'],'--out',evidence/'cli-attempt01','--synthetic'])
   run('09-same-native-pool-replay',['python3',ROOT/'analysis/replay_absolute_hybrid_fill_candidates.py','--probe-root',source,'--probe',binaries['hybridfillprobe'],'--out',replay,'--manifest',ROOT/'analysis/selector-tune-v3-manifest-attempt02'])
   unchanged=subprocess.check_output([str(GO),'run','-buildvcs=false','-mod=vendor','./cmd/sourcehash'],cwd=source,env=env,text=True).strip()
   if unchanged!=source_sha:raise ValueError('source changed during qualification')
   paths=[HERE/'qualify_source_B.py',ROOT/'selector-quality/staged/finite20-safe-v1/prepare_source.py',ROOT/'selector-quality/staged/finite20-safe-v1/apply_integration.py',ROOT/'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py',ROOT/'analysis/test_evaluate_v2_safe_fill_B_staged.py',ROOT/'analysis/replay_absolute_hybrid_fill_candidates.py',source/'routing.lock.json',source/'FINITE_SAFE_ORIGIN.json',source/'FINITE_SAFE_MATRIX.json',source/'HYBRID_FILL_MATRIX.json',*sorted(configs.glob('*.json')),*sorted(HERE.glob('*'))]
   hashes={str(path):sha(path) for path in paths if path.is_file()};write(evidence/'ARTIFACT_SHA256.json',hashes)
   receipt={'schema':'sg-one-absolute-hybrid-fill-B-source-feature-qualification-v1','status':'source_adapter_CLI_evaluator_and_tune_feature_replay_qualified_not_real_serving_timed_or_validation_tested','started_utc':started,'finished_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_root':str(source),'source_sha256':source_sha,'binaries':{str(p):sha(p) for p in binaries.values()},'qualified_common_source_sha256':COMMON_SHA,'safe_A_remains_immutable':True,'one_new_fill_algorithm':True,'requested_display_budgets':[3,5],'synthetic_CLI_report':{'path':str(evidence/'cli-attempt01/REPORT.json'),'sha256':sha(evidence/'cli-attempt01/REPORT.json')},'tune_replay':{'path':str(replay/'REPORT.json'),'sha256':sha(replay/'REPORT.json')},'artifact_sha256_manifest':{'path':str(evidence/'ARTIFACT_SHA256.json'),'sha256':sha(evidence/'ARTIFACT_SHA256.json')},'evaluator_implementation':{'path':str(ROOT/'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py'),'sha256':sha(ROOT/'analysis/evaluate_v2_certified_delivery_safe_fill_B_staged.py')},'limitations':['Initial192 independently reconstructed native pools and incomplete common/LOFO reference generation only.','All11520 offered mappings and432 scalar slots with18unknown remain; no new router/model/test outcomes.','393 and stress are exposed tune diagnostics; no optimizer access.','Filled regret values are copied upper bounds only; base continuous optimality relies on unchanged separately audited source.','Conservative resource preflight is not an RSS/cycle proof.','Offline duplicate-base parity call is not serving work or latency evidence.']};write(evidence/'QUALIFIED_SOURCE_B.json',receipt);print(json.dumps(receipt),flush=True)
  except Exception as exc:
   write(evidence/'FAILED.json',{'error':str(exc),'traceback':traceback.format_exc(),'failed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'all_outputs_preserved':True});raise
 print('CPU_LOCK_RELEASED',flush=True)
if __name__=='__main__':main()
