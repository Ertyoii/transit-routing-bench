#!/usr/bin/env python3
"""Exact rational independent selector audit using lower-envelope polygon clipping.
Not production selector code. Maxima of affine/positive linear-fractional functions
on each selected lower-envelope cell occur at cell vertices. Split by selected
minimum only, then maximize across every pool reference independently. This uses
neither worker floating critical-vertex generation nor router/selector imports.
"""
from fractions import Fraction as F
import argparse,itertools,json,random,unittest

def cost(v,x,y):return F(v[0])+F(v[1])*x+F(v[2])*y

def clean(poly):
    out=[]
    for p in poly:
        if not out or p!=out[-1]:out.append(p)
    if len(out)>1 and out[0]==out[-1]:out.pop()
    return out

def clip(poly,a,b,c):
    if not poly:return []
    out=[]
    signed=lambda p:a*p[0]+b*p[1]+c
    prev=poly[-1];fp=signed(prev)
    for cur in poly:
        fc=signed(cur)
        if (fc<=0)!=(fp<=0):
            u=fp/(fp-fc)
            out.append((prev[0]+u*(cur[0]-prev[0]),prev[1]+u*(cur[1]-prev[1])))
        if fc<=0:out.append(cur)
        prev,fp=cur,fc
    return clean(out)

def worst(pool,selected,box=(0,900,0,4),normalized=False):
    if not pool:return None
    if not selected:return {'missing':True}
    xmin,xmax,ymin,ymax=map(F,box)
    assert xmin<=xmax and ymin<=ymax
    assert all(v[0]>=0 and v[1]>=0 and v[2]>=0 for v in pool)
    maximum=F(0);at=None;ref=None;cell=None;vertices=set()
    for sid in selected:
        s=pool[sid]
        poly=clean([(xmin,ymin),(xmax,ymin),(xmax,ymax),(xmin,ymax)])
        for oid in selected:
            o=pool[oid]
            poly=clip(poly,F(s[1]-o[1]),F(s[2]-o[2]),F(s[0]-o[0]))
        for x,y in poly:
            vertices.add((x,y))
            actual=min(cost(pool[i],x,y) for i in selected)-min(cost(v,x,y) for v in pool)
            actual=actual/(1+min(cost(v,x,y) for v in pool)) if normalized else actual
            if at is None or actual>maximum:
                maximum,at,cell=actual,(x,y),sid
                ref=min(range(len(pool)),key=lambda i:cost(pool[i],x,y))
    assert at is not None
    return {'maximum':maximum,'at':at,'reference':ref,'selected_cell':cell,'vertices':len(vertices)}

def exhaustive(pool,k,box=(0,900,0,4),normalized=False):
    best=None
    for size in range(1,min(k,len(pool))+1):
        for ids in itertools.combinations(range(len(pool)),size):
            r=worst(pool,ids,box,normalized)
            key=(r['maximum'],len(ids),ids)
            if best is None or key<best[0]:best=(key,r)
    return {'selected':best[0][2],'objective':best[1]} if best else None

def encode(v):
    if isinstance(v,F):return {'numerator':v.numerator,'denominator':v.denominator,'float':float(v)}
    if isinstance(v,dict):return {k:encode(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [encode(x) for x in v]
    return v

class Tests(unittest.TestCase):
    def test_interior_triple_not_corners(self):
        p=[(1900,0,300),(1600,2,0),(2500,0,0),(1800,1,100)]
        for x,y in [(0,0),(900,0),(0,4),(900,4)]:self.assertEqual(min(cost(v,F(x),F(y)) for v in p[:3])-min(cost(v,F(x),F(y)) for v in p),0)
        r=worst(p,[0,1,2]);self.assertEqual(r['maximum'],50);self.assertEqual(r['at'],(450,2))
    def test_equal_vector_and_subset(self):
        p=[(10,1,2),(10,1,2),(20,2,3)]
        self.assertEqual(worst(p,[0])['maximum'],0)
        self.assertEqual(exhaustive(p,3)['selected'],(0,))
    def test_degenerate_boxes(self):
        p=[(100,1,0),(50,2,0),(20,3,1)]
        for box in [(0,0,0,4),(0,900,0,0),(75,75,2,2)]:
            r=worst(p,[0,1],box);self.assertIsNotNone(r);self.assertGreaterEqual(r['maximum'],0)
    def test_normalized_smoothing_zero(self):
        p=[(0,0,0),(1,0,0)];self.assertEqual(worst(p,[1],normalized=True)['maximum'],1)
    def test_random_dense_lower_bound(self):
        rng=random.Random(20261021)
        for _ in range(60):
            p=[(rng.randrange(0,300),rng.randrange(4),rng.randrange(100)) for _ in range(6)]
            ids=sorted(rng.sample(range(6),3))
            for normalized in [False,True]:
                bound=worst(p,ids,normalized=normalized)['maximum']
                for t in range(0,901,45):
                    for w in [F(i,5) for i in range(21)]:
                        opt=min(cost(v,F(t),w) for v in p);d=min(cost(p[i],F(t),w) for i in ids)-opt
                        if normalized:d/=1+opt
                        self.assertLessEqual(d,bound)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input');ap.add_argument('--output');ap.add_argument('--selftest',action='store_true');a=ap.parse_args()
    if a.selftest:
        unittest.main(argv=['selector_exact_audit'],exit=False);return
    d=json.load(open(a.input));pool=[tuple(map(F,v)) for v in d['pool']];box=tuple(map(F,d.get('box',[0,900,0,4])))
    out={'schema':'selector-rational-audit-v1','method':'exact rational selected-envelope cell polygon clipping; no production geometry imports','additive':worst(pool,d['selected'],box),'normalized_regret_over_one_plus_pool_score':worst(pool,d['selected'],box,True)}
    if d.get('exhaustive_k'):
        assert len(pool)<=14,'independent exhaustive audit limited to14candidates'
        out['exhaustive_additive']=exhaustive(pool,d['exhaustive_k'],box)
        out['exhaustive_normalized']=exhaustive(pool,d['exhaustive_k'],box,True)
    text=json.dumps(encode(out),indent=2)+'\n'
    if a.output:open(a.output,'w').write(text)
    else:print(text,end='')
if __name__=='__main__':main()
