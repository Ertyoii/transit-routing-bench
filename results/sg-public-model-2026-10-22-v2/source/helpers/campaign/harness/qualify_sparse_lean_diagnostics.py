#!/usr/bin/env python3
"""Explicit future quiet-window qualification only; no real-model measurement.
Staged statically. Acquires BLOCKING global lock to serialize authorized jobs.
"""
import argparse,fcntl,hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SETUP=ROOT.parent/'setup';GO=SETUP/'toolchain/go/bin/go';SRC=ROOT/'src/routing-sparse-cost-summary';BASE=ROOT/'src/routing-noncsa-quality';BENCH=ROOT/'src/bench-sparse-lean-diagnostics';VP=Path('vendor/github.com/ertyoii/transit-routing-go')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args,cwd,env,log):
 with log.open('x') as out:out.write('COMMAND '+json.dumps([str(x) for x in args])+'\n');out.flush();subprocess.run([str(x) for x in args],cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
def main():
 p=argparse.ArgumentParser();p.add_argument('--quiet-window-open',action='store_true');p.add_argument('--out-dir',required=True,type=Path);a=p.parse_args()
 if not a.quiet_window_open:raise SystemExit('No qualification without explicit quiet-window allocation')
 lock=(SETUP/'campaign.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX)
 evidence=a.out_dir.resolve();evidence.mkdir(parents=True,exist_ok=False);binary=ROOT/'bin/familybench-sparse-lean-diagnostics'
 if binary.exists() or (BENCH/'.git').exists():raise FileExistsError('Keep prior qualified candidate; create a new source/bench/bin revision rather than overwrite')
 env=dict(os.environ,GOTOOLCHAIN='local',GOWORK='off',GOPROXY='off',GOSUMDB='off',GOMAXPROCS='2',GOCACHE=str(SETUP/'cache/go-build'),GOMODCACHE=str(SETUP/'cache/go-mod'));env['PATH']=str(GO.parent)+os.pathsep+env.get('PATH','')
 # Original kernel/API files must be byte-identical, not just equivalent tests.
 for original in (BASE/'ultra').glob('*.go'):
  if original.read_bytes()!=(SRC/'ultra'/original.name).read_bytes():raise ValueError('Original native source changed:'+str(original))
 for original in (ROOT/'src/bench-v3-quality'/VP/'ultra').glob('*.go'):
  if original.read_bytes()!=(BENCH/VP/'ultra'/original.name).read_bytes():raise ValueError('Original native vendor source changed:'+str(original))
 gofiles=[SRC/'ultra/sparse_cost.go',SRC/'ultra/sparse_cost_test.go']+[BENCH/'cmd/familybench'/x for x in ['diagnostics.go','diagnostics_test.go','main.go','scoped.go','adapters.go']]
 run([GO.parent/'gofmt','-w',*gofiles],ROOT,env,evidence/'gofmt.log');shutil.copy2(SRC/'ultra/sparse_cost.go',BENCH/VP/'ultra/sparse_cost.go')
 lockpath=BENCH/'routing.lock.json';v=json.loads(lockpath.read_text());files={str(p.relative_to(BENCH/VP)):sha(p) for p in sorted((BENCH/VP).rglob('*')) if p.is_file()};v.update(files=files,source_sha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),origin='NEW Sparse scalar cost-summary and explicitly lean-diagnostics driver candidate. Original Preparation/proofs/search unchanged; full same-index evidence retained after serving; not query-kernel optimization.');lockpath.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
 run(['git','init','-b','sparse-lean-diagnostics'],BENCH,env,evidence/'git-init.log');run(['git','add','--all'],BENCH,env,evidence/'git-add.log');run(['git','-c','commit.gpgsign=false','-c','user.name=Cloud auxiliary build','-c','user.email=local-build@assistant.invalid','commit','-m','Stage Sparse lean diagnostics with full same-index evidence'],BENCH,env,evidence/'git-commit.log')
 run([GO,'test','-buildvcs=false','./ultra','-run','^Test(SparseCost|CappedDenseFrozenSparseCertificates)','-count=1','-timeout=180s'],SRC,env,evidence/'source-cost-ownership-counts-native-parity.log')
 run([GO,'test','-race','-buildvcs=false','./ultra','-run','^TestSparseCostConcurrent','-count=1','-timeout=180s'],SRC,env,evidence/'source-cost-concurrency-race.log')
 run([GO,'test','-buildvcs=false','-mod=vendor','./cmd/familybench','-run','^TestSparseDiagnostics','-count=1','-timeout=180s'],BENCH,env,evidence/'driver-native-output-evidence-parity.log')
 fingerprint=subprocess.check_output([str(GO),'run','-buildvcs=false','-mod=vendor','./cmd/sourcehash'],cwd=BENCH,env=env,text=True).strip();run([GO,'build','-buildvcs=false','-mod=vendor','-trimpath','-ldflags','-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256='+fingerprint,'-o',binary,'./cmd/familybench'],BENCH,env,evidence/'build.log')
 manifest={'status':'QUALIFIED_SYNTHETIC_ONLY_NOT_MEASURED','source':str(SRC),'bench':str(BENCH),'source_hash':fingerprint,'routing_file_list_sha256':v['source_sha256'],'binary':{'path':str(binary),'sha256':sha(binary)},'scope':'Scalar-only diagnostics; original Preparation/proofs/search byte-identical. Full same-index proof evidence after serving. No real-model router or benchmark. No CSA execution.'}
 with (evidence/'QUALIFIED_SOURCE.json').open('x') as f:json.dump(manifest,f,sort_keys=True,indent=2);f.write('\n')
 print(json.dumps(manifest))
if __name__=='__main__':main()
