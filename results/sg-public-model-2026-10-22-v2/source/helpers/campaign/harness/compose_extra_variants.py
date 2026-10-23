import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT/'src';VP='vendor/github.com/ertyoii/transit-routing-go'
def overlay(a,b):shutil.copytree(a,b,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.cache','artifacts'))
def clone_overlay(base,dest):
 if dest.exists():raise FileExistsError(dest)
 subprocess.run(['git','clone','--no-hardlinks','--no-checkout',str(ROOT.parent/'bench'),str(dest)],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(['git','-C',str(dest),'checkout','-q','HEAD'],check=True);overlay(base,dest)
def lock(root,origin):
 p=root/'routing.lock.json';v=json.loads(p.read_text());files={str(f.relative_to(root/VP)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((root/VP).rglob('*')) if f.is_file()};v.update(files=files,source_sha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),origin=origin);p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
quality=SRC/'bench-v2-quality';clone_overlay(SRC/'bench-v2-storage',quality)
for package in ['recommend','validate']:
 shutil.rmtree(quality/VP/package);shutil.copytree(SRC/'bench-selector-hybrid'/VP/package,quality/VP/package,ignore=shutil.ignore_patterns('*_test.go'))
shutil.copy2(SRC/'routing-noncsa-quality/ultra/local_walk_ties.go',quality/VP/'ultra/local_walk_ties.go')
for p in ['cmd/familybench/scoped.go','cmd/familybench/local_walk_ties_test.go','regression/mcraptor/ultra_local_walk_ties_test.go']:
 shutil.copy2(SRC/'bench-noncsa-quality'/p,quality/p)
shutil.copytree(SRC/'bench-selector-hybrid/regression/recommend',quality/'regression/recommend',dirs_exist_ok=True)
# All native point candidates can omit fixed-score presentation controls explicitly.
for name in ['control','storage','slab','quality']:
 b=SRC/f'bench-v2-{name}';p=b/'cmd/familybench/main.go';s=p.read_text().replace('0 historical display1/3/5/10; explicit1..10 emits only that fixed-score display control','-1 omits fixed-score controls;0 historical1/3/5/10;positive emits only that fixed-score display control').replace('*displayK < 0 || *displayK > 10','*displayK < -1 || *displayK > 10').replace('if *displayK > 0 {\n\t\tdisplayLimits = []int{*displayK}\n\t}', 'if *displayK > 0 {\n\t\tdisplayLimits = []int{*displayK}\n\t} else if *displayK == -1 { displayLimits=[]int{} }');p.write_text(s);lock(b,f'V2 independent composed {name}, exact full-file lock, optional no-default-control serving. Ancestry commit only, no remote push.')
for name,routing in [('aux-control','routing-noncsa-control'),('aux-range','routing-noncsa-noarena')]:
 b=SRC/f'bench-v2-{name}';clone_overlay(SRC/'bench-auxiliary',b);shutil.rmtree(b/VP);shutil.copytree(SRC/routing,b/VP,ignore=shutil.ignore_patterns('.git','.cache','*_test.go'))
 if name=='aux-range':shutil.copy2(SRC/'routing-range-opt/raptor/range.go',b/VP/'raptor/range.go')
 lock(b,f'V2 auxiliary native {name}, full file lock. No CSA execution in selected range/tad contract. Not equal point/profile work.')
print('composed quality and2auxiliary variants, no-control serving flag added to all4 point trees')
