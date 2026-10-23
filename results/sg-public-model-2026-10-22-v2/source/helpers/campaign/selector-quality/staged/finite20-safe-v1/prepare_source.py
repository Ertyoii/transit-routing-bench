#!/usr/bin/env python3
"""UNEXECUTED preparer: run only after proposal acceptance and a quiet CPU slot."""
import argparse,hashlib,json,shutil,os
from apply_integration import integrate
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def source_hash(root):
 paths=[]
 for directory,dirs,files in os.walk(root):
  dirs[:]=[d for d in dirs if d not in ('.git','.cache','artifacts')]
  for name in files:
   path=Path(directory)/name;rel=path.relative_to(root).as_posix()
   if name.endswith('.go') or name in ('go.mod','routing.lock.json') or rel=='vendor/modules.txt':paths.append((rel,path))
 h=hashlib.sha256()
 for rel,path in sorted(paths):
  raw=path.read_bytes();h.update(('%d:%s:%d:'%(len(rel.encode()),rel,len(raw))).encode());h.update(raw)
 if not paths:raise ValueError('no Go source')
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--out-root',required=True,type=Path);p.add_argument('--expected-source-sha256',required=True);p.add_argument('--base-receipt',required=True,type=Path);p.add_argument('--include-fill',action='store_true');a=p.parse_args();src=a.source_root.resolve();out=a.out_root.resolve()
 receipt=json.loads(a.base_receipt.read_text());actual=source_hash(src)
 assert actual==a.expected_source_sha256==receipt['source_hash'],'qualified common bench source hash mismatch'
 assert Path(receipt['bench']).resolve()==src,'qualified common bench path mismatch'
 assert src!=out and not out.exists(),'create-only isolated tree required'
 rec=Path('vendor/github.com/ertyoii/transit-routing-go/recommend');before={x.name:sha(x) for x in sorted((src/rec).glob('*.go'))}
 shutil.copytree(src,out,ignore=shutil.ignore_patterns('.git','.cache','artifacts'))
 for name in ['finite_safe.go','finite_safe_test.go','finite_safe_evaluate.go']:shutil.copyfile(HERE/name,out/rec/name)
 (out/'cmd/finitesafeprobe').mkdir();shutil.copyfile(HERE/'main.go',out/'cmd/finitesafeprobe/main.go')
 fill=HERE.parent/'absolute-hybrid-fill-v1'
 if a.include_fill:
  for name in ['hybrid_fill.go','hybrid_fill_evaluate.go','hybrid_fill_test.go']:shutil.copyfile(fill/name,out/rec/name)
  (out/'cmd/hybridfillprobe').mkdir();shutil.copyfile(fill/'main.go',out/'cmd/hybridfillprobe/main.go')
 (out/'regression').mkdir(exist_ok=True);shutil.copyfile(HERE/'finite_safe_lean_test.go',out/'regression/finite_safe_lean_test.go')
 if a.include_fill:shutil.copyfile(fill/'hybrid_fill_lean_test.go',out/'regression/hybrid_fill_lean_test.go')
 assert all(sha(out/rec/name)==h for name,h in before.items()),'frozen recommend source modified before declared additive integration'
 integrate(out,a.include_fill)
 lockpath=out/'routing.lock.json';lock=json.loads(lockpath.read_text());vend=out/'vendor/github.com/ertyoii/transit-routing-go';lock['files']={x.relative_to(vend).as_posix():sha(x) for x in sorted(vend.rglob('*')) if x.is_file()};lock['source_sha256']=hashlib.sha256(json.dumps(lock['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest();lock['origin']+=' Additive finite20-safe V1 offline feature probe only, not serving qualification.';lockpath.write_text(json.dumps(lock,sort_keys=True,indent=2)+'\n')
 baseline=ROOT/'selector-quality/configs/finite20-lean-delivery-top3.json';domain=ROOT/'selector-quality/configs/bounded-absolute-delivery-top3.json';frozen=json.loads(baseline.read_text());base=json.loads(domain.read_text())['bounded'];base['exact_subset_search']=True;base.pop('exact_when_feasible',None)
 matrix=[]
 for objective in ['absolute','normalized']:
  cfg={'baseline':frozen,'domain':dict(base,objective=objective),'max_candidates':64,'max_total_subset_states':200000};serving={'max_candidates':64,'max_subsets':200000,'lean_delivery':True,'delivery_policy':'finite20_safe_v1','delivery_limits':[3],'finite20_safe':cfg};matrix.append({'id':'finite20_safe_'+objective+'_exact_v1','feature_config':cfg,'config':serving})
 fillmatrix=[]
 for k in ([3,5] if a.include_fill else []):
  basecfg=json.loads(domain.read_text());basecfg['bounded']['limits']=[k];basecfg['bounded']['objective']='absolute';basecfg['bounded']['exact_subset_search']=False;basecfg['bounded']['exact_when_feasible']=True
  finite=json.loads(baseline.read_text());finite['delivery_limits']=[k]
  cfg={'base':basecfg,'finite20':finite,'max_fill_subsets':200000,'max_fill_work':20000000,'max_fill_matrix_bytes':8388608}
  serving={'max_candidates':1024,'max_subsets':200000,'lean_delivery':True,'delivery_policy':'bounded_absolute_hybrid_fill_v1','delivery_limits':[k],'absolute_hybrid_fill':cfg}
  fillmatrix.append({'id':'bounded_absolute_hybrid_fill_v1_top%d'%k,'policy':'bounded_absolute_hybrid_fill_v1','limit':k,'feature_config':cfg,'config':serving})
 (out/'HYBRID_FILL_MATRIX.json').write_text(json.dumps({'schema':'sg-one-absolute-hybrid-fill-preregistration-v1','policies':fillmatrix,'algorithm_variants':1,'display_budgets':[3,5],'priority':'historical finite20,pattern envelope300,default Feature less order; never remove base IDs','no393_optimizer_inputs':True},sort_keys=True,indent=2)+'\n')
 (out/'FINITE_SAFE_MATRIX.json').write_text(json.dumps({'schema':'sg-finite20-safe-preregistration-v1','policies':matrix,'exposure':'393 and stress are exposed tune diagnostics, never optimizer inputs; no untouched preference-generalization claim','serving_contract':'offline feature-only exact top3; not serving integration or timing'},sort_keys=True,indent=2)+'\n')
 origin={'source_root':str(src),'composition_scope':'two_safe_plus_one_fill' if a.include_fill else 'safe_only_A_no_fill_source','qualified_common_source_sha256':actual,'qualified_common_receipt_sha256':sha(a.base_receipt),'unchanged_native_routing_basis':receipt['source'],'original_recommend_file_hashes':before,'declared_integration_edits':['recommend/choices.go optional named config and dispatch','recommend/quality.go optional result field','familybench/main.go explicit shared-checker/no-recovery constructor condition'],'unchanged_recommend_files':{name:h for name,h in before.items() if name not in ['choices.go','quality.go']},'baseline_config_sha256':sha(baseline),'domain_config_sha256':sha(domain),'proposal_sha256':sha(HERE/'PROPOSAL.md'),'staged_files':{x.name:sha(x) for x in sorted(HERE.iterdir()) if x.is_file()},'policy_matrix_sha256':sha(out/'FINITE_SAFE_MATRIX.json'),'hybrid_fill_matrix_sha256':sha(out/'HYBRID_FILL_MATRIX.json'),'hybrid_fill_lineage':{'separate_named_policy':'bounded_absolute_hybrid_fill_v1','staged_files':{x.name:sha(x) for x in sorted(fill.iterdir()) if x.is_file()},'base_is_unchanged_absolute_resource_hybrid':True,'fill_profiles_unchanged_historical20':True},'qualification_status':'unqualified: source preparation only'}
 (out/'FINITE_SAFE_ORIGIN.json').write_text(json.dumps(origin,sort_keys=True,indent=2)+'\n');print(json.dumps(origin))
if __name__=='__main__':main()
