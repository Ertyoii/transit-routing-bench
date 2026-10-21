#!/usr/bin/env python3
"""Create-only portable combined result package; verifies component and copy hashes."""
import argparse,datetime,hashlib,json,pathlib,shutil
BASE_COMMIT='f5fb8ebf5fbbb030ab0c3ed4c7feee33dff7311c'
MAX_FILE=2*1024*1024;MAX_TOTAL=64*1024*1024;MAX_FILES=512

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def verify(root,name):
 m=json.load(open(root/name))
 for f in m['files']:
  rel=pathlib.Path(f['path']);assert not rel.is_absolute() and '..' not in rel.parts; p=root/rel;assert not p.is_symlink() and p.is_file() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256'],f['path']
 return {'name':name,'bytes':(root/name).stat().st_size,'sha256':sha(root/name)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=pathlib.Path,required=True);ap.add_argument('--evidence',type=pathlib.Path,required=True);ap.add_argument('--docs',type=pathlib.Path,required=True);ap.add_argument('--tools-root',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args()
 sb=verify(a.source,'PAYLOAD_MANIFEST.json');eb=verify(a.evidence,'PUBLICATION_MANIFEST.json');si=json.load(open(a.evidence/'SHARD_INDEX.json'));audit=json.load(open(a.tools_root/'PUBLIC_PROJECTION_ACCOUNTING_CHECK.json'));assert si['row_count']==179516 and si['uncompressed_sha256']==audit['uncompressed_outcome_stream_sha256'] and audit['decision']=='pass'
 a.out.mkdir(parents=True,exist_ok=False);shutil.copytree(a.source,a.out/'repro');shutil.copytree(a.evidence,a.out/'evidence');(a.out/'publication-tools').mkdir()
 for n in ['README.md','RESULTS.md','METHODOLOGY.md','EVIDENCE_LEVELS.md']:shutil.copy2(a.docs/n,a.out/n)
 for n in ['shard_publication_outcomes.py','test_shard_publication_outcomes.py','SHARD_PUBLICATION_OUTCOMES.md','audit_publication_outcomes.py','assemble_publication.py']:shutil.copy2(a.tools_root/n,a.out/'publication-tools'/n)
 shutil.copy2(a.tools_root/'PUBLIC_PROJECTION_ACCOUNTING_CHECK.json',a.out/'PUBLICATION_ACCOUNTING_CHECK.json');shutil.copy2(a.source/'LICENSE',a.out/'LICENSE')
 for src,dst in [(a.source,a.out/'repro'),(a.evidence,a.out/'evidence')]:
  for p in src.rglob('*'):
   if p.is_file():assert sha(p)==sha(dst/p.relative_to(src))
 files=[]
 for p in sorted(a.out.rglob('*')):
  if not p.is_file():continue
  assert not p.is_symlink();n=p.stat().st_size;assert n<MAX_FILE,(str(p),n);files.append({'path':str(p.relative_to(a.out)),'bytes':n,'sha256':sha(p)})
 total=sum(f['bytes'] for f in files);assert len(files)<MAX_FILES and total<MAX_TOTAL
 m={'schema':'sg_public_bounded_result_package_file_manifest_v1','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'repository':'Ertyoii/transit-routing-bench','suggested_repository_prefix':'results/sg-public-model-2026-10-21/','expected_repository_base_commit':BASE_COMMIT,'file_count_excluding_this_manifest':len(files),'total_bytes_excluding_this_manifest':total,'maximum_file_bytes':max(f['bytes'] for f in files),'bounds':{'max_file_bytes_exclusive':MAX_FILE,'max_total_bytes_exclusive':MAX_TOTAL,'max_files_exclusive':MAX_FILES},'components':{'source_manifest':sb,'outcome_manifest':eb},'claim':'Bounded best-measured public-model source/results snapshot. No raw source databases, full witness legs or native binaries; no global/protocol convergence or latest-official authenticity. This manifest excludes itself to avoid recursive hashing.','files':files}
 (a.out/'FILE_MANIFEST.json').write_text(json.dumps(m,indent=2)+'\n');mf=a.out/'FILE_MANIFEST.json';print(json.dumps({'out':a.out.name,'files':len(files)+1,'total_bytes':total+mf.stat().st_size,'maximum_file_bytes':m['maximum_file_bytes'],'manifest_bytes':mf.stat().st_size,'manifest_sha256':sha(mf)}))
if __name__=='__main__':main()
