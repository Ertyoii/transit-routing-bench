#!/usr/bin/env python3
"""Compare frozen selectors on validated feature replays, not search truth/timing.

This script never changes a selector based on validation/test outcomes. Raw-pool
reference is explicitly incomplete; scalar-oracle comparisons are a separate lane.
"""
import argparse,glob,hashlib,json,math,pathlib,subprocess,statistics
p=argparse.ArgumentParser();p.add_argument('--pass-glob',action='append',required=True);p.add_argument('--probe',required=True);p.add_argument('--out-dir',required=True);p.add_argument('--phase',choices=['historical_tune','tune','validation','test'],required=True);a=p.parse_args();root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.out_dir);out.mkdir(parents=True,exist_ok=False)
files=sorted({x for g in a.pass_glob for x in glob.glob(g)});assert files,'no pass artifacts'
if a.phase!='test' and any('.test.' in x for x in files):raise RuntimeError('test input requires explicit --phase test after campaign release')
weights=json.loads((root/'configs/heldout393.json').read_text());stress=json.loads((root/'configs/outside_rectangle_stress257.json').read_text());configs={x.stem:json.loads(x.read_text()) for x in sorted((root/'configs').glob('bounded-*-k3k5.json'))}
records=[];sources={}
for path in files:
 b=pathlib.Path(path).read_bytes();sources[path]=hashlib.sha256(b).hexdigest();x=json.loads(b)
 for r in x['records']:
  q=r['query'];quality=r.get('recommendation_quality') or r.get('quality') or {};fs=quality.get('features',[]);records.append((path,r,quality,fs))
requests=[];keys=[]
for ri,(_,r,quality,fs) in enumerate(records):
 for name,cfg in configs.items():requests.append(json.dumps({'features':fs,'config':cfg},separators=(',',':')));keys.append((ri,name))
proc=subprocess.run([a.probe],input='\n'.join(requests)+'\n',capture_output=True,text=True)
(out/'selectorprobe.stderr.log').write_text(proc.stderr);replies=[json.loads(s) for s in proc.stdout.splitlines()];assert len(replies)==len(keys),(len(replies),len(keys),proc.stderr[-2000:]);replayed={}
for key,result in zip(keys,replies):
 if configs[key[1]]["bounded"].get("exact_when_feasible") and not result.get("config",{}).get("exact_when_feasible"):raise RuntimeError("requested hybrid config is unsupported by this probe; use selectorprobe-hybrid")
 replayed[key]=result

def cost(f,w):return f['duration_seconds']+w['transfer_seconds']*f['metrics']['transfers']+w['extra_walk_weight']*f['metrics']['walking_seconds']
def metric(fs,ids,ws):
 by={f['identity']:f for f in fs};chosen=[by[i] for i in ids if i in by]
 if len(chosen)!=len(ids):raise RuntimeError('selector identity absent from validated pool')
 if not fs:return {'eligible_slots':0,'empty_pool':True,'selected_count':len(chosen)}
 if not chosen:return {'eligible_slots':len(ws),'missing_display':True,'selected_count':0}
 regrets=[];relative=[]
 for w in ws:
  ref=min(cost(f,w) for f in fs);obs=min(cost(f,w) for f in chosen);regrets.append(max(0.,obs-ref));relative.append(max(0.,obs-ref)/(1+ref))
 slacks=[min([v['slack_seconds'] for v in f.get('interchanges',[])],default=None) for f in chosen]
 return {'eligible_slots':len(ws),'selected_count':len(chosen),'patterns':len({f['route_stop_walk_pattern'] for f in chosen}),'exact_slots':sum(r<=1e-7 for r in regrets),'within1scoresecond_slots':sum(r<=1+1e-7 for r in regrets),'worst_absolute':max(regrets),'worst_normalized':max(relative),'sum_absolute':sum(regrets),'sum_normalized':sum(relative),'regrets':regrets,'normalized_regrets':relative,'selected_min_slacks_seconds':slacks}
allrows=[];buckets={}
for ri,(path,r,quality,fs) in enumerate(records):
 candidates={}
 for s in quality.get('selections',[]):
  if s.get('score_envelope_seconds')==300 and s['limit'] in [3,5]:candidates[f'pattern_anchors_v1/k{s["limit"]}']=(s['selected'],None)
 for group in (quality.get('choices') or {}).get('groups',[]):
  for s in group.get('selections',[]):
   if s['method']=='preference_minimax' and s['limit'] in [3,5]:candidates[f'finite20_samegrid_diagnostic/k{s["limit"]}']=(s['selected'],None)
 for name in configs:
  result=replayed[(ri,name)]
  if not result.get('complete'):candidates[f'{name}/incomplete']=([],result)
  else:
   for s in result['selections']:candidates[f'{name}/k{s["limit"]}']=(s['selected'],result)
 for name,(ids,continuous) in candidates.items():
  row={'source':path,'query_id':r['query']['id'],'stratum':r.get('stratum'),'status':r.get('status'),'raw_candidates':len(fs),'policy':name,'selection_complete':continuous is None or continuous.get('complete',False),'heldout393':metric(fs,ids,weights),'outside_rectangle_stress257':metric(fs,ids,stress)}
  if continuous is not None:row['continuous']=continuous
  allrows.append(row)
  for panel in ['heldout393','outside_rectangle_stress257']:
   m=row[panel];b=buckets.setdefault((name,panel),{'rows':0,'empty_rows':0,'incomplete_rows':0,'missing_display_rows':0,'eligible_slots':0,'exact_slots':0,'within1scoresecond_slots':0,'regrets':[],'relative':[],'patterns':[],'selected_counts':[]})
   b['rows']+=1;b['empty_rows']+=bool(m.get('empty_pool'));b['incomplete_rows']+=not row['selection_complete'];b['missing_display_rows']+=bool(m.get('missing_display'));b['eligible_slots']+=m['eligible_slots'];b['exact_slots']+=m.get('exact_slots',0);b['within1scoresecond_slots']+=m.get('within1scoresecond_slots',0);b['regrets']+=m.get('regrets',[]);b['relative']+=m.get('normalized_regrets',[]);b['patterns'].append(m.get('patterns',0));b['selected_counts'].append(m.get('selected_count',0))
   # Raw per-slot arrays remain in separate records, not replicated in summary.
summary={}
for (name,panel),b in buckets.items():
 vals=sorted(b.pop('regrets'));rels=sorted(b.pop('relative'));patterns=b.pop('patterns');counts=b.pop('selected_counts');n=b['eligible_slots'];b.update(exact_coverage=b['exact_slots']/n if n else None,within1scoresecond_coverage=b['within1scoresecond_slots']/n if n else None,max_absolute=max(vals,default=None),p95_absolute=vals[math.ceil(.95*len(vals))-1] if vals else None,mean_absolute=sum(vals)/len(vals) if vals else None,max_normalized=max(rels,default=None),mean_normalized=sum(rels)/len(rels) if rels else None,mean_patterns_per_offered_row=statistics.mean(patterns),mean_selected_per_offered_row=statistics.mean(counts));summary[f'{name}/{panel}']=b
(out/'records.json').write_text(json.dumps(allrows,separators=(',',':'))+'\n');report={'phase':a.phase,'scope':'selection loss relative to each supplied incomplete validated candidate pool, not journey search completeness or authentic rider utility','source_files':sources,'preference_seal':json.loads((root/'PREFERENCE_SEAL.json').read_text()),'configs':configs,'probe_sha256':hashlib.sha256(pathlib.Path(a.probe).read_bytes()).hexdigest(),'offered_rows':len(records),'summary':summary};(out/'SUMMARY.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'offered_rows':len(records),'comparisons':len(allrows),'policies':len(summary),'probe_exit':proc.returncode}))
