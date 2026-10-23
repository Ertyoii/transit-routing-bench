"""Build immutable v2 point run plans from source/config definitions and registry.
The output contains exact randomized order before execution; no routing occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path
from order import balanced_order
ROOT=Path(__file__).resolve().parents[1]

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def identity(p):return {'path':str(p),'sha256':sha(p)}

def build(variants,split,model,windows,blocks,seed,panel='full'):
    data=ROOT/'data-workload'
    models=read(data/'models/MODEL_REGISTRY.json')['models'][model]
    registry=data/f'workloads/{model}/registry.json'
    all_windows=sorted(models)
    windows=all_windows if not windows else [w for w in all_windows if any(k in w for k in windows)]
    cells=[{'id':f'{w}-{v["id"]}','window':w,'variant':v} for w in windows for v in variants]
    order=balanced_order(cells,seed,blocks)
    runs=[]
    for item in order['order']:
        v=item['cell']['variant'];w=item['cell']['window']
        query=data/f'workloads/{model}/{w}.{split}.{panel}.primary_1h_walk600.json'
        argv=[v['binary'],'-algorithm',v['algorithm'],'-dataset',models[w]['path'],'-queries',str(query),'-batch-size','1','-batch-timeout','3s','-prep-timeout',v.get('prep_timeout','180s'),'-warmups','0','-repetitions','1','-rss-safety-stop','7000000000','-stream-responses']
        if v.get('quality',True):argv+=['-quality']
        if v.get('preferences'):argv+=['-preference-scenarios',v['preferences']]
        if v.get('scoped_config'):argv+=['-scoped-config',v['scoped_config']]
        if v.get('max_labels'):argv+=['-max-labels',str(v['max_labels'])]
        if v.get('max_transfers'):argv+=['-max-transfers',str(v['max_transfers'])]
        argv+=v.get('extra_argv',[])
        argv+=['-out-dir','{run_dir}/artifact']
        runs.append({'id':f'b{item["block"]}-{item["cell"]["id"]}','block':item['block'],'position':item['position'],'variant_id':v['id'],'window':w,'argv':argv,'cwd':v['source_root'],'source_roots':[v['source_root']],'timeout_s':v.get('timeout_s',600),'rss_safety_stop_bytes':7000000000,'env':v.get('env',{}),'inputs':[str(query.with_suffix('.metadata.json')),str(ROOT/'protocol/PROTOCOL_DRAFT.md'),str(data/'audits/TEST_REQUEST_BYTES_SEAL.json')]})
    return {'schema':'sg-coldstart-campaign-v2','evaluation_mode':'public_model_final_evaluation' if split=='test' else 'diagnostic','dataset_tier':'public_modeled_pipeline_validation','purpose':'Bounded non-CSA native point serving, all offered rows retained; explicit contracts, fixed quality and two reverse-balanced randomized process blocks; no outcome-conditioned order/filtering.','continue_on_failure':True,'workload_registry':identity(registry),'order':order,'variants':variants,'runs':runs}

def main():
    p=argparse.ArgumentParser();p.add_argument('--variants',required=True);p.add_argument('--split',choices=['tune','validation','test'],required=True);p.add_argument('--model',default='phase_hash_a_conservative600');p.add_argument('--windows',nargs='*');p.add_argument('--blocks',type=int,default=2);p.add_argument('--seed',type=int,required=True);p.add_argument('--panel',choices=['full','reference'],default='full');p.add_argument('--out',required=True);a=p.parse_args()
    value=build(read(a.variants),a.split,a.model,a.windows,a.blocks,a.seed,a.panel)
    with Path(a.out).open('x') as f:json.dump(value,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'path':a.out,'sha256':sha(a.out),'runs':len(value['runs']),'blocks':a.blocks,'order_sha256':value['order']['order_sha256']}))
if __name__=='__main__':main()
