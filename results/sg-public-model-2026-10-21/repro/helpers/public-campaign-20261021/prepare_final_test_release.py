#!/usr/bin/env python3
"""Prepare a create-only multi-subcampaign public-model test release; never launches routers."""
import argparse,copy,datetime,hashlib,json,pathlib
R=pathlib.Path(__file__).resolve().parents[1];O=R/'public-campaign-20261021';P=O/'resumed-0130'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(pathlib.Path(p).read_text())
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',type=pathlib.Path,required=True);ap.add_argument('--review',type=pathlib.Path,required=True);a=ap.parse_args();a.out=a.out.resolve();a.review=a.review.resolve(strict=True)
 # Validation and independent review are prerequisites, not a data/secrecy proof.
 for c,n in [('full-validation-candidate-slate-v2',44),('full-validation-tb-recovery',4),('csa-native-screen90-validation',16),('csa-native-screen90-validation-anchors',12),('rail-sensitivity-fourwindow-tune',16)]:
  s=load(P/c/'status.json');assert len(s['completed_runs'])==n,(c,s['state'],len(s['completed_runs']));assert s['state']==('runner_error' if n==44 else 'completed'),(c,s['state'])
 review=load(a.review);assert review.get('decision')=='accept_for_bounded_public_model_test_release',review
 evidence=review.get('evidence');assert isinstance(evidence,list) and evidence,'acceptedreviewrequires exactevidencerefs'
 for ref in evidence:
  assert isinstance(ref,dict) and ref.get('path') and ref.get('sha256'),ref
  ep=pathlib.Path(ref['path']);ep=ep if ep.is_absolute() else a.review.parent/ep;assert ep.is_file() and sha(ep)==ref['sha256'],('stalereviewevidence',str(ep))
 required=[P/'FULL_VALIDATION_METRICS.json',P/'FULL_VALIDATION_SOURCE_PARITY.json',P/'FULL_VALIDATION_QUALITY_DEFAULT.json',P/'FULL_VALIDATION_QUALITY_FINITE500000.json',P/'CSA90_VALIDATION_METRICS.json',P/'CSA90_VALIDATION_QUALITY.json',P/'CROSS_PANEL_UNORDERED_PARENT_OD_AUDIT.json',a.review]
 assert all(p.is_file() for p in required)
 assert load(P/'FULL_VALIDATION_SOURCE_PARITY.json')['semantic_mismatch_count']==0
 assert load(P/'CROSS_PANEL_UNORDERED_PARENT_OD_AUDIT.json')['all_tune_validation_vs_test_overlap']==0
 a.out.mkdir(parents=True,exist_ok=False);master=a.out/'FINALIST_RELEASE.json';full=load(P/'full-validation-candidate-slate-v2-plan.json');recovery=load(P/'full-validation-tb-recovery-plan.json');specs=full['runs']+recovery['runs'];entry=load(P/'dense-entrypoint-coverage-tune-plan.json')['runs'];csa=load(P/'csa-native-screen90-validation-plan.json');anchors=load(P/'csa-native-screen90-validation-anchors-plan.json')
 roots={'bench':'routing','bench-raptor-dense-opt':'routing-raptor-dense-opt','bench-walk-eacsa-opt':'routing-walk-eacsa-opt','bench-ultra-capped-opt':'routing-ultra-capped-opt','bench-walk-opt':'routing-walk-opt','bench-csa-opt':'routing-csa-opt'}
 qualification=O/'public-model-qualification/conservative600-qualification.json';entries=[]
 def write_group(name,items,contract,panel):
  plan={k:copy.deepcopy(v) for k,v in full.items() if k not in ('runs','purpose')};plan.update(evaluation_mode='public_model_final_evaluation',dataset_tier='reviewed_public_model_not_latest_official',purpose=contract,data_qualification={'path':str(qualification),'sha256':sha(qualification)},runs=[])
  for w,x in zip(['morning','midday','evening','overnight'],items):
   x=copy.deepcopy(x);x['id']='test-'+w+'-'+name;x['argv']=[v.replace('.full.validation.','.full.test.').replace('.screen.validation.','.screen.test.').replace('.screen.tune.','.full.test.') for v in x['argv']];x['inputs']=[str((R/v).resolve()) if not pathlib.Path(v).is_absolute() else v for v in x['inputs']];x['inputs']=[v.replace('.full.validation.','.full.test.').replace('.screen.validation.','.screen.test.').replace('.screen.tune.','.full.test.') for v in x['inputs']];x['inputs']+=list(dict.fromkeys([str(master),str(P/'CROSS_PANEL_UNORDERED_PARENT_OD_AUDIT.json'),str(a.review.resolve())]));x['source_roots']=[x['cwd'],str(R/roots[pathlib.Path(x['cwd']).name])]
   assert all(pathlib.Path(v).is_absolute() for v in x['inputs'])
   for v in x['inputs']:
    if v!=str(master):assert pathlib.Path(v).is_file(),v
   query=x['argv'][x['argv'].index('-queries')+1];assert f'.{panel}.test.' in query,query
   x['timeout_s']=1800 if panel=='full' else 380;plan['runs'].append(x)
  f=a.out/(name+'-plan.json');f.write_text(json.dumps(plan,indent=2)+'\n');entries.append({'name':name,'plan':{'path':str(f),'sha256':sha(f)},'contract':contract,'panel':panel,'requests_per_window':450 if panel=='full' else 90,'runs':4})
 primary=['raptor-early-baseline','raptor-early-dense','ea-baseline','ea-combined','ultra-control-baseline','ultra-control-dense','ultra-subset-dense','mc-dense-labels500000-finite20','mc-early-dense-labels500000-finite20','trip-based-capped-100m']
 for tail in primary:
  items=[]
  for w in ['morning','midday','evening','overnight']:
   hit=[x for x in specs if x['id']==f'validation-{w}-{tail}'];items.append(hit[-1])
  write_group(tail,items,'Primary full450/window point-router contract; native2D versus3D distinct, same3s/batch1, no test-conditioned change, no global/protocol convergence.','full')
 for tail,alg,binary,cwd in [('raptor-baseline','raptor',str(R/'setup/familybench'),str(R/'bench')),('raptor-dense','raptor',str(O/'raptor-dense-readiness/familybench-raptor-dense'),str(R/'bench-raptor-dense-opt'))]:
  items=[]
  for w in ['morning','midday','evening','overnight']:
   x=copy.deepcopy(next(x for x in specs if x['id']==f'validation-{w}-raptor-early-dense'));x['argv'][0]=binary;x['argv'][x['argv'].index('-algorithm')+1]=alg;x['cwd']=cwd;items.append(x)
  write_group(tail,items,'Primary full450/window ordinary nativeRAPTOR2D; source-differential and two-block tune qualified, ordinary entrypoint not separately full450 validation. Samefrozen source/caps, no test-conditioned tuning.','full')
 for alg in ['csa_arrival_single','csa_score_single','csa_arrival_shared','csa_score_shared']:
  write_group('native90-'+alg,[next(x for x in csa['runs'] if x['id']==f'validation-{w}-{alg}-suffix-labels1000000-batch1') for w in ['morning','midday','evening','overnight']],'Separate native screen90/window: arrival strict identity top-k10 single lane; score boarding-cap0..4 lane union then certified ranking, up to5 k-sized raw lists, maxlabels1m PERLANE. Original3s/batch1; tiny exact-topk oracle qualification, not2D completeness or primary450 qualification. Shared batch1 compatibility only.','screen')
 for tail in ['raptor-early-dense','ultra-control-dense','mc-early-dense-labels500000-finite20']:
  write_group('native90-anchor-'+tail,[next(x for x in anchors['runs'] if x['id']==f'validation90-{w}-{tail}') for w in ['morning','midday','evening','overnight']],'Matched nativeCSA90/window point-router quality anchor, distinctnative2D/3D contracts, alloffered failures retained.','screen')
 release={'schema':'sg_public_model_master_finalist_release_v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'decision':'bounded_best_measured_source_configuration_snapshot_not_convergence','data_tier':'reviewed public-modeled static frequency timetable and conservative600 walking; not official/latest/physicaltruth','formal_baseline_eligible':False,'latest_official_transit_feed':False,'official_source_authenticity_established':False,'test_outcomes_exposed_at_freeze':False,'one_blind_release_policy':'Allsubplans and exactmode-specific seals prepared+validated BEFORE firsttestlaunch; queueall unchanged, no source/config/resource/selection retuning after testexposure. Testfailures remain results.','partition_reason':'Each4window subcampaign has exact4qualified dataset scope. Masterrelease hash bindsallsubplans acrossindividual seals, avoids quadratic wholelargeplan repeatedhashing without weakeningeachsubcampaign exactseal.','entries':entries,'validation_evidence':[{'path':str(p.resolve()),'sha256':sha(p)} for p in required],'source_and_config_selection':'500kMc guard retained from complete180tune and450validation vs1m exact outputagreement, rather than silently increasingbasedtest; finite20 selector same20hypotheticalgrid disclosed. Original controls alongsidecandidates. CappedTB100m actuallinks/prep/RSS explicit.','remaining_space':'No globaloptimum or declared finiteprotocol convergence: morefamilies/indexstructures/resourcefrontiers/independentpreferenceevaluation unexhausted; auxiliaries smallercohorts, unsupported andprepguard rows explicit.'};master.write_text(json.dumps(release,indent=2)+'\n');print(json.dumps({'master_release':str(master),'sha256':sha(master),'subplans':len(entries),'processes':sum(x['runs'] for x in entries),'offered':sum(x['runs']*x['requests_per_window'] for x in entries)},indent=2))
if __name__=='__main__':main()
