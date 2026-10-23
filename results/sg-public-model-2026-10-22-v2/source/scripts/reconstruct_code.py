#!/usr/bin/env python3
"""Create-only offline source byte materializer. Never executes project code."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def h(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads((ROOT/p).read_text())
def safe(p):
 x=Path(p)
 if x.is_absolute() or '..' in x.parts or '.git' in x.parts:raise ValueError('Unsafe relative path')
 return x
HEADER=re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
def apply(files,data):
 lines=data.decode().splitlines(keepends=True);out=dict(files);i=0
 while i<len(lines):
  if not lines[i].startswith('--- '):i+=1;continue
  old=lines[i][4:].strip();new=lines[i+1][4:].strip();i+=2
  src=None if old=='/dev/null' else old.removeprefix('a/');dest=None if new=='/dev/null' else new.removeprefix('b/')
  if src:safe(src)
  if dest:safe(dest)
  oldlines=out[src].decode().splitlines(keepends=True) if src else [];result=[];pos=0
  while i<len(lines) and not lines[i].startswith('--- '):
   m=HEADER.match(lines[i])
   if not m:i+=1;continue
   start,count=int(m[1]),int(m[2] or 1);index=start-1 if count else start
   if index<pos:raise ValueError('Patch order')
   result.extend(oldlines[pos:index]);pos=index;i+=1
   while i<len(lines) and lines[i][:1] in {' ','+','-'} and not lines[i].startswith('--- '):
    tag,line=lines[i][0],lines[i][1:];i+=1
    if tag in {' ','-'}:
     if pos>=len(oldlines) or oldlines[pos]!=line:raise ValueError('Exact patch context mismatch: '+str(src))
     if tag==' ':result.append(line)
     pos+=1
    else:result.append(line)
  result.extend(oldlines[pos:])
  if dest is None:
   if ''.join(result):raise ValueError('Nonempty deleted file')
  else:out[dest]=''.join(result).encode()
  if src and src!=dest:out.pop(src,None)
 return out

def verify(files,name):
 expected=read('source-hashes/'+name+'.json')['files']
 if set(files)!=set(expected):raise ValueError('Source path-set mismatch '+name)
 for p,b in files.items():
  if len(b)!=expected[p]['bytes'] or h(b)!=expected[p]['sha256']:raise ValueError('Source byte mismatch '+p)

def reconstruct(name,seen=None):
 seen=set() if seen is None else seen
 if name in seen:raise ValueError('Dependency cycle')
 seen.add(name);plan=read('BRANCH_RECONSTRUCTION.json')
 if name in plan['bases']:
  files={p:(ROOT/plan['bases'][name]/safe(p)).read_bytes() for p in read('source-hashes/'+name+'.json')['files']}
 else:
  rows={x['name']:x for x in plan['ordered_branches']}
  if name not in rows:raise ValueError('Unknown branch '+name)
  row=rows[name];files=reconstruct(row['reconstruction_parent'],seen);pb=(ROOT/safe(row['patch'])).read_bytes()
  if h(pb)!=row['patch_sha256']:raise ValueError('Patch hash mismatch')
  files=apply(files,pb)
 verify(files,name);return files

def main():
 p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--tree');g.add_argument('--helpers',action='store_true');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():raise FileExistsError('Output must be a new directory')
 if a.tree:files=reconstruct(a.tree)
 else:
  files={};rename={'campaign':'campaign-v2-20261021','audit':'campaign-v2-audit-20261021','evalkit':'evalkit'}
  for row in read('SOURCE_ALLOWLIST.json')['supplementary_source_decisions']:
   if row['decision']!='allow':continue
   rel=safe(row['bundle_path']);b=(ROOT/rel).read_bytes()
   if h(b)!=row['sha256']:raise ValueError('Helper hash mismatch')
   rest=rel.parts[1:];dest=Path(rename[rest[0]],*rest[1:]);files[str(dest)]=b
 a.out.mkdir(parents=True)
 for name,b in files.items():
  dest=a.out/safe(name);dest.parent.mkdir(parents=True,exist_ok=True)
  with dest.open('xb') as f:f.write(b)
 print(json.dumps({'files':len(files),'source_bytes':sum(map(len,files.values())),'project_code_executed':False}))
if __name__=='__main__':main()
