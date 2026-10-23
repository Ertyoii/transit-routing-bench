#!/usr/bin/env python3
"""V3 actual ALL8/prior4 metadata compatibility ONLY; never launches/archives."""
import argparse
import json
from pathlib import Path
import post_stage as w

def boundary_metadata(s,next_index,*,ready_path=w.READY,ready_sha=w.READY_SHA,work=w.WORK,lock=w.LOCK):
    """Read-only ALL8 + successful immutable-prior boundary proof; no raw opens."""
    w.require(1<=next_index<8,'Resume boundary must precede an exact remaining stage')
    with s.quiet(lock):
        contexts=[w.stage_context(s,i,ready_path,ready_sha) for i in range(8)]
        ready=contexts[0][0];ready_ref=w.identity(s,ready_path)
        ids=[r['id'] for r in ready['all672_state_rows']]
        w.require(len(ids)==len(set(ids))==672,'Global672 ID uniqueness failure')
        block_cells=[]
        for block in range(2):
            block_ids=ids[block*336:(block+1)*336]
            prefix='b%d-'%block
            w.require(all(rid.startswith(prefix) for rid in block_ids),'Frozen block ID prefix mismatch')
            block_cells.append([rid[len(prefix):] for rid in block_ids])
        w.require(block_cells[1]==list(reversed(block_cells[0])),'Frozen all672 global block-reverse order mismatch')
        prior=[];all8=[]
        for index,context in enumerate(contexts):
            _,stage,plan,admission,inventory,root,by_run=context
            all8.append({'stage_index':index,'block':stage['block'],'segment':stage['segment'],
                'plan_block_relative_start':plan['runtime_stage']['global_start_position'],
                'absolute_ledger_start':index*84,'plan':stage['plan'],'freeze':stage['freeze'],
                'prospective_specs':stage['prospective_specs'],'storage_request':stage['request'],
                'storage_admission':stage['storage_admission'],'storage_inventory':stage['storage_inventory']})
            label='b%d-s%d'%(stage['block'],stage['segment'])
            if index<next_index:
                path=work/label/'STAGE_STORAGE_REPORT.json';report=s.read_doc(path)[0]
                ledger=w.bound(s,report['offered_ledger']);global_doc=w.bound(s,report['global_ledger_snapshot'])
                w.validate_prior_ancestry(report,ledger,global_doc,index,ready,ready_ref)
                status_ref,terminal,observations=w.terminal_metadata(s,index,ready,stage,plan,root,by_run)
                records={rid:{'parsed_result':result['document'],'command':command,'memory_admission':memory}
                         for rid,(command,result,memory) in observations.items()}
                w.require(w.success_records(status_ref['document'],plan,records),'Prior actual metadata is not exact successful complete offer set')
                w.require({k:v for k,v in status_ref.items() if k!='document'}==report['terminal_status'],
                          'Prior actual terminal status changed since immutable report')
                for operation in report['operations']:
                    receipt=w.bound(s,operation['retirement_receipt'])
                    w.require(receipt.get('state')=='raw-retired-recoverably'
                              and receipt['raw_path']==operation['raw_path'] and not s.exists(Path(operation['raw_path'])),
                              'Prior exact raw-retirement state mismatch')
                prior.append({'stage_index':index,'report':w.identity(s,path),'offered_ledger':report['offered_ledger'],
                    'global_ledger_snapshot':report['global_ledger_snapshot'],'terminal_status':report['terminal_status'],
                    'original_runner_tick_raw':terminal['runner_start_ticks'],'metadata_offers_checked':len(observations)})
            else:
                s.absent(root);s.absent(work/label)
                for name in ('LAUNCH_INTENT-','LAUNCH-','LAUNCH_OUTCOME-'):
                    suffix='.log' if name=='LAUNCH-' else '.json'
                    s.absent(work/(name+label+suffix))
                for entries in by_run.values():
                    for entry in entries:
                        for value in s.declared_paths(entry):s.absent(Path(value))
        return {'schema':'runtime-v3-all8-boundary-metadata-v1','status':'ALL8_AND_PRIOR_BOUNDARY_INPUT_ONLY_PASS',
            'next_stage_index':next_index,'ready_receipt':ready_ref,'state_root':str(work),
            'all8_stage_bindings':all8,'prior_successful_stages':prior,'absolute_global672_order_preserved':True,
            'block1_exact_global_reverse_preserved':True,'raw_contents_opened_or_hashed':False,
            'archive_retirement_or_launch_performed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-opened-post-stage-quiet-slot',action='store_true')
    parser.add_argument('--next-stage-index',type=int,default=4)
    args=parser.parse_args()
    w.require(args.owner_opened_post_stage_quiet_slot,'Explicit owner post-stage quiet slot required')
    s=w.load_helper()
    result=boundary_metadata(s,args.next_stage_index)
    with s.quiet():
        root=Path(__file__).resolve().parent
        output=root/'ACTUAL_ALL8_PRIOR4_INPUT_COMPATIBILITY_ATTEMPT01.json'
        s.write_doc(output,result)
        print(json.dumps({'status':result['status'],'receipt':w.identity(s,output),
            'all8_stages':len(result['all8_stage_bindings']),'prior_stages':len(result['prior_successful_stages'])},sort_keys=True))

if __name__=='__main__':main()
