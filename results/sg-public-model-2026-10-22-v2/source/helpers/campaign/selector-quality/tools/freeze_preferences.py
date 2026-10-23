#!/usr/bin/env python3
"""Immutable hypothetical preference panels, independent of candidate outcomes."""
import hashlib,json,pathlib
root=pathlib.Path(__file__).resolve().parents[1]
def halton(i,b):
 r=0.;f=1.
 while i:
  f/=b;r+=f*(i%b);i//=b
 return r
interior=[{'id':f'halton_{i:03d}','transfer_seconds':900*halton(i,2),'extra_walk_weight':4*halton(i,3)} for i in range(1,258)]
edges=[]
for i in range(33):
 u=(i+.5)/33
 for t,w,n in [(0,4*u,'left'),(900,4*u,'right'),(900*u,0,'bottom'),(900*u,4,'top')]:edges.append({'id':f'edge_{n}_{i:02d}','transfer_seconds':t,'extra_walk_weight':w})
corners=[{'id':f'corner_{t}_{w}','transfer_seconds':t,'extra_walk_weight':w} for t in [0,900] for w in [0,4]]
full=interior+edges+corners
scalar=[{'transfer_seconds':t,'extra_walk_weight':w} for t,w in [(0,0),(900,0),(0,4),(900,4),(73.125,.375),(241.75,1.125),(463.375,2.625),(691.625,.875),(827.875,3.375)]]
stress=[{'id':f'outer_{i:03d}','transfer_seconds':1800*halton(i,2),'extra_walk_weight':8*halton(i,3)} for i in range(1,258)]
files={'heldout393.json':full,'scalar9.json':scalar,'outside_rectangle_stress257.json':stress};hashes={}
for name,x in files.items():
 p=root/'configs'/name;b=(json.dumps(x,sort_keys=True,indent=2)+'\n').encode()
 if p.exists() and p.read_bytes()!=b:raise RuntimeError('refuse to replace frozen panel')
 p.write_bytes(b);hashes[name]=hashlib.sha256(b).hexdigest()
(root/'PREFERENCE_SEAL.json').write_text(json.dumps({'contract':'hypothetical preference stress, not rider distribution; none generated from new validation/test outputs','generator_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),'files':hashes,'heldout393_counts':{'Halton_base2_base3_indices1_to257':257,'midpoint_boundary_probes33_each_edge':132,'corners':4},'scalar9_predeclared':scalar,'normalization':'(observed_best-reference_best)/(1+reference_best_score_seconds)'},indent=2,sort_keys=True)+'\n')
