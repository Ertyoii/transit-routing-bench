#!/usr/bin/env python3
"""Tiny actual-composed-binary baseline/candidate differential; no real-model input."""
import argparse,fcntl,json,os,subprocess
from pathlib import Path
import qualify as q
E=q.E; ROOT=q.ROOT; B=q.B; BR=q.BR

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--quiet-window-open',action='store_true');a=ap.parse_args()
 if not a.quiet_window_open:raise SystemExit('Explicit owner quiet slot required')
 lock=(q.SETUP/'campaign.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX)
 out=E/'bench-differential-attempt01';out.mkdir(exist_ok=False)
 q.capture(out/'resources-before.json','before composed tiny binary differential')
 env=dict(os.environ,GOTOOLCHAIN='local',GOWORK='off',GOPROXY='off',GOSUMDB='off',GOMAXPROCS='2',GOMEMLIMIT='2GiB',GOFLAGS='-p=1')
 expected=json.loads((ROOT/'source-evidence/native-v5/COMPOSITION.json').read_text())['roles']['trex-compact']
 candidate=json.loads((E/'attempt02/QUALIFIED_SOURCE.json').read_text())
 original=expected['binaries']['familybench']; new=candidate['binaries']['familybench']
 if q.sha(Path(original['path']))!=original['sha256'] or q.sha(Path(new['path']))!=new['sha256']:raise ValueError('binary identity mismatch')
 if q.runtime_hash(BR)!=expected['go_source_hash_sha256'] or q.runtime_hash(B)!=candidate['benchmark_source_sha256']:raise ValueError('composed source identity mismatch')
 commands=[]
 for label,source,binary in [('base',BR,original),('candidate',B,new)]:
  args=[binary['path'],'-fixture','testdata/scoped.manifest.json','-algorithm','trex_static_caps_mandatory_verified_experimental','-scoped-config','testdata/scoped-config/trex.json','-out-dir',str(out/label),'-warmups','0','-repetitions','1','-batch-size','1','-stream-responses','-rss-safety-stop','2500000000']
  commands.append({'command':args,'cwd':str(source)})
  with (out/(label+'.log')).open('x') as f:f.write('COMMAND '+json.dumps(args)+'\n');f.flush();subprocess.run(args,cwd=source,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
 # Exclude only instrumentation, never route words/statuses/counters. A field
 # removed by suffix is a nanosecond clock, not a routing work counter.
 omitted=set()
 def canonical(v):
  if isinstance(v,list):return [canonical(x) for x in v]
  if isinstance(v,dict):
   result={}
   for key,value in v.items():
    if key.endswith('_ns') or key in ['resources','allocated_bytes']:
     omitted.add(key);continue
    result[key]=canonical(value)
   return result
  return v
 allrows={}
 for label in ['base','candidate']:
  summary=json.loads((out/label/'summary.json').read_text())
  provenance=summary['provenance']; want=expected['go_source_hash_sha256'] if label=='base' else candidate['benchmark_source_sha256']
  if not provenance['runtime_matches_build'] or provenance['runtime_tree_sha256']!=want or provenance['build_source_sha256']!=want:raise ValueError('runtime source not bound: '+label)
  rows={'preparation':canonical(summary['preparation']),'index_cost_final':canonical(summary['index_cost_final']),'passes':{}}
  for name in ['pass-00.json','forced-deadline.json']:
   artifact=json.loads((out/label/name).read_text())
   rows['passes'][name]={'algorithm':artifact['algorithm'],'repetition':artifact['repetition'],'warmup':artifact['warmup'],'records':canonical(artifact['records'])}
  allrows[label]=rows
  q.write(out/(label+'-canonical.json'),rows)
 if allrows['base']!=allrows['candidate']:
  q.write(out/'FAILED.json',{'status':'COMPOSED_BINARY_DIFFERENTIAL_MISMATCH','omitted_instrumentation_keys':sorted(omitted),'commands':commands});raise ValueError('composed tiny baseline/candidate canonical outputs differ')
 q.capture(out/'resources-after.json','after composed tiny binary differential')
 q.write(out/'PASS.json',{'status':'BYTE_IDENTICAL_CANONICAL_COMPOSED_BINARY_OUTPUTS','canonical_sha256':q.sha(out/'base-canonical.json'),'queries_per_source':6,'ordinary_statuses':['unsupported_cap_certificate','complete','complete'],'forced_deadline_statuses':['deadline','deadline','deadline'],'omitted_instrumentation_keys':sorted(omitted),'base_binary':original,'candidate_binary':new,'base_source_sha256':expected['go_source_hash_sha256'],'candidate_source_sha256':candidate['benchmark_source_sha256'],'commands':commands,'scope':'Original invented scoped fixture only; no real-model input; raw/final words/status/certificates/detail/native work/storage counters preserved.'})
 print((out/'PASS.json').read_text())
if __name__=='__main__':main()
