#!/usr/bin/env python3
"""Sampled execution/resource guard only; never scoring, admission or storage.

Owner/reviewer acceptance and a live quiet slot are prerequisites. Exact shell
and numeric request are hash-bound. No scientific module is imported. Samples
are soft observations, not a hard disk/RSS/fit or quality guarantee. Any breach,
child failure or uncertainty preserves intent, log, all outputs and outcome.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time

PERIOD_SECONDS=1.0
TERM_GRACE_SECONDS=30.0
MIN_MEMAVAILABLE=6_500_000_000


def need(ok,message):
    if not ok:raise ValueError(message)


def pinned_json(path,expected_sha):
    path=Path(path)
    need(path.is_absolute() and str(path)==os.path.abspath(path),'noncanonical request path')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_size<=8*1024*1024,'request is not bounded regular metadata')
        data=stream.read()
    need(hashlib.sha256(data).hexdigest()==expected_sha,'numeric request hash mismatch')
    return json.loads(data)


def pin_shell(path,expected_sha):
    path=Path(path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno());need(stat.S_ISREG(info.st_mode) and info.st_size<=1024*1024,'bad shell source')
        data=stream.read()
    need(path.is_absolute() and hashlib.sha256(data).hexdigest()==expected_sha,'shell source hash/path mismatch')
    return str(path)


def memavailable():
    with open('/proc/meminfo') as stream:
        for line in stream:
            words=line.split()
            if words[0]=='MemAvailable:':return int(words[1])*1024
    raise ValueError('MemAvailable is unknown')


def diskfree(path):
    info=os.statvfs(path)
    return info.f_bavail*info.f_frsize


def window_bytes(root,metrics_relative):
    """Descriptor-relative, non-following walk; never enter source symlinks."""
    metrics=other=skipped=0
    rootfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    def visit(fd,prefix):
        nonlocal metrics,other,skipped
        with os.scandir(fd) as entries:
            for entry in entries:
                relative=prefix+entry.name
                info=os.stat(entry.name,dir_fd=fd,follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    need(relative!=metrics_relative,'metrics output is a symlink')
                    skipped+=1;continue
                if stat.S_ISDIR(info.st_mode):
                    child=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                    try:visit(child,relative+'/')
                    finally:os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    if relative==metrics_relative:metrics=info.st_size
                    else:other+=info.st_size
                else:raise ValueError('nonregular current-window output: '+relative)
    try:visit(rootfd,'')
    finally:os.close(rootfd)
    return dict(metrics_bytes=metrics,other_new_regular_bytes=other,symlinks_not_followed=skipped)


def violation(sample,metrics_budget,other_budget,reserve):
    if sample['metrics_bytes']>metrics_budget:return 'metrics_budget_exceeded'
    if sample['other_new_regular_bytes']>other_budget:return 'other_output_budget_exceeded'
    if sample['free_bytes']<reserve:return 'free_disk_below_original_reserve'
    return None


def write_new(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')


def group_alive(pid):
    try:os.killpg(pid,0);return True
    except ProcessLookupError:return False


def run(request,request_ref,shell,shell_ref,*,sample_period=PERIOD_SECONDS,
        grace=TERM_GRACE_SECONDS,read_mem=memavailable,read_free=diskfree):
    """Timing overrides exist for synthetic fixtures, not the operational CLI."""
    root=Path(request['scope']['out'])
    need(root.is_absolute() and root.is_dir() and not root.is_symlink(),'exact existing window root required')
    need(request['scope']['mode']=='cap-window','guard is scoped to cap V4 only')
    relative=request['metrics_gzip_inputs'][0]['path']
    need(relative=='v4/METRICS_BY_RUN.json','unexpected metrics output path')
    guards=request['live_guard_requirements']
    metrics_budget=guards['metrics_budget_bytes'];other_budget=guards['all_other_new_bytes'];reserve=guards['min_free_bytes']
    need(type(metrics_budget)is int and metrics_budget>0 and other_budget==400000000 and reserve==1000000000,
         'numeric guard envelope differs from exact accepted policy')
    need(request['output_upper_bytes'][relative]==metrics_budget,'metrics budget/request contradiction')
    fresh=dict(free_bytes=read_free(root),memavailable_bytes=read_mem(),**window_bytes(root,relative))
    need(fresh['free_bytes']>=request['required_free_bytes'],'fresh free disk fails exact numeric request')
    need(fresh['memavailable_bytes']>=MIN_MEMAVAILABLE,'fresh MemAvailable below6.5GB')
    need(violation(fresh,metrics_budget,other_budget,reserve)is None,'prelaunch output/reserve guard failed')
    intent,log_path,outcome=(root/name for name in ('EVALUATION_INTENT.json','EVALUATION.log','EVALUATION_OUTCOME.json'))
    need(not outcome.exists(),'prior outcome exists; preserve and do not retry')
    argv=['/bin/bash',shell]
    start=dict(utc_ns=time.time_ns(),monotonic_ns=time.monotonic_ns())
    write_new(intent,dict(schema='finite-cap-v4-supervision-intent-v1',argv=argv,shell=shell_ref,
        numeric_request=request_ref,fresh_resources=fresh,start=start,sample_period_seconds=sample_period,
        term_then_kill_grace_seconds=grace,soft_sampled_not_hard_fit_guarantee=True))
    child=None;samples=[];breach=None;error=None;term_at=None;killed=False;returncode=None
    try:
        with log_path.open('xb') as log:
            child=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            while True:
                sample=dict(utc_ns=time.time_ns(),monotonic_ns=time.monotonic_ns(),
                    free_bytes=read_free(root),**window_bytes(root,relative))
                samples.append(sample)
                problem=violation(sample,metrics_budget,other_budget,reserve)
                if problem and breach is None:
                    breach=problem;term_at=time.monotonic()
                    try:os.killpg(child.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                if term_at is not None and not killed and time.monotonic()-term_at>=grace:
                    try:os.killpg(child.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    killed=True
                returncode=child.poll()
                if returncode is not None and (term_at is None or killed or not group_alive(child.pid)):break
                time.sleep(sample_period)
    except BaseException as exc:
        error=type(exc).__name__+': '+str(exc)
        if child is not None and group_alive(child.pid):
            try:os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            deadline=time.monotonic()+grace
            while group_alive(child.pid) and time.monotonic()<deadline:
                child.poll();time.sleep(min(.1,max(0,deadline-time.monotonic())))
            if group_alive(child.pid):
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                killed=True
            child.wait()
        returncode=None if child is None else child.poll()
    result=dict(schema='finite-cap-v4-supervision-outcome-v1',argv=argv,shell=shell_ref,
        numeric_request=request_ref,start=start,end=dict(utc_ns=time.time_ns(),monotonic_ns=time.monotonic_ns()),
        pid=None if child is None else child.pid,new_process_group=True,returncode=returncode,
        breach=breach,error=error,kill_sent=killed,fresh_resources=fresh,samples=samples,
        sampled_envelope_completed_without_observed_breach=returncode==0 and breach is None and error is None,
        quality_or_reader_or_output_acceptance=False,soft_sampled_not_hard_fit_guarantee=True,
        outputs_logs_intent_preserved=True,automatic_retry_permitted=False)
    write_new(outcome,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner-quiet-open',action='store_true')
    parser.add_argument('--request',required=True);parser.add_argument('--request-sha256',required=True)
    parser.add_argument('--shell',required=True);parser.add_argument('--shell-sha256',required=True)
    args=parser.parse_args()
    need(args.owner_quiet_open,'explicit owner quiet release required')
    request=pinned_json(args.request,args.request_sha256);shell=pin_shell(args.shell,args.shell_sha256)
    result=run(request,dict(path=args.request,sha256=args.request_sha256),shell,
               dict(path=args.shell,sha256=args.shell_sha256))
    return 0 if result['sampled_envelope_completed_without_observed_breach'] else 1


if __name__=='__main__':raise SystemExit(main())
