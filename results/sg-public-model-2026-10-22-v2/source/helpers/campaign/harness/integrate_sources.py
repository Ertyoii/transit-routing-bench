"""Compose already qualified V2 changes into independent source-bound build trees."""
import hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent
SRC=ROOT/'src';VENDOR='vendor/github.com/ertyoii/transit-routing-go'

def copy_overlay(source,dest):
    shutil.copytree(source,dest,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.cache','artifacts'))

def compose(name,routing,control=False):
    dest=SRC/name
    if dest.exists():raise FileExistsError(dest)
    subprocess.run(['git','clone','--no-hardlinks','--no-checkout',str(BASE/'bench'),str(dest)],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['git','-C',str(dest),'checkout','-q','HEAD'],check=True)
    copy_overlay(SRC/('bench-noncsa' if not control else 'bench-raptor-dense-opt-never'),dest) if not control else copy_overlay(BASE/'bench-raptor-dense-opt',dest)
    # One common driver, including streaming, for source controls and candidates.
    for p in ['main.go','stream.go','stream_test.go']:
        shutil.copy2(SRC/'bench-noncsa/cmd/familybench'/p,dest/'cmd/familybench'/p)
    shutil.copy2(SRC/'bench-noncsa/scripts/build.sh',dest/'scripts/build.sh')
    if (dest/VENDOR).exists():shutil.rmtree(dest/VENDOR)
    shutil.copytree(SRC/routing,dest/VENDOR,ignore=shutil.ignore_patterns('.git','.cache','artifacts','*_test.go'))
    for package in ['recommend','validate']:
        target=dest/VENDOR/package
        if target.exists():shutil.rmtree(target)
        shutil.copytree(SRC/'bench-selector'/VENDOR/package,target,ignore=shutil.ignore_patterns('*_test.go'))
    # Regression test every shared checker/selector behavior in every build tree.
    shutil.copytree(SRC/'bench-selector/regression/recommend',dest/'regression/recommend',dirs_exist_ok=True)
    main=dest/'cmd/familybench/main.go';s=main.read_text()
    selected=(SRC/'bench-selector/cmd/familybench/main.go').read_text()
    a=selected.index('\tvar qualityIndex *recommend.Index');b=selected.index('\tfmt.Println(*alg, "preparation"',a)
    c=s.index('\tvar qualityIndex *recommend.Index');d=s.index('\tfmt.Println(*alg, "preparation"',c)
    s=s[:c]+selected[a:b]+s[d:]
    s=s.replace('quality := flag.Bool("quality",', 'displayK := flag.Int("display-k", 0, "0 historical display1/3/5/10; explicit1..10 emits only that fixed-score display control")\n quality := flag.Bool("quality",',1)
    s=s.replace('\tflag.Parse()\n', '\tflag.Parse()\n if *displayK<0 || *displayK>10 {return fmt.Errorf("invalid display-k")}; displayLimits:=[]int{1,3,5,10};if *displayK>0 {displayLimits=[]int{*displayK}}\n',1)
    s=s.replace('for _, displayK := range []int{1, 3, 5, 10}', 'for _, displayK := range displayLimits')
    s=s.replace('"display_k": []int{1, 3, 5, 10}', '"display_k": displayLimits')
    main.write_text(s)
    lock=json.loads((dest/'routing.lock.json').read_text())
    files={str(p.relative_to(dest/VENDOR)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((dest/VENDOR).rglob('*')) if p.is_file()}
    lock.update(files=files,source_sha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),origin=f'V2 composed {routing}; shared checker lean selector and streaming driver. Ancestry commit only; exact file-list hashes identify working content. No remote push.')
    (dest/'routing.lock.json').write_text(json.dumps(lock,sort_keys=True,indent=2)+'\n')
    return {'tree':str(dest),'routing_variant':routing,'vendor_file_list_sha256':lock['source_sha256'],'control':control}

if __name__=='__main__':
    variants=[compose('bench-v2-control','routing-noncsa-control',True),compose('bench-v2-storage','routing-noncsa-noarena'),compose('bench-v2-slab','routing-noncsa')]
    (ROOT/'source-evidence/INTEGRATED_INITIAL.json').write_text(json.dumps(variants,indent=2)+'\n')
    print(json.dumps(variants,indent=2))
