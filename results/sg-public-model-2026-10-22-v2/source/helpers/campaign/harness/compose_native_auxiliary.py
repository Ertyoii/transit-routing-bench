#!/usr/bin/env python3
"""CREATE-ONLY, explicit quiet-window composition/qualification/build.
Never launches a real-model router, measurement or campaign. Requires the SAME
nonblocking campaign.lock as measurements, so it cannot overlap their barrier.
Prepared statically; not executed merely by writing this script.
"""
import argparse,fcntl,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'src';SETUP=ROOT.parent/'setup';VP=Path('vendor/github.com/ertyoii/transit-routing-go');TEMPLATES=ROOT/'harness/native-auxiliary-templates'
GO=SETUP/'toolchain/go/bin/go'
PROD66=['tripbased/'+p for p in ['bounded_walking.go','capped_patterns.go','cost_summary.go','flash.go','flash_graph.go','trex.go','trex_diagnostic.go','trex_query.go','trex_walking_scope.go']]+['docs/CAPPED_WALKING_CLOSURE.md']
def write_new(p,v):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def runtime_hash(root):
 files=[]
 for parent,dirs,names in os.walk(root):
  dirs[:]=[d for d in dirs if d not in ('.git','.cache','artifacts')]
  for n in names:
   p=Path(parent)/n;rel=p.relative_to(root).as_posix()
   if n.endswith('.go') or n in ('go.mod','routing.lock.json') or rel=='vendor/modules.txt':files.append((rel,p))
 h=hashlib.sha256()
 for rel,p in sorted(files):
  b=p.read_bytes();a=rel.encode();h.update(f'{len(a)}:'.encode()+a+f':{len(b)}:'.encode()+b)
 return h.hexdigest()
def copytree(a,b):shutil.copytree(a,b,ignore=shutil.ignore_patterns('.git','.cache','artifacts','__pycache__','*.pyc'))
def run(cmd,cwd,env,log):
 with log.open('x') as f:
  f.write('COMMAND '+json.dumps([str(x) for x in cmd])+'\n');f.flush();subprocess.run([str(x) for x in cmd],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
def patch_once(s,old,new,label):
 if s.count(old)!=1:raise ValueError(f'{label}: expected exactly one anchor, found{s.count(old)}')
 return s.replace(old,new,1)
def actual_parser_probe(root,driver):
 p=root/'cmd'/driver/'main.go';s=p.read_text()
 s=patch_once(s,'func run() error {','func run() error {\n inputOnly := flag.Bool("input-only", false, "parse and bind exact consuming-driver inputs; no constructor or search")',driver+' flag')
 s=patch_once(s,'import (','import (\n "github.com/ertyoii/transit-routing-bench/nativeinputprobe"',driver+' import')
 if driver=='familybench':
  anchor='\truntime.GC()\n\tvar before, after runtime.MemStats';branch='\tif *inputOnly { return nativeinputprobe.Emit("familybench","point",dh,qh,scopedSHA,w.Seed,len(w.Items),*alg) }\n'
 elif driver in ('profilebench','tadbench'):
  anchor='\tprovenance, e := experiment.Identify(".")'
  if driver=='profilebench':branch='\tif *inputOnly { schema:="profile";if *pointWorkload {schema="profile-from-point"};return nativeinputprobe.Emit("profilebench",schema,dh,qh,"",w.Seed,len(w.Items),names) }\n'
  else:branch='\tif *inputOnly { return nativeinputprobe.Emit("tadbench","point",dh,qh,"",w.Seed,len(w.Items),names) }\n'
 elif driver=='ultrabench':
  anchor='\tcfg := ultra.Config{';branch='\tif *inputOnly { return nativeinputprobe.Emit("ultrabench","point",dh,qh,"",work.Seed,len(work.Items),"ultra_native") }\n'
 elif driver=='corechgraphbench':
  anchor='\t// Independent label-correcting Bellman-Ford relaxation';branch='\tif *inputOnly { return nativeinputprobe.Emit("corechgraphbench","graph-point-anchors",dh,qh,"",w.Seed,len(w.Items),anchors) }\n'
 else:raise ValueError(driver)
 s=patch_once(s,anchor,branch+anchor,driver+' preconstructor branch');p.write_text(s)
def seed_ultra(root):
 p=root/'cmd/ultrabench/main.go';s=p.read_text()
 s,n=re.subn(r'(Seed\s+)uint64(\s+`json:"seed"`)',r'\1workloadseed.Seed\2',s)
 if n!=1:raise ValueError('ultrabench requires exactly one old uint64 seed; inspect new baseline rather than broad replacement')
 s=patch_once(s,'import (','import (\n "github.com/ertyoii/transit-routing-bench/workloadseed"','ultra seed import')
 s=patch_once(s,'rand.NewPCG(work.Seed,','rand.NewPCG(work.Seed.Uint64(),','ultra RNG')
 s=patch_once(s,'experiment.ThroughputConfidence(throughput[name], work.Seed)','experiment.ThroughputConfidence(throughput[name], work.Seed.Uint64())','ultra CI')
 s=patch_once(s,'"seed": work.Seed,','"seed": work.Seed, "seed_metadata": work.Seed.Metadata(),','ultra summary');p.write_text(s)
 shutil.copy2(TEMPLATES/'ultrabench_seed_test.go',root/'cmd/ultrabench/native_seed_test.go')
def lock(root,role):
 p=root/'routing.lock.json';v=json.loads(p.read_text());files={str(f.relative_to(root/VP)):sha(f) for f in sorted((root/VP).rglob('*')) if f.is_file()}
 v.update(files=files,source_sha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),origin=f'Native auxiliary {role}; targeted V1 66b bounded closure only when declared; current seed-fixed common driver/checker/selector retained. Local ancestry only, no remote push.');p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
 return v['source_sha256']
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--quiet-window-open',action='store_true');ap.add_argument('--prefix',default='native-v4');a=ap.parse_args()
 if not a.quiet_window_open:raise SystemExit('Refusing: explicit quiet window not acknowledged; no composition or CPU work performed')
 if not re.fullmatch(r'[a-z][a-z0-9-]{1,40}',a.prefix):raise SystemExit('unsafe prefix')
 lockfile=(SETUP/'campaign.lock').open('a+');fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
 evidence=ROOT/'source-evidence'/a.prefix;evidence.mkdir(exist_ok=False)
 roles={'prep':['familybench','tadbench','ultrabench','corechgraphbench','inputpreflight'],'fullmetric-fixed':['familybench','inputpreflight'],'range':['profilebench','inputpreflight'],'range-control':['profilebench','inputpreflight']}
 roots={role:SRC/f'bench-{a.prefix}-{role}' for role in roles};bins={role:{cmd:ROOT/'bin'/f'{cmd}-{a.prefix}-{role}' for cmd in cmds} for role,cmds in roles.items()}
 for p in [*roots.values(),*[b for m in bins.values() for b in m.values()]]:
  if p.exists():raise FileExistsError(f'Create-only target exists: {p}')
 env=dict(os.environ,GOTOOLCHAIN='local',GOWORK='off',GOPROXY='off',GOSUMDB='off',GOMAXPROCS='2',GOCACHE=str(SETUP/'cache/go-build'),GOMODCACHE=str(SETUP/'cache/go-mod'));env['PATH']=str(GO.parent)+os.pathsep+env.get('PATH','')
 manifest={'schema':'native-auxiliary-composition-v1','status':'IN_PROGRESS_NOT_FOR_MEASUREMENT','base':str(SRC/'bench-v3-storage'),'auxiliary_base':str(SRC/'bench-v3-aux-control'),'roles':{}}
 write_new(evidence/'STARTED.json',manifest)
 run([sys.executable,'-m','unittest','discover','-s',ROOT/'harness','-p','test_native_auxiliary_planning.py'],ROOT,env,evidence/'planning-projection-unit.log')
 for role,dest in roots.items():
  copytree(SRC/'bench-v3-storage',dest)
  # Only auxiliary COMMANDS come from seed-fixed aux source. Common driver,
  # workloadseed, checker, selector and repaired familybench remain v3 storage.
  for cmd in ('profilebench','tadbench','corechgraphbench','ultrabench'):
   shutil.rmtree(dest/'cmd'/cmd);copytree(SRC/'bench-v3-aux-control/cmd'/cmd,dest/'cmd'/cmd)
  if role!='fullmetric-fixed':
   for rel in PROD66:
    target=dest/VP/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(SRC/'routing-native-prep'/rel,target)
  if role=='range':shutil.copy2(SRC/'routing-range-opt/raptor/range.go',dest/VP/'raptor/range.go')
  if role in ('range','range-control'):
   shutil.rmtree(dest/'regression/profilequery');copytree(SRC/'bench-range/regression/profilequery',dest/'regression/profilequery')
   if any('transit-routing-go/profilecsa' in p.read_text() for p in (dest/'regression/profilequery').glob('*.go')):raise ValueError('CSA oracle leak in range qualification')
  (dest/'nativeinputprobe').mkdir();shutil.copy2(TEMPLATES/'nativeinputprobe.go',dest/'nativeinputprobe/probe.go')
  seed_ultra(dest)
  for cmd in ('familybench','profilebench','tadbench','corechgraphbench','ultrabench'):actual_parser_probe(dest,cmd)
  gofiles=[dest/'nativeinputprobe/probe.go',dest/'cmd/ultrabench/native_seed_test.go']+[dest/'cmd'/c/'main.go' for c in ('familybench','profilebench','tadbench','corechgraphbench','ultrabench')]
  run([GO.parent/'gofmt','-w',*gofiles],dest,env,evidence/f'{role}-gofmt.log');vendor=lock(dest,role)
  # A new independent local git repository. Never share old worktree metadata.
  run(['git','init','-b',a.prefix+'-'+role],dest,env,evidence/f'{role}-git-init.log')
  run(['git','add','--all'],dest,env,evidence/f'{role}-git-add.log')
  run(['git','-c','commit.gpgsign=false','-c','user.name=Cloud auxiliary build','-c','user.email=local-build@assistant.invalid','commit','-m',f'Freeze {a.prefix} {role} native auxiliary composition'],dest,env,evidence/f'{role}-git-commit.log')
  for tag,args in [('input-units',['./workloadseed','./cmd/inputpreflight','./cmd/ultrabench','./cmd/profilebench']),('family-native',['./cmd/familybench']),('graph-native',['./cmd/corechgraphbench'])]:
   run([GO,'test','-buildvcs=false','-mod=vendor',*args,'-count=1','-timeout=180s'],dest,env,evidence/f'{role}-{tag}.log')
  if role in ('range','range-control'):run([GO,'test','-buildvcs=false','-mod=vendor','./regression/profilequery','-count=1','-timeout=180s'],dest,env,evidence/f'{role}-whole-grid-oracle.log')
  fingerprint=subprocess.check_output([str(GO),'run','-buildvcs=false','-mod=vendor','./cmd/sourcehash'],cwd=dest,env=env,text=True).strip()
  if fingerprint!=runtime_hash(dest):raise ValueError('Go/Python sourcehash mismatch')
  record={'source_root':str(dest),'source_role':role,'go_source_hash_sha256':fingerprint,'routing_file_list_sha256':vendor,'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip(),'binaries':{}}
  for cmd,out in bins[role].items():
   run([GO,'build','-buildvcs=false','-mod=vendor','-trimpath','-ldflags',f'-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256={fingerprint}','-o',out,'./cmd/'+cmd],dest,env,evidence/f'{role}-{cmd}-build.log')
   record['binaries'][cmd]={'path':str(out),'sha256':sha(out)}
  if runtime_hash(dest)!=fingerprint:raise ValueError('Source changed during qualification/build')
  manifest['roles'][role]=record
 # Focused source qualification executes non-CSA methods only; never ./...
 run([GO,'test','-buildvcs=false','./tripbased','-run','^Test(WalkingScope|CompactLinks)','-count=1','-timeout=180s'],SRC/'routing-native-prep',env,evidence/'routing-bounded-compact-focused.log')
 run([GO,'test','-buildvcs=false','./raptor','-run','^TestRangeDenseStorage','-count=1','-timeout=180s'],SRC/'routing-range-opt',env,evidence/'routing-range-native-focused.log')
 manifest['status']='QUALIFIED_BUILT_SOURCE_FROZEN_INPUT_PREFLIGHT_PENDING';manifest['scope']='No real-model constructor or routing. Input-only and focused synthetic non-CSA checks only. No campaign launched.';write_new(evidence/'COMPOSITION.json',manifest);print(json.dumps({'manifest':str(evidence/'COMPOSITION.json'),'status':manifest['status']}))
if __name__=='__main__':main()
