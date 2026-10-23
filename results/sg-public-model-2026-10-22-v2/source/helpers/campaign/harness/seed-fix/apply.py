#!/usr/bin/env python3
"""Apply narrow seed adapter changes to an explicitly selected NEW source copy.
Does not touch workloads or existing integrated sources unless operator names them.
"""
import argparse,pathlib,re,shutil,subprocess,json
p=argparse.ArgumentParser();p.add_argument('target',type=pathlib.Path);a=p.parse_args();root=a.target.resolve();here=pathlib.Path(__file__).resolve().parent
if not (root/'go.mod').is_file():raise SystemExit('target must be bench Go module')
changed=[]
for rel in ['cmd/familybench/main.go','cmd/profilebench/main.go','cmd/profilebench/point_input.go','cmd/profilebench/point_input_test.go','cmd/tadbench/main.go','cmd/corechgraphbench/main.go','cmd/corechgraphbench/audit.go']:
 f=root/rel
 if not f.exists():continue
 old=f.read_text();s=old
 s=re.sub(r'(Seed\s+)uint64(\s+`json:"seed"`)',r'\1workloadseed.Seed\2',s)
 s=s.replace('Seed: uint64(manifest.Seed)','Seed: workloadseed.Numeric(uint64(manifest.Seed))')
 s=s.replace('Seed: 9,','Seed: workloadseed.Numeric(9),').replace('got.Seed != 9','got.Seed.Uint64() != 9')
 s=s.replace('rand.NewPCG(w.Seed,','rand.NewPCG(w.Seed.Uint64(),').replace('rand.NewPCG(seed,','rand.NewPCG(seed.Uint64(),')
 s=re.sub(r'experiment.ThroughputConfidence\(([^\n]*), w.Seed\)',r'experiment.ThroughputConfidence(\1, w.Seed.Uint64())',s)
 s=re.sub(r'experiment.ThroughputConfidence\(([^\n]*), seed\)',r'experiment.ThroughputConfidence(\1, seed.Uint64())',s)
 if 'main.go' in rel and '"seed_metadata"' not in s:
  s=s.replace('"seed": w.Seed,','"seed": w.Seed, "seed_metadata": w.Seed.Metadata(),').replace('"seed": seed,','"seed": seed, "seed_metadata": seed.Metadata(),')
  if rel in ('cmd/profilebench/main.go','cmd/tadbench/main.go'):
   s=s.replace('"workload": w,','"workload": w, "seed_metadata": w.Seed.Metadata(),')
 if 'workloadseed.' in s and '"github.com/ertyoii/transit-routing-bench/workloadseed"' not in s:
  s=s.replace('import (','import (\n "github.com/ertyoii/transit-routing-bench/workloadseed"',1)
 if s!=old:f.write_text(s);changed.append(rel)
for directory in ['workloadseed','cmd/inputpreflight']:
 for src in (here/'overlay'/directory).glob('*.go'):
  dst=root/directory/src.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);changed.append(str(dst.relative_to(root)))
# Match scoped adapter names to the selected source, not a permissive union.
scoped_source=(root/'cmd/familybench/scoped.go').read_text()
start=scoped_source.index('var scopedNames =')
end=scoped_source.index('type outcomeError')
config=root/'cmd/inputpreflight/config.go'
c=config.read_text()
a0=c.index('var scopedNames =');a1=c.index('const tpSourceDomainName')
c=c[:a0]+scoped_source[start:end]+c[a1:]
config.write_text(c)
subprocess.run(['gofmt','-w',*[str(root/f) for f in changed]],check=True)
print(json.dumps({'target':str(root),'changed_files':changed},indent=2))
