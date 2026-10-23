#!/usr/bin/env python3
"""Independent score/pattern arithmetic over existing independently checked records.
Not a new feasibility checker, exact routing oracle, or heldout selection evaluator.
Exposed artifacts may only be diagnostic. No router/search/selector imports.
"""
import argparse, collections, hashlib, json, math, pathlib

def digest(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def vec(j):return (j['duration_seconds'],j['metrics']['transfers'],j['metrics']['walking_seconds'])
def cost(v,t,w):return v[0]+t*v[1]+w*v[2]
def quantile(x,p):
    if not x:return None
    x=sorted(x);return x[max(0,math.ceil(len(x)*p)-1)]
def dist(x):return {'count':len(x),'mean':sum(x)/len(x) if x else None,'p50':quantile(x,.5),'p95':quantile(x,.95),'p99':quantile(x,.99),'max':max(x) if x else None}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pool',required=True);ap.add_argument('--rows',action='append',required=True);ap.add_argument('--out',required=True);ap.add_argument('--evidence',default='exposed-v1-retrospective-diagnostic');a=ap.parse_args()
    pool=json.load(open(a.pool));pools={q['query_id']:[vec(j) for j in q['witnesses']] for q in pool['queries']}
    profiles={'train_grid':[(t,w) for t in [0,150,300,600,900] for w in [0,1,2,4]],'interior_offgrid':[(t,w) for t in [75,225,450,750] for w in [.25,.5,1.5,3]],'out_of_box_stress':[(t,w) for t in [1200,1800] for w in [0,2,6,10]]}
    sums={};byquery=collections.defaultdict(dict);inputfiles=[]
    for p in a.rows:
        inputfiles.append({'path':p,'sha256':digest(p)})
        label=pathlib.Path(p).parent.name
        for line in open(p):
            r=json.loads(line);alg=r['algorithm'];key=label+'::'+alg;qid=r['query_id'];pv=pools[qid]
            acc=sums.setdefault(key,{'algorithm':alg,'source_label':label,'offered':0,'success':0,'empty_pool':0,'eligible':0,'profiles':{},'patterns':{s:[] for s in ['raw','candidates','displayed','displayed_secondary']},'vectors':{s:[] for s in ['raw','candidates','displayed','displayed_secondary']},'available_unique_patterns':[]})
            acc['offered']+=1;acc['success']+=bool(r['success']);acc['empty_pool']+=not pv
            if not pv:continue
            acc['eligible']+=1
            stages={s:[vec(j) for j in js] for s,js in r['stages'].items()}
            byquery[qid][key]={'algorithm':alg,'raw':stages['raw']}
            for s,js in r['stages'].items():
                acc['patterns'][s].append(len({j['pattern'] for j in js}));acc['vectors'][s].append(len({vec(j) for j in js}))
            acc['available_unique_patterns'].append(len({j['pattern'] for j in r['stages']['candidates']}))
            for pn,ps in profiles.items():
                for s,vs in stages.items():
                    m=acc['profiles'].setdefault(pn+'::'+s,{'eligible_slots':0,'missing_slots':0,'exact_covered':0,'within_60_score_seconds':0,'regrets':[]})
                    for t,w in ps:
                        m['eligible_slots']+=1
                        if not vs or not r['success']:
                            m['missing_slots']+=1;continue
                        d=min(cost(v,t,w) for v in vs)-min(cost(v,t,w) for v in pv)
                        if abs(d)<1e-9:d=0
                        assert d>=0,(key,qid,pn,d)
                        m['regrets'].append(d);m['exact_covered']+=d==0;m['within_60_score_seconds']+=d<=60
    for acc in sums.values():
        acc['patterns']={s:dist(xs) for s,xs in acc['patterns'].items()};acc['vectors']={s:dist(xs) for s,xs in acc['vectors'].items()};acc['available_unique_patterns']=dist(acc['available_unique_patterns'])
        for m in acc['profiles'].values():
            m['exact_coverage']=m['exact_covered']/m['eligible_slots'] if m['eligible_slots'] else None;m['within_60_coverage']=m['within_60_score_seconds']/m['eligible_slots'] if m['eligible_slots'] else None;m['regret_observed_only']=dist(m.pop('regrets'))
    # Contributor dependence diagnostics use raw vectors, not a completeness claim.
    family=lambda alg: 'McRAPTOR' if alg.startswith('mc_raptor') else ('RAPTOR' if alg.startswith('raptor') else alg)
    contribution={}
    for qid,rows in byquery.items():
        fams=collections.defaultdict(list)
        for r in rows.values():fams[family(r['algorithm'])]+=r['raw']
        for fam,vs in fams.items():
            other=[v for f,xs in fams.items() if f!=fam for v in xs]
            c=contribution.setdefault(fam,{'eligible_query_profile_slots':0,'no_other_reference_slots':0,'strictly_better_than_other_families':0,'improvement_score_seconds':[]})
            for t,w in profiles['interior_offgrid']:
                c['eligible_query_profile_slots']+=1
                if not other:c['no_other_reference_slots']+=1;continue
                if vs:
                    improvement=min(cost(v,t,w) for v in other)-min(cost(v,t,w) for v in vs)
                    if improvement>0:c['strictly_better_than_other_families']+=1;c['improvement_score_seconds'].append(improvement)
    for c in contribution.values():c['improvement_score_seconds']=dist(c['improvement_score_seconds'])
    out={'schema':'independent-quality-arithmetic-v1','evidence':a.evidence,'script_sha256':digest(__file__),'pool_path':a.pool,'pool_file_sha256':digest(a.pool),'pool_sha256':pool['pool_sha256'],'inputs':inputfiles,'profiles':profiles,'results':sums,'family_contribution_dependence':contribution,'limitations':['Arithmetic reanalysis of retained reconstructed witnesses; does not independently generate paths or certify completeness.','Profiles fixed by audit after v1 exposure. All v1 results are retrospective diagnostics, never untouched holdout or candidate selection evidence.','Exact score coverage and <=60 score-second coverage are not actual passenger preference probabilities or travel-time regret.','Pool empty remains unknown, not automatically reachable or unreachable.','Out-of-box stress is separately labeled and does not change selector contract.']}
    pathlib.Path(a.out).write_text(json.dumps(out,indent=2)+'\n')
    for k,r in sums.items():
        for stage in ['raw','displayed','displayed_secondary']:
            p=r['profiles'].get('interior_offgrid::'+stage,{})
            print(k,stage,r['offered'],r['eligible'],p.get('exact_coverage'),p.get('within_60_coverage'),p.get('regret_observed_only',{}).get('max'))
if __name__=='__main__':main()
