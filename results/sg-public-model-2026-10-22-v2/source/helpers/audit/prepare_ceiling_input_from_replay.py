#!/usr/bin/env python3
"""Join only reconstruction-bound replay features, preserving native/reference split.
Never reroutes or loads a model. Output is diagnostic input, not a serving artifact.
"""
import argparse,collections,hashlib,json,pathlib
A=pathlib.Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(pathlib.Path(p).read_text())
def lines(p):
 with pathlib.Path(p).open()as f:
  for s in f:yield json.loads(s)
def sem(identity):return json.dumps(json.loads(identity),sort_keys=True,separators=(',',':'),ensure_ascii=False)
def require(ok,reason):
 if not ok:raise ValueError(reason)

def prepare(replay,out):
 replay=pathlib.Path(replay);manifest=read(replay/'MANIFEST.json');prior=read(A/'ACTUAL_TUNE_RECEIPT_SOURCE_SEAL_AUDIT.json');evaluation=pathlib.Path(manifest['prepared_from_authoritative_evaluator']);quality=evaluation/'QUALITY_ROWS.jsonl'
 require(manifest['authoritative_quality_rows_sha256']==prior['inputs'][str(quality)]==sha(quality),'replay is not bound to accepted actual tune quality rows')
 for name,digest in manifest['outputs'].items():require(sha(replay/name)==digest,'replay output digest mismatch '+name)
 for path,digest in manifest['inputs'].items():require(sha(path)==digest,'replay input changed '+path)
 require(manifest['candidate_rows']==11520 and manifest['authoritative_errors']==0 and manifest['authoritative_native_counterexamples']==0,'initial tune replay scope differs')
 candidates={}
 for p in lines(replay/'CANDIDATE_POOLS.jsonl'):
  require(p['role']=='native_final_before_selection','candidate role is not native final');key=p['candidate_pool_id'];require(key not in candidates,'duplicate native pool ID');candidates[key]=p
 members={}
 for m in lines(replay/'POOL_MEMBERS.jsonl'):
  key=(m['dataset_sha256'],m['query_id'],sem(m['identity']));require(key not in members,'duplicate common witness member');members[key]=m['feature']
 refs={}
 for r in lines(replay/'REFERENCE_POOLS.jsonl'):
  key=(r['dataset_sha256'],r['query_id']);require(key not in refs,'duplicate common reference query');refs[key]=[members[(*key,sem(i))]for i in r['common_semantic_ids']]
 groups={key:{'dataset_sha256':key[0],'query_id':key[1],'common_reference':features,'runs':[]}for key,features in refs.items()};seen=set()
 for r in lines(replay/'CANDIDATE_ROWS.jsonl'):
  qid=r['query']['id'];key=(r['dataset_sha256'],qid);runkey=(r['run'],key);require(runkey not in seen,'duplicate offered run/query');seen.add(runkey);pool=candidates[r['candidate_pool_id']];require((pool['dataset_sha256'],pool['query_id'])==key and r['run']in pool['native_runs'],'native candidate pool/query/run association');require(type(r['independent_complete'])is bool,'independent outcome type');features=pool['features'];native={sem(f['identity']):f for f in features};require(len(native)==len(features),'duplicate native feature identity')
  for feature in features:require((*key,sem(feature['identity']))in members,'native feature absent from common member set')
  top3=[s for s in r['original_selections']if s['limit']==3]
  chosen=None
  for policy in ['bounded_continuous_regret_v3','finite_preferences_v2','pattern_anchors_v1']:
   selections=[s for s in top3 if s['policy']==policy]
   if selections:chosen=selections[0];break
  if chosen is None:
   require(not r['independent_complete']or not features,'missing complete top3 serving selection');display=[]
  else:
   require(not r['independent_complete']or chosen['selection_complete'],'incomplete serving selection on accepted row');display=[native[sem(i)]for i in chosen['selected_replay_ids']]
  require(len(display)<=3,'top3 serving cardinality');groups[key]['runs'].append({'id':r['run'],'variant_id':r['variant_id'],'complete':r['independent_complete'],'native_final':features,'display':display,'source_pass':r['source_pass']})
 require(len(seen)==11520 and len(groups)==240 and all(len(r['runs'])==48 for r in groups.values()),'all240 offers ×24 variants ×2 blocks retained')
 out=pathlib.Path(out)
 with out.open('x')as f:
  for key,r in sorted(groups.items()):f.write(json.dumps(r,sort_keys=True,separators=(',',':'))+'\n')
 receipt={'schema':'sg-v2-ceiling-input-native-reference-join-v1','scope':'All initial tune offered rows; independently reconstructed native final pools are never enlarged by common raw/final/oracle reference donors. Original top3 serving selections are retained, not rerun.','offered_unique_queries':len(groups),'offered_run_rows':len(seen),'inputs':{'replay_manifest':{'path':str(replay/'MANIFEST.json'),'sha256':sha(replay/'MANIFEST.json')},'prior_actual_audit':{'path':str(A/'ACTUAL_TUNE_RECEIPT_SOURCE_SEAL_AUDIT.json'),'sha256':sha(A/'ACTUAL_TUNE_RECEIPT_SOURCE_SEAL_AUDIT.json')},'adapter_source_sha256':sha(__file__)},'output':{'path':str(out),'sha256':sha(out)}}
 out.with_suffix('.manifest.json').write_text(json.dumps(receipt,indent=2)+'\n');return receipt
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--replay',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(prepare(a.replay,a.out),indent=2))
