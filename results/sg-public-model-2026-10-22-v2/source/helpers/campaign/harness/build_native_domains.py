"""Build metadata-only native fixed-destination/source-domain tune requests.

These are distinct narrow contracts, not arbitrary-OD launch qualification.
No routing result is used. All original offered primary requests remain intact.
"""
import copy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data-workload'
OUT=ROOT/'native-domains'

def read(p):return json.loads(Path(p).read_text())
def write(p,v):
    if p.exists():raise FileExistsError(p)
    p.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ident(p):return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}

def main():
    OUT.mkdir()
    parent={s['stop_id']:s['parent_group'] for s in read(DATA/'plan/stop-metadata.json')['stops']}
    pair=lambda a,b:tuple(sorted((parent.get(a,a),parent.get(b,b))))
    old=read(DATA/'audits/V1_EXPOSURE_LEDGER.json')
    blocked={tuple(x) for x in old['unordered_parent_pairs']}
    blocked.update(tuple(x['unordered_parent_pair']) for x in read(DATA/'plan/planned-workload.json')['clusters'])
    models=read(DATA/'models/MODEL_REGISTRY.json')['models']['phase_hash_a_conservative600']
    entries=[];domains=[]
    for window in sorted(models):
        src=DATA/f'workloads/phase_hash_a_conservative600/{window}.tune.full.primary_1h_walk600.json'
        base=read(src)
        destination=next(x['query']['destination'] for x in base['items'] if x['stratum']=='timetable_constructed_transit_positive')
        items=[]
        for x in base['items']:
            q=copy.deepcopy(x['query']); q['destination']=destination
            key=pair(q['origin'],destination)
            if q['origin']==destination or key in blocked:continue
            blocked.add(key)
            q['id']='native-domain-'+hashlib.sha256((window+'|'+q['origin']+'|'+destination+'|'+str(q['departure'])).encode()).hexdigest()[:20]
            items.append({'stratum':'metadata_fixed_destination_domain', 'query':q})
            if len(items)==12:break
        if len(items)!=12:raise ValueError('insufficient untouched source-domain pairs')
        value={'seed':202610211552,'method':'metadata-only native fixed-destination/source-domain tune12; no routing-outcome selection; not arbitrary OD','dataset_sha256':base['dataset_sha256'],'items':items}
        path=OUT/f'{window}.tune.fixed-destination.json';write(path,value)
        meta={'schema':'native-fixed-domain-metadata-v2','split':'tune','queries_sha256':sha(path),'dataset_sha256':base['dataset_sha256'],'source_primary_workload':ident(src),'domain_destination':destination,'domain_sources':[x['query']['origin'] for x in items],'contract':'fixed destination; optional explicitly retained source domain; same hard caps and rules','selection_uses_routing_outcomes':False,'items':[{'query_id':x['query']['id'],'split':'tune','unordered_parent_pair':list(pair(x['query']['origin'],destination))} for x in items]}
        side=path.with_suffix('.metadata.json');write(side,meta)
        entries.append({'split':'tune','workload':ident(path),'metadata':ident(side)})
        domains.append({'window':window,'destination':destination,'sources':meta['domain_sources'],'workload':ident(path),'dataset':models[window]})
    registry=OUT/'registry.json';write(registry,{'schema':'predeclared-workload-registry-v1','entries':entries,'source_provenance':{'data_origin':'public_modeled','formal_baseline_eligible':False,'latest_official_transit_feed':False}})
    write(OUT/'DOMAINS.json',{'schema':'native-fixed-domain-contracts-v2','built_without_routing_outcomes':True,'excludes_all_v1_and_v2_primary_parent_pairs':True,'domains':domains,'registry':ident(registry),'scope':'12 tune requests/window for explicitly fixed destination and retained source domain; not primary arbitrary OD, not final test'})
    print(json.dumps({'domains':len(domains),'queries':sum(len(x['sources']) for x in domains),'registry':ident(registry)}))

if __name__=='__main__':main()
