#!/usr/bin/env python3
"""Finite all8 conductor: preserve terminal stage, launch next EXACT READY argv.

This is owner-gated operational orchestration, never a retry or routing policy.
While a measurement child runs the conductor ONLY waits. No hashing/analysis.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import post_stage as w


def qualify(s, receipt_path, lock):
    with s.quiet(lock):
        receipt = s.read_doc(receipt_path)[0]
        w.require(receipt.get('status') == 'SYNTHETIC_QUALIFICATION_PASS', 'Workflow is not qualified')
        w.require(receipt.get('storage_helper_sha256') == w.HELPER_SHA, 'Wrong storage qualification')
        w.require(receipt.get('owner_opened_quiet_slot') is True, 'Qualification lacks owner quiet-slot confirmation')
        for name in ('post_stage.py','test_post_stage.py','conductor.py','test_conductor.py','test_coordinates.py','check_all8_boundary.py'):
            actual = w.identity(s, Path(__file__).resolve().parent / name)
            w.require(actual['sha256'] == receipt['files'][name]['sha256'], 'Qualified workflow changed: '+name)
        return w.identity(s,receipt_path)


def exact_launch(s, index, *, ready_path=w.READY, ready_sha=w.READY_SHA, work=w.WORK, lock=w.LOCK,
                 runner=subprocess.run):
    with s.quiet(lock):
        ready, stage, plan, admission, inventory, root, by_run = w.stage_context(s,index,ready_path,ready_sha)
        s.absent(root)
        # Existing prospective request/admission/inventory are checked above;
        # no raw destination or output root is created here before admission.
        for entries in by_run.values():
            for entry in entries:
                for name in s.declared_paths(entry):
                    s.absent(Path(name))
        free=shutil.disk_usage(root.parent).free
        w.require(free >= stage['required_free_bytes_before_stage'], 'Actual disk below exact frozen stage forecast')
        argv=stage['launch_argv']
        w.require(isinstance(argv,list) and all(isinstance(v,str) for v in argv), 'Invalid frozen launch argv')
        w.require(argv.count('--plan')==1 and argv[argv.index('--plan')+1]==stage['plan']['path'], 'Launch plan differs')
        w.require(argv.count('--out')==1 and argv[argv.index('--out')+1]==str(root), 'Launch root differs')
        label='b%d-s%d'%(stage['block'],stage['segment'])
        logpath=work/('LAUNCH-'+label+'.log')
        intent=work/('LAUNCH_INTENT-'+label+'.json')
        s.absent(logpath)
        s.absent(intent)
        s.write_doc(intent,{'schema':'runtime-exact-stage-launch-intent-v1','stage_index':index,
                          'ready_receipt':w.identity(s,ready_path),'plan':stage['plan'],
                          'storage_admission':stage['storage_admission'],'launch_argv':argv,
                          'actual_free_bytes':free,'required_free_bytes':stage['required_free_bytes_before_stage'],
                          'no_retry_after_intent':True,'created_ns':time.time_ns()})
        fd=os.open(logpath,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
    # No reads/hashes/storage/imports until this exact child has been reaped.
    with os.fdopen(fd,'wb') as logfile:
        result=runner(argv,stdout=logfile,stderr=subprocess.STDOUT,check=False)
    with s.quiet(lock):
        event={'schema':'runtime-exact-stage-launch-outcome-v1','stage_index':index,'launch_argv':argv,
               'returncode':result.returncode,'launch_log':w.identity(s,logpath),'finished_ns':time.time_ns(),
               'next_action':'preserve_terminal_stage_then_stop_unless_terminal_success'}
        s.write_doc(work/('LAUNCH_OUTCOME-'+label+'.json'),event)
        return event


def conduct(s, first_terminal_stage, *, preserve=w.preserve, launch=exact_launch, work=w.WORK, lock=w.LOCK):
    w.require(0 <= first_terminal_stage < 8,'Invalid first terminal stage')
    for current in range(first_terminal_stage,8):
        report=preserve(s,current)
        print(json.dumps({'stage_index':current,'storage_status':report['status'],
                          'terminal_stage_success':report['terminal_stage_success']},sort_keys=True),flush=True)
        w.require(report['terminal_stage_success'] is True,'Terminal failure/unknown/missing state: no next launch')
        if current == 7:
            with s.quiet(lock):
                s.write_doc(work/'ALL8_STORAGE_COMPLETE.json',{'schema':'runtime-all8-storage-complete-v1',
                            'status':'ALL8_TERMINAL_SUCCESS_AND_STORAGE_PRESERVED',
                            'final_stage_report':w.identity(s,work/'b1-s3/STAGE_STORAGE_REPORT.json'),
                            'storage_acceptance_is_not_native_or_quality_acceptance':True,'finished_ns':time.time_ns()})
            return
        outcome=launch(s,current+1)
        if outcome['returncode'] != 0:
            # Archive actual terminal failed bytes if possible, but NEVER proceed.
            preserve(s,current+1)
            raise RuntimeError('Exact stage launch returned nonzero; terminal evidence preserved where available; no retry')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first-terminal-stage-index',type=int,required=True)
    parser.add_argument('--qualification-receipt',type=Path,required=True)
    parser.add_argument('--owner-opened-post-stage-quiet-slot',action='store_true')
    parser.add_argument('--owner-authorized-frozen-all8-sequence',action='store_true')
    parser.add_argument('--explicitly-retire-admitted-raw',action='store_true')
    args=parser.parse_args()
    w.require(args.owner_opened_post_stage_quiet_slot and args.owner_authorized_frozen_all8_sequence
              and args.explicitly_retire_admitted_raw,'Owner quiet slot, exact all8 sequence and recoverable retirement required')
    s=w.load_helper()
    qualify(s,args.qualification_receipt,w.LOCK)
    conduct(s,args.first_terminal_stage_index)

if __name__=='__main__':
    try:
        main()
    except (OSError,RuntimeError,ValueError,KeyError) as exc:
        print(json.dumps({'status':'STOP_INSPECT_DO_NOT_RETRY','error_type':type(exc).__name__,'error':str(exc)}),file=sys.stderr,flush=True)
        sys.exit(2)
