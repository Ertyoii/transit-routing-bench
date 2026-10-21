#!/usr/bin/env python3
"""Read-only outcome/provenance accounting check; no native routing or data copying."""
import argparse,collections,datetime,gzip,hashlib,json,pathlib

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--stage',type=pathlib.Path,required=True);ap.add_argument('--launch',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args();s=a.stage;m=json.load(open(s/'PUBLICATION_MANIFEST.json'));idx=json.load(open(s/'ARTIFACT_INDEX.json'));expected={};originals={}
 for f in m['files']:
  p=s/f['path'];assert not p.is_symlink() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256'],f['path']
 actual={str(p.relative_to(s)) for p in s.rglob('*') if p.is_file()};assert actual=={f['path'] for f in m['files']}|{'PUBLICATION_MANIFEST.json'}
 for c in idx['original_artifact_sha256']:
  for run in c['runs']:
   for role,n in run['projected_record_counts'].items():expected[(c['campaign'],run['run_id'],role)]=n
   originals[(c['campaign'],run['run_id'])]=run['original_artifacts']
 launch=json.load(open(a.launch));finalnames={pathlib.Path(e['output']).name for e in launch['entries']};seen=set();observed=collections.Counter();roles=collections.Counter();units=collections.Counter();statuses=collections.Counter();final=collections.Counter();prelaunch=0;stream=hashlib.sha256()
 with gzip.open(s/'outcome-records.jsonl.gz','rb') as f:
  for n,line in enumerate(f):
   assert line.endswith(b'\n');stream.update(line);r=json.loads(line);c=r['campaign'];run=r['run_id'];role=r['measurement_role'];observed[(c,run,role)]+=1;roles[role]+=1;units[(r.get('denominator_unit'),role)]+=1;statuses[(role,r.get('status'))]+=1
   key=(c,run,r.get('algorithm'),r.get('repetition'),role,r.get('source_artifact'),r.get('source_record_index'));assert key not in seen,key;seen.add(key)
   if r.get('source_artifact') is not None:assert originals[(c,run)][r['source_artifact']]==r['source_artifact_sha256']
   if r.get('launch_state')=='prelaunch':
    assert role=='offered-unresolved' and r.get('attempted') is None and r.get('completed') is None and r.get('response_ns') is None;prelaunch+=1
   if c in finalnames:
    final[role]+=1
    if role=='measured':assert r['status']=='complete' and r['attempted'] and r['completed']
 assert dict(observed)==expected and sum(roles.values())==idx['rows'];assert final['measured']==24120 and final['forced-deadline']==24120 and final['warmup']==0;assert prelaunch==2004
 members=set()
 with gzip.open(s/'provenance-records.jsonl.gz','rt',encoding='utf-8') as f:
  for line in f:
   v=json.loads(line);p=pathlib.Path(v['path']);assert not p.is_absolute() and '..' not in p.parts and v['path'] not in members;members.add(v['path']);b=(json.dumps(v['content'],sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode();assert len(b)==v['bytes'] and hashlib.sha256(b).hexdigest()==v['sha256']
 assert len(members)==idx['provenance_member_count']
 result={'schema':'sg_public_projection_accounting_check_v1','generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'decision':'pass','campaigns':len(idx['original_artifact_sha256']),'planned_process_slots':len(originals),'projected_rows':idx['rows'],'measurement_roles':dict(roles),'denominator_role_counts':[{'unit':k[0],'role':k[1],'rows':v} for k,v in sorted(units.items(),key=lambda z:str(z[0]))],'status_role_counts':[{'role':k[0],'status':k[1],'rows':v} for k,v in sorted(statuses.items(),key=lambda z:str(z[0]))],'final_test_roles':dict(final),'prelaunch_unresolved_null_attempt_slots':prelaunch,'provenance_members_verified':len(members),'uncompressed_outcome_stream_sha256':stream.hexdigest(),'original_compact_publication_manifest_sha256':sha(s/'PUBLICATION_MANIFEST.json'),'all_output_file_hashes_verified':True,'all_per_run_role_counts_reconcile':True,'duplicate_source_row_identities':0,'scope':'Configuration/repetition/control/prelaunch slots across distinct point/profile/graph-row units, not unique passenger demand; this checks portable projection accounting and hashes, not a new routing or quality experiment. Privacy/source-data restrictions are enforced separately by the projection.'}
 a.out.open('x').write(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['decision','projected_rows','provenance_members_verified','prelaunch_unresolved_null_attempt_slots','uncompressed_outcome_stream_sha256']}))
if __name__=='__main__':main()
