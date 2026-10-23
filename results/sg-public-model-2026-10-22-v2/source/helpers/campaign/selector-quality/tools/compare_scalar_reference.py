#!/usr/bin/env python3
"""Compare validated router witnesses/displays to independent scalar optima.

Incomplete reference slots remain offered but cannot define regret. They are not
model-empty, and a router is not penalized for an oracle resource failure.
"""
import argparse,glob,hashlib,json,math,pathlib
p=argparse.ArgumentParser();p.add_argument('--reference-glob',action='append',required=True);p.add_argument('--pass-glob',action='append',required=True);p.add_argument('--out-dir',required=True);a=p.parse_args();out=pathlib.Path(a.out_dir);out.mkdir(parents=True,exist_ok=False)
refs={};hashes={};metadata=[]
for path in sorted({p for g in a.reference_glob for p in glob.glob(g)}):
 b=pathlib.Path(path).read_bytes();hashes[path]=hashlib.sha256(b).hexdigest()
 current_metadata={}
 for s in b.decode().splitlines():
  x=json.loads(s)
  if x.get('kind')=='metadata':metadata.append(x);current_metadata=x;continue
  if x.get('kind')!='scalar_result':continue
  x['_reference_dataset_sha256']=current_metadata['dataset_sha256'];key=(x['query']['id'],x['weight_index']);assert key not in refs,('duplicate offered reference',key);refs[key]=x
rows=[];summaries={}
def score(m,q,w):return m['arrival']-q['departure']+w['transfer_seconds']*m['transfers']+w['extra_walk_weight']*m['walking_seconds']
def distribution(xs):
 xs=sorted(xs);return {'count':len(xs),'max':max(xs,default=None),'p95':xs[math.ceil(.95*len(xs))-1] if xs else None,'mean':sum(xs)/len(xs) if xs else None}
for path in sorted({p for g in a.pass_glob for p in glob.glob(g)}):
 b=pathlib.Path(path).read_bytes();hashes[path]=hashlib.sha256(b).hexdigest();data=json.loads(b);summary_path=pathlib.Path(path).with_name('summary.json');assert summary_path.exists(),f'missing dataset binding summary: {summary_path}';summary_bytes=summary_path.read_bytes();hashes[str(summary_path)]=hashlib.sha256(summary_bytes).hexdigest();dataset_sha=json.loads(summary_bytes)['dataset_sha256'];by={r['query']['id']:r for r in data['records']};policies={'raw'}
 for r in data['records']:
  q=r.get('recommendation_quality') or r.get('quality') or {}
  for s in q.get('selections',[]):
   if s.get('score_envelope_seconds')==300:policies.add(f'pattern_anchor/k{s["limit"]}')
  for g in (q.get('choices') or {}).get('groups',[]):
   for s in g['selections']:
    if s['method']=='preference_minimax':policies.add(f'finite_preferences/k{s["limit"]}')
  for s in (q.get('continuous_choices') or {}).get('selections',[]):policies.add(f'continuous/k{s["limit"]}')
 for policy in sorted(policies):
  summary={'offered_reference_slots':len(refs),'reference_complete_found':0,'reference_complete_empty':0,'reference_inconclusive':0,'candidate_absent':0,'candidate_incomplete':0,'missing_witness_on_reference_found':0,'exact_score_slots':0,'within1scoresecond_slots':0,'negative_regret_contradictions':0,'reference_empty_candidate_found_contradictions':0,'scored_slots':0};regrets=[];relative=[]
  for key,ref in sorted(refs.items()):
   q=ref['query'];w=ref['weight'];rr=ref['result'];r=by.get(q['id']);row={'source':path,'algorithm':data.get('algorithm'),'policy':policy,'query_id':q['id'],'weight_index':key[1],'reference_complete':rr['complete'],'reference_found':rr['found'],'candidate_present':r is not None,'regret':None}
   if not rr['complete']:summary['reference_inconclusive']+=1;row['status']='reference_inconclusive';rows.append(row);continue
   summary['reference_complete_found' if rr['found'] else 'reference_complete_empty']+=1
   if r is None:summary['candidate_absent']+=1;row['status']='candidate_absent';rows.append(row);continue
   if not r.get('completed',r.get('complete',False)):summary['candidate_incomplete']+=1;row['status']='candidate_incomplete';rows.append(row);continue
   if r['query']!=q:raise RuntimeError('query contract mismatch for same ID')
   if dataset_sha!=ref['_reference_dataset_sha256']:raise RuntimeError('dataset byte-hash mismatch between native and independent reference')
   quality=r.get('recommendation_quality') or r.get('quality') or {};features={f['identity']:f for f in quality.get('features',[])};vs=r.get('final',[])
   if policy!='raw':
    ids=None
    if policy.startswith('pattern_anchor'):
     for s in quality.get('selections',[]):
      if s.get('score_envelope_seconds')==300 and s['limit']==int(policy.split('/k')[1]):ids=s['selected']
    elif policy.startswith('finite_preferences'):
     for g in (quality.get('choices') or {}).get('groups',[]):
      for s in g['selections']:
       if s['method']=='preference_minimax' and s['limit']==int(policy.split('/k')[1]):ids=s['selected']
    else:
     choices=quality.get('continuous_choices') or {}
     if choices.get('complete'):
      for s in choices['selections']:
       if s['limit']==int(policy.split('/k')[1]):ids=s['selected']
    if ids is None:summary['candidate_absent']+=1;row['status']='policy_absent';rows.append(row);continue
    vs=[features[i] for i in ids]
   if not rr['found']:
    if vs:summary['reference_empty_candidate_found_contradictions']+=1;row['status']='reference_empty_counterexample'
    else:row['status']='independent_empty_agreement'
    rows.append(row);continue
   if not vs:summary['missing_witness_on_reference_found']+=1;row['status']='missing_witness';rows.append(row);continue
   observed=min(score(v['metrics'],q,w) for v in vs);regret=observed-rr['score_seconds'];row.update(reference_score=rr['score_seconds'],observed_score=observed,regret=regret,normalized_regret=regret/(1+rr['score_seconds']));summary['scored_slots']+=1
   if regret < -1e-7:summary['negative_regret_contradictions']+=1;row['status']='independent_optimum_contradiction'
   else:row['status']='scored';regret=max(0.,regret);regrets.append(regret);relative.append(regret/(1+rr['score_seconds']));summary['exact_score_slots']+=regret<=1e-7;summary['within1scoresecond_slots']+=regret<=1+1e-7
   rows.append(row)
  n=summary['reference_complete_found'];summary.update(exact_coverage_over_all_reference_found=summary['exact_score_slots']/n if n else None,within1scoresecond_coverage_over_all_reference_found=summary['within1scoresecond_slots']/n if n else None,absolute_regret=distribution(regrets),normalized_regret=distribution(relative));summaries[f'{path}::{policy}']=summary
(out/'ROWS.json').write_text(json.dumps(rows,separators=(',',':'))+'\n');report={'scope':'independent finite-input scalar weighted optimum evidence only; not exhaustive 3D frontier or rider population utility','source_hashes':hashes,'reference_metadata':metadata,'reference_offered_slots':len(refs),'summary':summaries};(out/'SUMMARY.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');print(json.dumps({'reference_slots':len(refs),'comparisons':len(rows),'policies':len(summaries)}))
