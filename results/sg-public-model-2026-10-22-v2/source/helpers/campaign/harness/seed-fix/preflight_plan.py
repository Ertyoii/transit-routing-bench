#!/usr/bin/env python3
"""Input-only plan preflight. Never launches any routing/benchmark binary.
Build ./cmd/inputpreflight separately in each source-matched composed tree.
"""
import argparse,hashlib,json,pathlib,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('plan',type=pathlib.Path);p.add_argument('--preflight-map',required=True,type=pathlib.Path,help='JSON object: plan source cwd -> source-matched inputpreflight binary');p.add_argument('--out-dir',required=True,type=pathlib.Path);a=p.parse_args()
plan=json.loads(a.plan.read_text());mapping=json.loads(a.preflight_map.read_text());a.out_dir.mkdir(parents=True,exist_ok=False)
def flags(argv,key,default=None):
 vals=[]
 for i,v in enumerate(argv):
  if v==key: vals.append(argv[i+1] if i+1<len(argv) and not argv[i+1].startswith('-') else True)
  elif v.startswith(key+'='):vals.append(v.split('=',1)[1])
 if len(vals)>1:raise ValueError('duplicate flag '+key)
 return vals[0] if vals else default

groups={}
for run in plan['runs']:
 argv=run['argv'];kind=pathlib.Path(argv[0]).name;profile='profilebench' in kind
 schema='profile-from-point' if profile and flags(argv,'-point-workload',False) in (True,'true') else ('profile' if profile else 'point')
 cwd=pathlib.Path(run['cwd']);binary=mapping.get(str(cwd))
 if not binary:raise SystemExit('no source-matched inputpreflight mapping for '+str(cwd))
 def path_flag(key):
  v=flags(argv,key,'')
  return str((cwd/v).resolve()) if v else ''
 request={'id':run['id'],'dataset':path_flag('-dataset'),'queries':path_flag('-queries'),'schema':schema,'algorithm':flags(argv,'-algorithm',''),'preferences':path_flag('-preference-scenarios'),'scoped_config':path_flag('-scoped-config'),'ready_span_seconds':int(flags(argv,'-ready-span-seconds',60)),'max_window_seconds':int(flags(argv,'-max-window-seconds',600))}
 if not request['dataset'] or not request['queries']:raise SystemExit('preflight requires explicit exact dataset/workload in '+run['id'])
 groups.setdefault((str(cwd),binary,request['dataset']),[]).append(request)
failed=False;reports=[]
for index,((cwd,binary,dataset),requests) in enumerate(groups.items()):
 manifest=a.out_dir/f'input-manifest-{index:02}.json';manifest.write_text(json.dumps(requests,indent=2)+'\n')
 command=[binary,'-manifest',str(manifest.resolve())]
 result=subprocess.run(command,cwd=cwd,capture_output=True,text=True)
 (a.out_dir/f'preflight-{index:02}.jsonl').write_text(result.stdout);(a.out_dir/f'preflight-{index:02}.stderr').write_text(result.stderr)
 reports.append({'source_cwd':cwd,'dataset':dataset,'inputpreflight_binary':binary,'requests':len(requests),'returncode':result.returncode,'report':str(a.out_dir/f'preflight-{index:02}.jsonl')})
 failed=failed or result.returncode!=0
summary={'scope':'input_only_no_routing_no_outcomes','plan':str(a.plan.resolve()),'plan_sha256':hashlib.sha256(a.plan.read_bytes()).hexdigest(),'runs':len(plan['runs']),'source_groups':reports,'accepted':not failed}
(a.out_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2));sys.exit(1 if failed else 0)
