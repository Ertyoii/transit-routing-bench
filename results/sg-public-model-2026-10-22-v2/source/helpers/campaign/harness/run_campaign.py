#!/usr/bin/env python3
"""Foreground, serialized, source-bound process runner. No benchmark policy inside."""
import argparse
import ctypes
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

import campaign_gate

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
LEGACY_SETUP = Path('/workspace/shared/sg-coldstart/setup')
GO = LEGACY_SETUP / 'toolchain/go/bin/go'
STOP = None


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def source_hash(root):
    """Same length-delimited content hash as experiment.SourceHash on Linux."""
    files = []
    for parent, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('.git', '.cache', 'artifacts')]
        for name in names:
            p = Path(parent) / name
            rel = p.relative_to(root).as_posix()
            if name.endswith('.go') or name in ('go.mod', 'routing.lock.json') or rel == 'vendor/modules.txt':
                files.append((rel, p))
    h = hashlib.sha256()
    for rel, path in sorted(files):
        data = path.read_bytes()
        encoded = rel.encode()
        h.update(str(len(encoded)).encode() + b':' + encoded + b':' + str(len(data)).encode() + b':')
        h.update(data)
    return h.hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def source_identity(root):
    return {'path': str(root), 'commit': git(root, 'rev-parse', 'HEAD'),
            'status_porcelain': git(root, 'status', '--porcelain=v1'),
            'go_source_hash_sha256': source_hash(root)}


def file_identity(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError(f'Input is not a file: {path}')
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def proc_stat(pid):
    s = Path(f'/proc/{pid}/stat').read_text()
    return s[s.rfind(')') + 2:].split()


def start_ticks(pid):
    try:
        return proc_stat(pid)[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def group_rss(pgid):
    total = count = 0
    page = os.sysconf('SC_PAGE_SIZE')
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            if int(proc_stat(p.name)[2]) == pgid:
                total += int((p / 'statm').read_text().split()[1]) * page
                count += 1
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
            pass
    return total, count


def group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def kill_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False


def signal_stop(sig, _frame):
    global STOP
    STOP = signal.Signals(sig).name


def child_setup():
    # Give cleanup a distinct process group, and kill the direct child if the
    # foreground runner unexpectedly dies. Normal timeout/cancel kills the group.
    os.setsid()
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), 'prctl(PR_SET_PDEATHSIG) failed')
    if os.getppid() != parent:
        os.kill(os.getpid(), signal.SIGKILL)


def expand(value, run_dir, campaign_dir):
    return str(value).replace('{run_dir}', str(run_dir)).replace('{campaign_dir}', str(campaign_dir))


def prepare_run(spec, run_dir, campaign_dir, env, cpus, sample_s, registry=None, inspect_heldout=False):
    argv = [expand(x, run_dir, campaign_dir) for x in spec['argv']]
    cwd = Path(expand(spec.get('cwd', ROOT / 'bench'), run_dir, campaign_dir)).resolve(strict=True)
    executable = shutil.which(argv[0], path=env['PATH'])
    if not executable:
        raise FileNotFoundError(f'Executable not found: {argv[0]}')
    argv[0] = str(Path(executable).resolve())
    timeout_s = float(spec['timeout_s'])
    if timeout_s <= 0:
        raise ValueError('timeout_s must be positive')
    run_env = dict(env)
    run_env.update({str(k): expand(v, run_dir, campaign_dir) for k, v in spec.get('env', {}).items()})
    if run_env.get('GOMAXPROCS') != '4':
        raise ValueError('This runner requires GOMAXPROCS=4; use a separately named runner/protocol for other CPU budgets')
    selected = campaign_gate.flags(argv, '-algorithm') + campaign_gate.flags(argv, '-algorithms')
    basename=Path(argv[0]).name.lower()
    if 'csabench' in basename or ('profilebench' in basename and selected!=['range_raptor']) or ('tadbench' in basename and not selected):
        raise ValueError('V2 native auxiliary requires explicit non-CSA algorithm selection')
    if any('csa' in name.lower() for names in selected for name in names.split(',')):
        raise ValueError('V2 excludes every CSA-family adapter from new execution')
    command = ['/usr/bin/taskset', '-c', cpus, *argv]
    input_paths = [expand(p, run_dir, campaign_dir) for p in spec.get('inputs', [])]
    file_flags = ('-dataset', '-queries', '-fixture', '-scoped-config', '-preference-scenarios')
    for flag in file_flags:
        input_paths.extend(campaign_gate.flags(argv, flag))
    bound_inputs = []
    for value in input_paths:
        path = Path(value)
        if not path.is_absolute():
            path = cwd / path
        if str(path.resolve()) not in bound_inputs:
            bound_inputs.append(str(path.resolve()))
        if path.name.endswith('.manifest.json'):
            manifest = json.loads(path.read_text())
            for field in ('data_file', 'license_file'):
                if field in manifest:
                    referenced = str((path.parent / manifest[field]).resolve())
                    if referenced not in bound_inputs:
                        bound_inputs.append(referenced)
    module_root = campaign_gate.module_root(cwd)
    default_roots = [module_root] if module_root is not None else [cwd]
    declared_roots = spec.get('source_roots', default_roots)
    if any(not Path(str(p)).is_absolute() for p in declared_roots):
        raise ValueError('source_roots must be explicit absolute paths')
    source_roots = [Path(expand(p, run_dir, campaign_dir)).resolve(strict=True) for p in declared_roots]
    source_roots = list(dict.fromkeys(source_roots))
    if module_root is not None and module_root not in source_roots:
        raise ValueError('Actual execution module root must be included in source_roots')
    gate = campaign_gate.classify(bound_inputs, argv, cwd, registry, inspect_heldout=inspect_heldout)
    bound_inputs = gate.pop('bound_inputs')
    metadata = {
        'id': spec['id'], 'started_utc': utc(), 'argv': command, 'cwd': str(cwd),
        'timeout_s': timeout_s, 'term_grace_s': 3.0, 'binary': file_identity(argv[0]),
        'inputs': [file_identity(p) for p in bound_inputs],
        'sources_before': [source_identity(p) for p in source_roots],
        'environment': {k: run_env.get(k) for k in ('GOMAXPROCS', 'GOMEMLIMIT', 'GOTOOLCHAIN', 'GOPROXY', 'GOSUMDB', 'GOCACHE', 'GOMODCACHE', 'GODEBUG', 'GOGC', 'GOEXPERIMENT', 'CGO_ENABLED', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'TZ', 'LANG', 'LC_ALL', 'TRANSIT_BENCH_HARDWARE')},
        'requested_cpu_affinity': cpus,
        'monitor_cpu_affinity': sorted(os.sched_getaffinity(0)),
        'sampled_rss_safety_stop_bytes': spec.get('rss_safety_stop_bytes'),
        'memory_limit_kind': 'GOMEMLIMIT soft Go GC target; NO hard RSS/cgroup cap',
        'rss_sample_interval_s': sample_s,
        'rss_definition': 'Sum of process-group /proc/PID/statm RSS, sampled. Shared pages may be counted multiple times; transient peaks may be missed.',
        'workload_gate': gate,
        'input_hash_cache_effect': 'Input content hashing occurs before process launch and may warm the filesystem page cache. This is NOT a cold-disk measurement.',
    }
    return metadata, argv, cwd, run_env, source_roots, timeout_s


def prepared_binding(metadata, run_dir=None, campaign_dir=None):
    binding = {k: metadata[k] for k in ('id', 'argv', 'cwd', 'timeout_s', 'term_grace_s', 'binary', 'inputs', 'sources_before', 'environment', 'requested_cpu_affinity', 'sampled_rss_safety_stop_bytes', 'workload_gate')}
    if run_dir is None:
        return binding
    def normalize(value):
        if isinstance(value, str):
            return value.replace(str(run_dir), '/__SEALED_RUN_DIR__/' + metadata['id']).replace(str(campaign_dir), '/__SEALED_CAMPAIGN__')
        if isinstance(value, list):
            return [normalize(x) for x in value]
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        return value
    return normalize(binding)


def check_fresh_final_binding(metadata, source_roots, run_dir, campaign_dir, expected_final):
    context = expected_final.get('verification_context')
    if not context or context.get('evaluation_mode') not in campaign_gate.FINAL_MODES:
        raise ValueError('Final prelaunch check requires the exact verified plan/seal dependency context')
    # Rebuild and compare the ENTIRE seal at the last prelaunch guard, including
    # qualification, audit, review, raw artifacts, policy and runner/gate bytes.
    # These reads are still not an atomic or adversarially immutable filesystem.
    fresh = verify_seal(context['plan_path'], context['seal_ref'], context['cpus'], context['sample_s'],
                        require_official=context['evaluation_mode'] == 'final_evaluation',
                        require_public_model=context['evaluation_mode'] == campaign_gate.PUBLIC_FINAL_MODE)
    if fresh['snapshot_sha256'] != expected_final['snapshot_sha256']:
        raise ValueError('Final prelaunch whole-seal snapshot changed; launch blocked')
    if prepared_binding(metadata, run_dir, campaign_dir) != expected_final['run']:
        raise ValueError('Freshly prepared final command differs from the verified sealed run; launch blocked')
    for root in source_roots:
        actual = campaign_gate.source_tree_snapshot(root)['manifest_sha256']
        if actual != expected_final['source_tree_manifest_by_root'].get(str(root)):
            raise ValueError('Fresh finalist source/support snapshot differs from the verified seal; launch blocked')


def host_snapshot():
    paths=['/proc/loadavg','/proc/meminfo','/proc/pressure/cpu','/proc/pressure/memory','/proc/pressure/io','/proc/stat','/sys/fs/cgroup/cpu.stat','/sys/fs/cgroup/cpu.max','/sys/fs/cgroup/memory.current','/sys/fs/cgroup/memory.max']
    result={'utc':utc(),'monotonic_ns':time.monotonic_ns()}
    for path in paths:
        try: result[path]=Path(path).read_text()
        except (OSError,PermissionError) as exc: result[path]={'unavailable':str(exc)}
    return result


def competing_go_processes():
    result=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit(): continue
        try:
            args=[x.decode(errors='replace') for x in (path/'cmdline').read_bytes().split(b'\0') if x]
            if args and ((Path(args[0]).name=='go' and any(x in ('build','test','run') for x in args[1:3])) or Path(args[0]).name in ('compile','link')):
                result.append({'pid':int(path.name),'argv':args})
        except (OSError,PermissionError): pass
    return result


def verify_publication_receipt(metadata, events):
    argv=metadata['argv']
    enabled='-stream-responses' in argv or '-stream-responses=true' in argv
    if not enabled:return {'enabled':False,'valid':True}
    outputs=campaign_gate.flags(argv,'-out-dir')
    if len(outputs)!=1:return {'enabled':True,'valid':False,'error':'stream output directory not uniquely bound'}
    path=Path(outputs[0])/'available-responses.jsonl'
    first=None;records=0;error=None
    try:
        if path.exists():
            with path.open() as file:
                for line in file:
                    row=json.loads(line);records+=1
                    if first is None and row.get('completed') and row.get('attempted'):first=row
        if len(events)>1:raise ValueError('multiple first-answer events')
        if first is None:
            if events:raise ValueError('first-answer event without completed serialized witness')
        else:
            if len(events)!=1:raise ValueError('completed serialized witness missing first-answer event')
            marker=events[0]['payload']
            if marker.get('query_id')!=first.get('query',{}).get('id') or first.get('status')!='complete':raise ValueError('first-answer event query/status mismatch')
            pub=marker.get('published_response_ns');ser=marker.get('serialization_ns');response=first.get('response_ns')
            if not all(isinstance(x,int) and not isinstance(x,bool) and x>=0 for x in [pub,ser,response]) or pub<response or ser>pub-response:raise ValueError('first-answer publication/serialization timing invalid')
        return {'enabled':True,'valid':True,'records':records,'first_completed_query_id':first.get('query',{}).get('id') if first else None,'file':file_identity(path) if path.exists() else None,'scope':'actual serialized ordinary answers; local availability, not transport or fsync durability'}
    except (OSError,ValueError,TypeError,KeyError) as exc:
        return {'enabled':True,'valid':False,'error':str(exc),'records_read':records}


def run_one(spec, run_dir, campaign_dir, env, cpus, status, status_path, index, sample_s, registry=None, expected_final=None):
    global STOP
    metadata, argv, cwd, run_env, source_roots, timeout_s = prepare_run(
        spec, run_dir, campaign_dir, env, cpus, sample_s, registry, inspect_heldout=expected_final is not None)
    if expected_final is not None:
        check_fresh_final_binding(metadata, source_roots, run_dir, campaign_dir, expected_final)
    command = metadata['argv']
    write_json(run_dir / 'command.json', metadata)
    status.update({'state': 'running', 'active_run': spec['id'], 'active_index': index, 'updated_utc': utc()})
    write_json(status_path, status)
    host_before = host_snapshot()
    competing_before = competing_go_processes()
    if competing_before:
        raise RuntimeError('Headline run blocked by active Go build/test processes: ' + repr(competing_before))
    begin = time.monotonic()
    peak_rss = peak_count = 0
    termination = None
    term_started = None
    reaped = False
    wait_status = usage = None
    proc = None
    done = threading.Event()
    waited = {}
    waiter = None
    process_begin_ns = process_end_ns = None
    first_answer_events = []
    stdout_thread = None
    try:
        with open(run_dir / 'stdout.log', 'wb') as stdout, open(run_dir / 'stderr.log', 'wb') as stderr, open(run_dir / 'rss-samples.jsonl', 'w') as samples:
            process_begin_ns = time.monotonic_ns()
            proc = subprocess.Popen(command, cwd=cwd, env=run_env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=stderr, preexec_fn=child_setup)
            def drain_stdout():
                for line in iter(proc.stdout.readline, b''):
                    received_ns = time.monotonic_ns()
                    stdout.write(line); stdout.flush()
                    try:
                        value=json.loads(line)
                        if isinstance(value,dict) and value.get('event')=='first_available_answer':
                            first_answer_events.append({'supervisor_received_since_spawn_ns':received_ns-process_begin_ns,'payload':value})
                    except (ValueError,UnicodeDecodeError):
                        pass
            stdout_thread=threading.Thread(target=drain_stdout,daemon=True)
            stdout_thread.start()
            def reap_child():
                try:
                    _, ws, ru = os.wait4(proc.pid, 0)
                    waited.update(status=ws, usage=ru, ended_ns=time.monotonic_ns())
                except BaseException as exc:
                    waited['error'] = repr(exc)
                finally:
                    done.set()
            waiter = threading.Thread(target=reap_child, daemon=True)
            waiter.start()
            metadata['pid'] = proc.pid
            metadata['pgid'] = proc.pid
            metadata['process_start_ticks'] = start_ticks(proc.pid)
            write_json(run_dir / 'command.json', metadata)
            while True:
                now = time.monotonic()
                cancel_path = campaign_dir / 'cancel.request.json'
                if cancel_path.exists():
                    request = json.loads(cancel_path.read_text())
                    if request.get('target_started_utc') == status['started_utc'] and request.get('target_plan_sha256') == status['plan_sha256']:
                        STOP = 'file_cancel_requested'
                rss, count = group_rss(proc.pid)
                peak_rss = max(peak_rss, rss)
                peak_count = max(peak_count, count)
                samples.write(json.dumps({'elapsed_s': now - begin, 'process_group_rss_bytes': rss, 'processes': count}) + '\n')
                samples.flush()
                if done.is_set():
                    if 'error' in waited:
                        raise RuntimeError(waited['error'])
                    reaped = True
                    wait_status, usage = waited['status'], waited['usage']
                    process_end_ns = waited['ended_ns']
                    proc.returncode = os.waitstatus_to_exitcode(wait_status)
                    if termination is None and (process_end_ns - process_begin_ns) / 1e9 > timeout_s:
                        termination = 'timeout'
                    break
                if termination is None and (STOP or now - begin >= timeout_s):
                    termination = f'cancelled:{STOP}' if STOP else 'timeout'
                    term_started = now
                    kill_group(proc.pid, signal.SIGTERM)
                elif termination is None and spec.get('rss_safety_stop_bytes') and rss > int(spec['rss_safety_stop_bytes']):
                    termination = 'sampled_rss_safety_stop'
                    term_started = now
                    kill_group(proc.pid, signal.SIGTERM)
                elif termination is not None and now - term_started >= 3.0:
                    kill_group(proc.pid, signal.SIGKILL)
                done.wait(sample_s)
            stdout_thread.join(timeout=5)
            proc.stdout.close()
            # A command that forks a background worker is not allowed to leave it
            # running after its leader exits, even for an otherwise successful run.
            leftover = group_exists(proc.pid)
            if leftover:
                kill_group(proc.pid, signal.SIGTERM)
                until = time.monotonic() + 3.0
                while group_exists(proc.pid) and time.monotonic() < until:
                    time.sleep(0.05)
                kill_group(proc.pid, signal.SIGKILL)
    finally:
        if proc is not None and not reaped:
            kill_group(proc.pid, signal.SIGTERM)
            time.sleep(0.1)
            kill_group(proc.pid, signal.SIGKILL)
            if waiter is not None:
                done.wait(5.0)
                if 'status' in waited:
                    proc.returncode = os.waitstatus_to_exitcode(waited['status'])
            else:
                try:
                    _, wait_status, usage = os.wait4(proc.pid, 0)
                    proc.returncode = os.waitstatus_to_exitcode(wait_status)
                except ChildProcessError:
                    pass
    after = [source_identity(p) for p in source_roots]
    result = {
        'id': spec['id'], 'host_before':host_before, 'host_after':host_snapshot(),
        'first_available_answer_events':first_answer_events,
        'launch_to_first_available_answer_ns':first_answer_events[0]['supervisor_received_since_spawn_ns'] if first_answer_events else None,
        'first_answer_scope':'Supervisor monotonic spawn to receiving first serialized-answer publication event; includes fork/exec, parsing, all preparation, first query, selected recommendation, answer serialization and stdout delivery. Missing event is unknown, never zero.',
        'finished_utc': utc(), 'elapsed_wall_s': time.monotonic() - begin,
        'process_wall_s': (process_end_ns - process_begin_ns) / 1e9,
        'process_wall_note': 'monotonic launch-to-blocking-wait4 completion; excludes input/source hashing, includes fork/exec and scheduler overhead. Harness internal timing remains authoritative for submillisecond query latency.',
        'returncode': proc.returncode, 'exit_status': proc.returncode if proc.returncode >= 0 else None,
        'signal': signal.Signals(-proc.returncode).name if proc.returncode < 0 else None,
        'termination': termination, 'timed_out': termination == 'timeout',
        'sampled_peak_process_group_rss_bytes': peak_rss, 'sampled_peak_process_count': peak_count,
        'wait4_ru_maxrss_kib': usage.ru_maxrss if usage else None,
        'wait4_ru_maxrss_note': 'Linux wait4 maximum RSS, not summed process-group memory and not a hard cap.',
        'user_cpu_s': usage.ru_utime if usage else None, 'system_cpu_s': usage.ru_stime if usage else None,
        'leftover_group_after_leader_exit': leftover,
        'sources_after': after, 'source_contents_unchanged': all(a['go_source_hash_sha256'] == b['go_source_hash_sha256'] for a, b in zip(metadata['sources_before'], after)),
        'stdout': str(run_dir / 'stdout.log'), 'stderr': str(run_dir / 'stderr.log'),
        'workload_gate': metadata['workload_gate'],
    }
    result['publication_receipt']=verify_publication_receipt(metadata,first_answer_events)
    result['ok'] = result['publication_receipt']['valid'] and proc.returncode == 0 and not termination and not leftover and result['source_contents_unchanged']
    write_json(run_dir / 'result.json', result)
    return result


def campaign_environment():
    env = dict(os.environ)
    env.update({'PATH': str(GO.parent) + os.pathsep + env.get('PATH', ''), 'GOTOOLCHAIN': 'local',
                'GOMAXPROCS': '4', 'GOMEMLIMIT': '7GiB', 'GOPROXY': 'off', 'GOSUMDB': 'off',
                'GOCACHE': str(LEGACY_SETUP / 'cache/go-build'), 'GOMODCACHE': str(LEGACY_SETUP / 'cache/go-mod')})
    return env


def sealed_snapshot(plan_path, cpus='0-3', sample_s=0.2):
    """Read-only binding; never starts a router or accesses router outcomes."""
    plan_path = Path(plan_path).resolve(strict=True)
    plan = json.loads(plan_path.read_text())
    mode = plan.get('evaluation_mode')
    if mode not in campaign_gate.FINAL_MODES:
        raise ValueError('A finalist seal requires evaluation_mode=final_evaluation or public_model_final_evaluation')
    registry = campaign_gate.load_registry(plan, plan_path.parent)
    if registry is None:
        raise ValueError('Finalist seal requires a predeclared hash-bound workload registry')
    runs = plan.get('runs', [])
    if not runs or len({r['id'] for r in runs}) != len(runs):
        raise ValueError('Final evaluation plan requires distinct nonempty runs')
    prepared = []
    source_trees = {}
    for spec in runs:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', spec['id']):
            raise ValueError('Unsafe final run ID')
        metadata, _, _, _, roots, _ = prepare_run(
            spec, Path('/__SEALED_RUN_DIR__') / spec['id'], Path('/__SEALED_CAMPAIGN__'),
            campaign_environment(), cpus, sample_s, registry, inspect_heldout=True)
        gate = metadata['workload_gate']
        if not gate['workloads'] or any(not w['registered'] for w in gate['workloads']):
            raise ValueError('Every final run workload must match a predeclared SHA/metadata registration')
        # Final-stage execution never uses unknown or merely diagnostic queries.
        if any(w['classification'] != 'test' for w in gate['workloads']):
            raise ValueError('Final evaluation workloads must be explicitly registered test splits')
        datasets = campaign_gate.flags(metadata['argv'], '-dataset')
        if len(datasets) != 1:
            raise ValueError('Final evaluation requires one explicitly bound normalized dataset')
        dataset_sha = digest(campaign_gate.resolve(datasets[0], Path(metadata['cwd'])))
        if any(w.get('dataset_sha256') != dataset_sha for w in gate['workloads']):
            raise ValueError('Final workload metadata must bind the actual normalized dataset SHA')
        prepared.append(prepared_binding(metadata))
        for root in roots:
            source_trees[str(root)] = campaign_gate.source_tree_snapshot(root)
    return {
        'schema': campaign_gate.PUBLIC_SEAL_SCHEMA if mode == campaign_gate.PUBLIC_FINAL_MODE else campaign_gate.SEAL_SCHEMA,
        'plan': file_identity(plan_path), 'plan_canonical_sha256': campaign_gate.canonical_hash(plan),
        'entire_evaluation_plan': plan,
        'registry': registry['file'], 'registry_contents_sha256': campaign_gate.canonical_hash(registry['payload']),
        'runner': file_identity(Path(__file__).resolve()), 'gate_implementation': file_identity(Path(campaign_gate.__file__).resolve()),
        'source_eligibility_policy': file_identity(campaign_gate.SOURCE_POLICY),
        'execution_controls': {'cpus': cpus, 'rss_sample_s': sample_s, 'continue_on_failure': bool(plan.get('continue_on_failure', False))},
        'finalists_and_runs': prepared, 'full_source_snapshots': list(source_trees.values()),
        'data_qualification_binding': campaign_gate.qualification_binding(plan, plan_path.parent),
        'policy': campaign_gate.POLICY,
    }


def create_seal(plan_path, out, cpus='0-3', sample_s=0.2):
    out = Path(out).resolve()
    if out.exists():
        raise FileExistsError('A finalist seal is create-only; choose a new file, never overwrite an earlier seal')
    snapshot = sealed_snapshot(plan_path, cpus, sample_s)
    payload = {'schema': snapshot['schema'], 'created_utc': utc(), 'snapshot': snapshot,
               'snapshot_sha256': campaign_gate.canonical_hash(snapshot),
               'claim': 'Consistency snapshot only. Does not authorize evaluation, certify input truth, or prove immutable sealing.'}
    # Exclusive creation preserves prior local evidence. This is not WORM storage.
    with out.open('x') as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write('\n')
    return file_identity(out)


def verify_seal(plan_path, seal_ref, cpus='0-3', sample_s=0.2, require_official=False, require_public_model=False):
    plan_path = Path(plan_path).resolve(strict=True)
    sealed_file = campaign_gate.check_identity(seal_ref, plan_path.parent, 'Predeclared finalist seal')
    seal = json.loads(Path(sealed_file['path']).read_text())
    mode = json.loads(plan_path.read_text()).get('evaluation_mode')
    expected_schema = campaign_gate.PUBLIC_SEAL_SCHEMA if mode == campaign_gate.PUBLIC_FINAL_MODE else campaign_gate.SEAL_SCHEMA
    if seal.get('schema') != expected_schema or seal.get('snapshot_sha256') != campaign_gate.canonical_hash(seal.get('snapshot')):
        raise ValueError('Finalist seal snapshot digest/schema is inconsistent')
    if require_official and mode != 'final_evaluation':
        raise ValueError('Official-data validation requires final_evaluation; public-model tier is not official qualification')
    if require_public_model and mode != campaign_gate.PUBLIC_FINAL_MODE:
        raise ValueError('Public-model data validation requires public_model_final_evaluation')
    current = sealed_snapshot(plan_path, cpus, sample_s)
    if current != seal['snapshot']:
        raise ValueError('Finalist seal no longer matches plan, workload/sidecar, source, binary, config, input, registry, controls, or qualification artifacts')
    qualification = None
    if require_official:
        qualification = campaign_gate.reviewed_data_qualification(
            current['entire_evaluation_plan'], plan_path.parent, current['finalists_and_runs'])
    elif require_public_model:
        qualification = campaign_gate.reviewed_public_model_qualification(
            current['entire_evaluation_plan'], plan_path.parent, current['finalists_and_runs'])
    return {'seal': sealed_file, 'snapshot_sha256': seal['snapshot_sha256'], 'consistency_valid': True,
            'evaluation_mode': mode,
            'official_data_gate_passed': require_official and qualification is not None,
            'public_model_data_gate_passed': require_public_model and qualification is not None,
            'data_qualification': qualification,
            'verified_run_bindings': {run['id']: run for run in current['finalists_and_runs']},
            'source_tree_manifest_by_root': {tree['root']: tree['manifest_sha256'] for tree in current['full_source_snapshots']},
            'verification_context': {'plan_path': str(plan_path), 'seal_ref': sealed_file, 'cpus': cpus, 'sample_s': sample_s, 'evaluation_mode': mode},
            'execution_performed': False, 'policy': campaign_gate.POLICY}


def run(args):
    global STOP
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal_stop)
    plan_path = Path(args.plan).resolve(strict=True)
    plan = json.loads(plan_path.read_text())
    mode = plan.get('evaluation_mode', 'diagnostic')
    final_gate = None
    qualification_checks = {'require_official': mode == 'final_evaluation',
                            'require_public_model': mode == campaign_gate.PUBLIC_FINAL_MODE}
    if mode in campaign_gate.FINAL_MODES:
        if not args.seal or not args.seal_sha256:
            raise ValueError('Final execution requires --seal and its separately retained --seal-sha256')
        if args.continue_on_failure != bool(plan.get('continue_on_failure', False)):
            raise ValueError('Final continuation policy must equal the entire sealed evaluation plan')
        final_gate = verify_seal(plan_path, {'path': args.seal, 'sha256': args.seal_sha256}, args.cpus, args.sample_s, **qualification_checks)
    campaign_gate.reject_execution_claims(plan, final_gate_passed=final_gate is not None)
    registry = campaign_gate.load_registry(plan, plan_path.parent)
    runs = plan.get('runs', [])
    if not runs:
        raise ValueError('Plan must include nonempty runs')
    ids = [r['id'] for r in runs]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', rid) for rid in ids):
        raise ValueError('Run IDs must be distinct safe filenames, at most 100 characters')
    initial_affinity = sorted(os.sched_getaffinity(0))
    housekeeping = set(initial_affinity) - {0, 1, 2, 3}
    if housekeeping:
        os.sched_setaffinity(0, {max(housekeeping)})
    campaign_dir = Path(args.out).resolve()
    if campaign_dir.exists():
        raise FileExistsError(f'Output must be a NEW independent directory: {campaign_dir}')
    lock = open(LEGACY_SETUP / 'campaign.lock', 'a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another serialized setup campaign holds campaign.lock')
    campaign_dir.mkdir(parents=True)
    shutil.copyfile(plan_path, campaign_dir / 'plan.json')
    status_path = campaign_dir / 'status.json'
    status = {'state': 'starting', 'runner_pid': os.getpid(), 'runner_start_ticks': start_ticks(os.getpid()),
              'runner_script': str(Path(__file__).resolve()), 'started_utc': utc(), 'updated_utc': utc(),
              'runner_sha256': digest(Path(__file__).resolve()),
              'runner_initial_cpu_affinity': initial_affinity,
              'runner_monitor_cpu_affinity': sorted(os.sched_getaffinity(0)),
              'plan_sha256': digest(plan_path), 'plan_path': str(plan_path), 'out_dir': str(campaign_dir),
              'evaluation_mode': mode,
              'completed_runs': [], 'total_runs': len(runs)}
    write_json(status_path, status)
    env = campaign_environment()
    status['final_evaluation_gate'] = final_gate
    write_json(status_path, status)
    try:
        for index, spec in enumerate(runs):
            if STOP:
                break
            if final_gate is not None:
                # Recheck the entire sealed campaign before EVERY launch, not
                # only before the first finalist. No stale registry indexes.
                final_gate = verify_seal(plan_path, {'path': args.seal, 'sha256': args.seal_sha256}, args.cpus, args.sample_s, **qualification_checks)
                registry = campaign_gate.load_registry(plan, plan_path.parent)
            run_dir = campaign_dir / spec['id']
            run_dir.mkdir()
            expected_final = ({'run': final_gate['verified_run_bindings'][spec['id']], 'source_tree_manifest_by_root': final_gate['source_tree_manifest_by_root'], 'verification_context': final_gate['verification_context'], 'snapshot_sha256': final_gate['snapshot_sha256']} if final_gate is not None else None)
            result = run_one(spec, run_dir, campaign_dir, env, args.cpus, status, status_path, index, args.sample_s, registry, expected_final=expected_final)
            result['evaluation_mode'] = mode
            if mode == campaign_gate.PUBLIC_FINAL_MODE:
                result.update(formal_baseline_eligible=False, latest_official_transit_feed=False,
                              official_source_authenticity_established=False)
            if final_gate is not None:
                try:
                    verify_seal(plan_path, {'path': args.seal, 'sha256': args.seal_sha256}, args.cpus, args.sample_s, **qualification_checks)
                    result['final_seal_integrity_after_run'] = True
                except Exception as exc:
                    result['final_seal_integrity_after_run'] = False
                    result['final_seal_integrity_error'] = f'{type(exc).__name__}: {exc}'
                    result['ok'] = False
                write_json(run_dir / 'result.json', result)
            status['completed_runs'].append({'id': spec['id'], 'ok': result['ok'], 'returncode': result['returncode'], 'timed_out': result['timed_out'], 'elapsed_wall_s': result['elapsed_wall_s'], 'result': str(run_dir / 'result.json')})
            status['updated_utc'] = utc()
            write_json(status_path, status)
            print(json.dumps(status['completed_runs'][-1]), flush=True)
            if not result['ok'] and not args.continue_on_failure:
                break
        status['state'] = 'cancelled' if STOP else ('completed' if len(status['completed_runs']) == len(runs) else 'stopped_on_failure')
        status['ok'] = status['state'] == 'completed' and all(r['ok'] for r in status['completed_runs'])
        status['active_run'] = None
        status['updated_utc'] = utc()
        write_json(status_path, status)
        return 0 if status['ok'] else 1
    except BaseException as exc:
        status.update({'state': 'runner_error', 'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'updated_utc': utc()})
        write_json(status_path, status)
        raise
    finally:
        lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    run_p = sub.add_parser('run', help='Run serially in the FOREGROUND; launch with an exec session, never shell backgrounding')
    run_p.add_argument('--plan', required=True)
    run_p.add_argument('--out', required=True)
    run_p.add_argument('--cpus', default='0-3')
    run_p.add_argument('--sample-s', type=float, default=0.2)
    run_p.add_argument('--continue-on-failure', action='store_true')
    run_p.add_argument('--seal')
    run_p.add_argument('--seal-sha256')
    register_p = sub.add_parser('register-workloads', help='Hash/metadata validation only; no router execution')
    register_p.add_argument('--manifest', required=True)
    register_p.add_argument('--out', required=True)
    seal_p = sub.add_parser('seal-finalists', help='Create-only consistency snapshot; no router execution')
    seal_p.add_argument('--plan', required=True)
    seal_p.add_argument('--out', required=True)
    validate_p = sub.add_parser('validate-seal', help='Read-only seal/mode-specific data validation; never executes a router')
    validate_p.add_argument('--plan', required=True)
    validate_p.add_argument('--seal', required=True)
    validate_p.add_argument('--seal-sha256', required=True)
    data_check = validate_p.add_mutually_exclusive_group()
    data_check.add_argument('--require-official-data', action='store_true')
    data_check.add_argument('--require-public-model-data', action='store_true')
    for name in ('status', 'cancel'):
        q = sub.add_parser(name)
        q.add_argument('--out', required=True)
    args = p.parse_args()
    if args.action == 'register-workloads':
        payload = campaign_gate.registry_from_manifest(args.manifest)
        with Path(args.out).open('x') as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write('\n')
        print(json.dumps(file_identity(args.out)))
        return 0
    if args.action == 'seal-finalists':
        print(json.dumps(create_seal(args.plan, args.out)))
        return 0
    if args.action == 'validate-seal':
        print(json.dumps(verify_seal(args.plan, {'path': args.seal, 'sha256': args.seal_sha256},
                                     require_official=args.require_official_data,
                                     require_public_model=args.require_public_model_data), indent=2))
        return 0
    if args.action == 'run':
        if args.cpus != '0-3' or args.sample_s < 0.05:
            p.error('This protocol runner requires --cpus 0-3 and --sample-s >= 0.05')
        return run(args)
    status = json.loads((Path(args.out) / 'status.json').read_text())
    if args.action == 'status':
        status['cancel_request_exists'] = (Path(args.out) / 'cancel.request.json').exists()
        print(json.dumps(status, indent=2))
        return 0
    if status['state'] not in ('starting', 'running'):
        print('Campaign is already terminal; no signal sent.')
        return 0
    # exec sessions may have isolated PID namespaces, so cross-session PID
    # signalling is not safe or reliable. A bound request file is checked by the
    # foreground owner, which performs process-group cleanup in its namespace.
    write_json(Path(args.out) / 'cancel.request.json', {
        'requested_utc': utc(), 'target_started_utc': status['started_utc'],
        'target_plan_sha256': status['plan_sha256'],
    })
    print('Cancellation requested through the shared filesystem; poll until cleanup and terminal state are recorded.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
