#!/usr/bin/env python3
import hashlib,importlib.util,itertools,json,pathlib,random,subprocess,time
P=pathlib.Path(__file__).parent;s=importlib.util.spec_from_file_location('exact',P/'selector_exact_audit.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
probe='/workspace/shared/sg-coldstart/campaign-v2-20261021/experiments/selectorprobe'
base={'min_transfer_seconds':0,'max_transfer_seconds':900,'min_extra_walk_weight':0,'max_extra_walk_weight':4,'objective':'absolute','limits':[1,3,5],'distinct_patterns':False,'nested':False,'max_critical_points':100000,'max_work':50000000,'exact_subset_search':True}
def run(features,cfg):
 p=subprocess.run([probe],input=json.dumps({'features':features,'config':cfg}),text=True,capture_output=True);return p,json.loads(p.stdout) if p.stdout else None
rng=random.Random(202610211523);records=[];errors=[];start=time.time()
for case in range(12):
 pool=[(rng.randrange(1,3601),rng.randrange(4),rng.randrange(601)) for _ in range(6)];patterns=['pattern%d'%(i%3) for i in range(6)];ids=['id%d'%i for i in range(6)];features=[{'identity':ids[i],'route_stop_walk_pattern':patterns[i],'duration_seconds':v[0],'metrics':{'transfers':v[1],'walking_seconds':v[2]}} for i,v in enumerate(pool)]
 for obj,nested,distinct in itertools.product(['absolute','normalized'],[False,True],[False,True]):
  bc=dict(base,objective=obj,nested=nested,distinct_patterns=distinct);cfg={'max_candidates':1024,'max_subsets':200000,'bounded':bc};p,r=run(features,cfg);record={'case':case,'config':cfg,'features':features,'returncode':p.returncode,'output':r,'checks':[]};records.append(record)
  if p.returncode:errors.append({'case':case,'reason':'unexpected failure','stderr':p.stderr});continue
  forced=set();previous=None
  for out in r['selections']:
   pick={ids.index(x) for x in out['selected']};k=out['limit'];value=m.worst(pool,sorted(pick),normalized=obj=='normalized')['maximum'];best=None
   if nested and not forced<=pick:errors.append({'case':case,'reason':'nesting violation'})
   if distinct and len({patterns[i] for i in pick})!=len(pick):errors.append({'case':case,'reason':'pattern repeat'})
   for size in range(1,min(k,len(pool))+1):
    for inds in itertools.combinations(range(len(pool)),size):
     if nested and not forced<=set(inds):continue
     if distinct and len({patterns[i] for i in inds})!=len(inds):continue
     v=m.worst(pool,inds,normalized=obj=='normalized')['maximum'];best=v if best is None else min(best,v)
   gap=float(value-best);record['checks'].append({'limit':k,'gap':gap,'selected':sorted(pick),'forced':sorted(forced)})
   if gap>(1e-8 if obj=='absolute' else 1e-12):errors.append({'case':case,'reason':'not constrained optimum','gap':gap,'obj':obj})
   if nested:forced=pick
# Budget failures must remain incomplete, never certified selection successes.
f=[{'identity':'a','route_stop_walk_pattern':'a','duration_seconds':1900,'metrics':{'transfers':0,'walking_seconds':300}},{'identity':'b','route_stop_walk_pattern':'b','duration_seconds':1600,'metrics':{'transfers':2,'walking_seconds':0}},{'identity':'c','route_stop_walk_pattern':'c','duration_seconds':2500,'metrics':{'transfers':0,'walking_seconds':0}},{'identity':'r','route_stop_walk_pattern':'r','duration_seconds':1800,'metrics':{'transfers':1,'walking_seconds':100}}]
for name,change in [('candidates',{'max_candidates':1}),('subsets',{'max_subsets':1}),('critical_points',{'bounded':dict(base,max_critical_points=4)}),('work',{'bounded':dict(base,max_work=1)})]:
 cfg={'max_candidates':1024,'max_subsets':200000,'bounded':dict(base)};cfg.update(change);p,r=run(f,cfg);records.append({'guard':name,'config':cfg,'returncode':p.returncode,'output':r,'stderr':p.stderr})
 if p.returncode==0 or r is None or r['complete'] or any(x.get('complete') or x.get('subset_optimal') for x in r.get('selections',[])):errors.append({'guard':name,'reason':'failure misclassified'})
out=P/'selector-constraints-initial';out.mkdir(exist_ok=False)
with (out/'cases.jsonl').open('w') as f:
 for r in records:f.write(json.dumps(r)+'\n')
report={'schema':'independent-selector-constraint-audit-v1','probe_sha256':hashlib.sha256(pathlib.Path(probe).read_bytes()).hexdigest(),'probe_executions':len(records),'constrained_subset_checks':sum(len(r.get('checks',[])) for r in records),'errors':errors,'elapsed_seconds':time.time()-start,'scope':'synthetic exact constrained subset search; nested/distinct and budget classification, not actual route quality'};(out/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
