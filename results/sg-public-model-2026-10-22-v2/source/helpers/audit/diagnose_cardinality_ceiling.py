#!/usr/bin/env python3
"""OFFLINE DIAGNOSTIC ONLY: guarded best exact-profile coverage with <=k routes.

Not a serving selector, preference-training objective, or exhaustive journey oracle.
Consumes features reconstructed by the independent witness checker, not raw claims.
Never loads/runs a router. Max-work exits retain offered rows and explicit bounds.
"""
import argparse,collections,datetime,hashlib,json,pathlib
from fractions import Fraction

class Limit(Exception):pass
class Budget:
 def __init__(self,maximum):self.maximum=maximum;self.used=0
 def charge(self,n=1):
  if self.used+n>self.maximum:raise Limit()
  self.used+=n

def vector(x):
 metrics=x.get('metrics',x);v=(x['duration_seconds'],metrics['transfers'],metrics['walking_seconds'])
 if any(type(z)is not int or z<0 for z in v):raise ValueError('feature costs must be nonnegative exact integers')
 return v

def maximum_cover(masks,k,max_work=1000000):
 """Exact <=k maximum set coverage unless explicitly guarded. No pattern constraint."""
 if type(k)is not int or k<1 or max_work<0:raise ValueError('invalid cardinality/work bound')
 b=Budget(max_work);masks=sorted(set(masks),key=lambda m:(-m.bit_count(),m));union=0
 for m in masks:union|=m
 best_mask=0;best_ids=[];best_count=0;reduced=[]
 try:
  # With <=k score-coverage only, a subset mask can safely be replaced by its superset.
  # This deliberately does not assert safety for pattern diversity or exact-k identity policy.
  for m in masks:
   dominated=False
   for n in reduced:
    b.charge()
    if m|n==n:dominated=True;break
   if not dominated and m:reduced.append(m)
  suffix=[0]*(len(reduced)+1)
  for i in range(len(reduced)-1,-1,-1):suffix[i]=suffix[i+1]|reduced[i]
  # A deterministic lower bound, never returned as an exact answer after a guard.
  gmask=0;gids=[]
  for _ in range(min(k,len(reduced))):
   pick=None;score=gmask.bit_count()
   for i,m in enumerate(reduced):
    b.charge();count=(gmask|m).bit_count()
    if count>score:pick=i;score=count
   if pick is None:break
   gids.append(pick);gmask|=reduced[pick]
  best_mask=gmask;best_ids=gids[:];best_count=gmask.bit_count()
  def visit(start,slots,covered,chosen):
   nonlocal best_mask,best_ids,best_count
   b.charge();count=covered.bit_count()
   if count>best_count:best_mask,best_ids,best_count=covered,chosen[:],count
   if not slots or start==len(reduced)or(covered|suffix[start]).bit_count()<=best_count:return
   for i in range(start,len(reduced)):
    if best_count==union.bit_count():return
    if (covered|suffix[i]).bit_count()<=best_count:break
    updated=covered|reduced[i]
    if updated==covered:continue
    visit(i+1,slots-1,updated,chosen+[i])
  visit(0,k,0,[])
  complete=True;reason=None
 except Limit:complete=best_count==union.bit_count();reason=None if complete else 'max_work'
 return {'complete':complete,'unknown_reason':reason,'covered_lower_bound':best_count,'covered_upper_bound':best_count if complete else union.bit_count(),'all_native_candidates_covered':union.bit_count(),'selected_mask_values':[reduced[i]for i in best_ids],'work':b.used,'raw_unique_masks':len(masks),'nondominated_masks':len(reduced)}

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def diagnose(pool_file,weights_file,out,limits=(3,),max_work=1000000,max_vectors=1024):
 """Input each JSONL row: dataset_sha256, query_id, common_reference, runs.

 runs[]: id, variant_id, complete (independent), native_final[], display[].
 Every feature: identity,duration_seconds,transfers,walking_seconds (or metrics).
 The supplied manifest must bind the producer's independent reconstruction inputs.
 """
 weights=json.loads(pathlib.Path(weights_file).read_text());weights=weights.get('weights',weights)if isinstance(weights,dict)else weights
 points=[(Fraction(str(w['transfer_seconds'])),Fraction(str(w['extra_walk_weight'])))for w in weights]
 if not points:raise ValueError('empty profile set')
 count=len(points);rows=[];seen=set();work=collections.Counter();cache={}
 with pathlib.Path(pool_file).open()as stream:
  for line in stream:
   x=json.loads(line);key=(x['dataset_sha256'],x.get('query_id')or x['query']['id'])
   if key in seen:raise ValueError('duplicate offered query feature pool')
   seen.add(key);reference=list({vector(z)for z in x['common_reference']});masks={};best=[]
   if reference and len(reference)<=max_vectors:
    for t,w in points:best.append(min(d+b*t+a*w for d,b,a in reference))
   def cover(v):
    if v not in masks:
     d,b,a=v;m=0
     for i,((t,w),opt)in enumerate(zip(points,best)):
      score=d+b*t+a*w
      if score<opt-Fraction(1,10000000)*max(1,abs(opt)):raise ValueError('candidate beats frozen common reference')
      if score-opt<=Fraction(1,10000000)*max(1,abs(opt)):m|=1<<i
     masks[v]=m
    return masks[v]
   seen_runs=set()
   for r in x['runs']:
    if r['id']in seen_runs:raise ValueError('duplicate native run within offered query')
    seen_runs.add(r['id']);vectors=sorted({vector(z)for z in r['native_final']});shown=sorted({vector(z)for z in r['display']});shown_union=0
    if not set(shown)<=set(vectors):raise ValueError('display vector is not in native final candidates')
    if not reference and vectors:raise ValueError('native witnesses missing from common reference pool')
    if reference and len(reference)<=max_vectors:
     for v in shown:shown_union|=cover(v)
    for k in limits:
     base={'dataset_sha256':key[0],'query_id':key[1],'run':r['id'],'variant_id':r['variant_id'],'k':k,'native_independently_complete':r['complete'],'reference_empty_or_unknown':not reference,'eligible':count if reference else 0,'native_distinct_vectors':len(vectors),'actual_display_size':len(r['display']),'actual_display_distinct_vectors':len(shown),'actual_display_covered':shown_union.bit_count()if reference and len(reference)<=max_vectors else None,'scope':'DIAGNOSTIC ONLY, fixed independent reconstructed common-pool and frozen-profile coverage, unconstrained <=k score vectors, not globally optimal journeys or serving selection'}
     if not reference:rows.append({**base,'complete':False,'unknown_reason':'reference_empty_or_unknown'});continue
     if len(reference)>max_vectors:rows.append({**base,'complete':False,'unknown_reason':'max_reference_vectors'});continue
     if len(vectors)>max_vectors:rows.append({**base,'complete':False,'unknown_reason':'max_vectors'});continue
     cmasks=tuple(sorted({cover(v)for v in vectors}));signature=(cmasks,k,max_work)
     if signature not in cache:cache[signature]=maximum_cover(cmasks,k,max_work)
     z=cache[signature].copy();z.pop('selected_mask_values');work[str(k)]+=z['work'];native=z['all_native_candidates_covered'];z.update(route_candidate_gap=count-native,display_cardinality_gap_lower_bound=native-z['covered_upper_bound'],display_cardinality_gap_upper_bound=native-z['covered_lower_bound'],actual_display_to_ceiling_gap_lower_bound=z['covered_lower_bound']-shown_union.bit_count(),actual_display_to_ceiling_gap_upper_bound=z['covered_upper_bound']-shown_union.bit_count())
     # A complete search can diagnose an incomplete native attempt's offered vectors,
     # but it must not turn that attempt into independently completed delivery.
     rows.append({**base,**z})
 result={'schema':'sg-v2-guarded-cardinality-coverage-diagnostic-v1','reviewed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'EXPOSED TUNE DIAGNOSTIC ONLY; do not feed chosen profile masks to serving selectors or tune an objective on heldout393. Ceiling relative to supplied native candidates/common incomplete reference, never global truth.','offered_unique_queries':len(seen),'k_limits':list(limits),'per_pool_search_max_work':max_work,'max_vectors_guard':max_vectors,'work_unit':'one dominance test, greedy mask union or recursive search node; feature scoring is separately finite by vectors×frozen profiles, not included in search work','guard_unknown_rows':sum(not r.get('complete',False)for r in rows),'inputs':{'pool_file':{'path':str(pool_file),'sha256':sha(pool_file)},'weights_file':{'path':str(weights_file),'sha256':sha(weights_file)},'analysis_source_sha256':sha(__file__)},'rows':rows}
 with pathlib.Path(out).open('x')as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--pools',required=True);p.add_argument('--weights',required=True);p.add_argument('--out',required=True);p.add_argument('--limits',default='3');p.add_argument('--max-work',type=int,default=1000000);p.add_argument('--max-vectors',type=int,default=1024);a=p.parse_args();r=diagnose(a.pools,a.weights,a.out,tuple(map(int,a.limits.split(','))),a.max_work,a.max_vectors);print(json.dumps({k:r[k]for k in ['offered_unique_queries','guard_unknown_rows']}))
