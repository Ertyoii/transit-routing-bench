#!/usr/bin/env python3
"""Explicit memory-admission wrapper; the immutable V2 runner owns execution.

No router, constructor, search, wait/retry policy, hard RSS cap or system setting
is introduced. Admission is a sampled pre-prepare observation, not a guarantee.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time

WRAPPER_PATH = Path(__file__).resolve()
BASE_PATH = WRAPPER_PATH.with_name('run_campaign.py')
BASE_SHA256 = '206076513f4fb023e38deb9aee96de07c8c885b579e716c56350c7f73ff4480b'
POLICY = {
    'schema': 'observed-memory-admission-policy-v1',
    'default_sampled_group_rss_stop_bytes': 5_500_000_000,
    'default_min_mem_available_bytes': 6_500_000_000,
    'reserve_bytes': 1_000_000_000,
    'on_rejection': 'stop_campaign_preserve_rejected_and_unstarted_offers',
    'unavailable_limits': 'record_unknown_never_infer_hidden_limits',
    'measurement_scope': 'MemAvailable and exposed cgroup headroom before prepare; no hard RSS guarantee',
}
V2_FILES = ('memory.max', 'memory.current', 'memory.high', 'memory.events',
            'memory.events.local', 'memory.swap.max', 'memory.swap.current')
V1_FILES = ('memory.limit_in_bytes', 'memory.usage_in_bytes',
            'memory.memsw.limit_in_bytes', 'memory.memsw.usage_in_bytes',
            'memory.stat', 'memory.failcnt')


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def identity(path):
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def create_json(path, value):
    with Path(path).open('x') as file:
        json.dump(value, file, indent=2, sort_keys=True)
        file.write('\n')


def load_base():
    """Import exact, unmodified source bytes without writing/using a bytecode cache."""
    data = BASE_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != BASE_SHA256:
        raise ValueError('Immutable base runner SHA256 mismatch; no execution allowed')
    spec = importlib.util.spec_from_file_location('_sg_immutable_admission_base_v1', BASE_PATH)
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    try:
        sys.path.insert(0, str(BASE_PATH.parent))
        exec(compile(data, str(BASE_PATH), 'exec'), module.__dict__)
    finally:
        sys.path[:] = old_path
    return module


def plan_binding():
    base = identity(BASE_PATH)
    if base['sha256'] != BASE_SHA256:
        raise ValueError('Immutable base runner SHA256 mismatch')
    return {'schema': 'memory-admission-plan-binding-v1', 'wrapper': identity(WRAPPER_PATH),
            'base_runner': base, 'policy': dict(POLICY)}


def validate_plan(plan):
    expected = plan_binding()
    if plan.get('memory_admission') != expected:
        raise ValueError('Plan must predeclare the exact wrapper, immutable base and admission policy')
    required = {expected['wrapper']['path'], expected['base_runner']['path']}
    for run in plan.get('runs', []):
        if not required.issubset(set(run.get('inputs', []))):
            raise ValueError('Every run inputs must explicitly bind the wrapper and immutable base paths')
    return expected


def positive_int(value, label):
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError(label + ' must be a positive non-boolean signed-64-bit integer')
    return value


def envelope(spec, gate):
    override = spec.get('memory_admission', {})
    if not isinstance(override, dict) or set(override) - {'sampled_group_rss_stop_bytes', 'min_mem_available_bytes'}:
        raise ValueError('Malformed per-run memory_admission override')
    if override and set(override) != {'sampled_group_rss_stop_bytes', 'min_mem_available_bytes'}:
        raise ValueError('Per-run overrides must explicitly declare both stop and minimum available bytes')
    stop = positive_int(override.get('sampled_group_rss_stop_bytes', POLICY['default_sampled_group_rss_stop_bytes']), 'Declared RSS stop')
    minimum = positive_int(override.get('min_mem_available_bytes', POLICY['default_min_mem_available_bytes']), 'Minimum MemAvailable')
    if minimum < stop + POLICY['reserve_bytes']:
        raise ValueError('Minimum MemAvailable must include at least the declared RSS stop plus 1e9 reserve bytes')
    if positive_int(spec.get('rss_safety_stop_bytes'), 'Supervisor RSS stop') != stop:
        raise ValueError('Supervisor RSS stop conflicts with the declared admission envelope')
    argv = spec.get('argv')
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError('argv must be a nonempty string list')
    guards = gate.flags(argv, '-rss-safety-stop') + gate.flags(argv, '-rss-safety-stop-bytes')
    if len(guards) > 1:
        raise ValueError('Multiple driver RSS guards are ambiguous')
    if guards and (not re.fullmatch(r'[1-9][0-9]*', guards[0]) or int(guards[0]) != stop):
        raise ValueError('Driver RSS stop conflicts with the declared admission envelope')
    return {'sampled_group_rss_stop_bytes': stop, 'min_mem_available_bytes': minimum,
            'reserve_bytes': POLICY['reserve_bytes'], 'driver_rss_guard': guards[0] if guards else None}


def read_observed(path):
    try:
        return Path(path).read_text()
    except OSError as exc:
        return {'unavailable': f'{type(exc).__name__}: {exc}'}


def cgroup_directories(files):
    """Known mount roots plus resolvable exposed membership ancestors, not hidden limits."""
    directories = {('/sys/fs/cgroup', 2), ('/sys/fs/cgroup', 1), ('/sys/fs/cgroup/memory', 1)}
    notes = []
    membership, mounts = files['/proc/self/cgroup'], files['/proc/self/mountinfo']
    if not isinstance(membership, str) or not isinstance(mounts, str):
        return sorted(directories), ['Membership/mount discovery unavailable; hidden limits remain unknown']
    unescape = lambda s: re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), s)
    groups = []
    for row in membership.splitlines():
        fields = row.split(':', 2)
        if len(fields) == 3 and (not fields[1] or 'memory' in fields[1].split(',')):
            groups.append((2 if not fields[1] else 1, PurePosixPath(fields[2])))
    for row in mounts.splitlines():
        left, separator, right = row.partition(' - ')
        before, after = left.split(), right.split()
        if not separator or len(before) < 5 or len(after) < 3:
            continue
        version = 2 if after[0] == 'cgroup2' else 1 if after[0] == 'cgroup' and 'memory' in after[2].split(',') else None
        if version is None:
            continue
        mount_root, mount_point = PurePosixPath(unescape(before[3])), PurePosixPath(unescape(before[4]))
        directories.add((str(mount_point), version))
        for group_version, group in groups:
            if version != group_version:
                continue
            if not group.is_absolute() or '..' in group.parts:
                notes.append('Cgroup membership cannot safely map inside exposed mount: ' + str(group))
                continue
            try:
                relative = group.relative_to(mount_root)
            except ValueError:
                notes.append('Cgroup membership outside exposed mount root: ' + str(group))
                continue
            directory = mount_point / relative
            while True:
                directories.add((str(directory), version))
                if directory == mount_point:
                    break
                directory = directory.parent
    return sorted(directories), notes


def memory_snapshot():
    files = {path: read_observed(path) for path in ('/proc/meminfo', '/proc/self/limits',
              '/proc/self/cgroup', '/proc/self/mountinfo', '/proc/pressure/memory')}
    directories, notes = cgroup_directories(files)
    pairs = []
    for directory, version in directories:
        for name in V2_FILES if version == 2 else V1_FILES:
            path = str(Path(directory) / name)
            files[path] = read_observed(path)
        limit, current = ('memory.max', 'memory.current') if version == 2 else ('memory.limit_in_bytes', 'memory.usage_in_bytes')
        pairs.append({'version': version, 'limit': str(Path(directory) / limit),
                      'current': str(Path(directory) / current)})
    return {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'monotonic_ns': time.monotonic_ns(), 'files': files, 'cgroup_pairs': pairs,
            'discovery_notes': notes, 'scope': 'Actual exposed reads only; hidden limits unknown. Namespace-visible process counts are NOT host memory usage.'}


def check_memory(snapshot, declared):
    files = snapshot['files']
    text = files['/proc/meminfo']
    if not isinstance(text, str):
        raise ValueError('MemAvailable observation unavailable')
    parsed = {}
    for key in ('MemTotal', 'MemAvailable'):
        rows = re.findall(r'^' + key + r':\s+([0-9]+) kB\s*$', text, re.MULTILINE)
        if len(rows) != 1:
            raise ValueError('Missing, duplicate or malformed /proc/meminfo ' + key)
        parsed[key] = int(rows[0]) * 1024
    if not 0 < parsed['MemAvailable'] <= parsed['MemTotal']:
        raise ValueError('Impossible observed MemAvailable/MemTotal values')
    minimum = declared['min_mem_available_bytes']
    if minimum > parsed['MemTotal']:
        raise ValueError('Declared admission threshold exceeds observed MemTotal')
    if parsed['MemAvailable'] < minimum:
        raise ValueError('Observed MemAvailable is below the declared admission threshold')
    limits = files['/proc/self/limits']
    if not isinstance(limits, str) or not limits.startswith('Limit'):
        raise ValueError('/proc/self/limits unavailable or malformed')
    process_limits = {}
    for name in ('Max address space', 'Max resident set'):
        rows = re.findall(r'^' + name + r'[ \t]+(unlimited|[0-9]+)[ \t]+(unlimited|[0-9]+)[ \t]+bytes[ \t]*$', limits, re.MULTILINE)
        if len(rows) != 1:
            raise ValueError('Missing, duplicate or malformed /proc/self/limits ' + name)
        soft, hard = (None if value == 'unlimited' else int(value) for value in rows[0])
        if hard is not None and (soft is None or soft > hard):
            raise ValueError('Impossible process soft/hard limit: ' + name)
        process_limits[name] = {'soft_bytes': soft, 'hard_bytes': hard}
    address_soft = process_limits['Max address space']['soft_bytes']
    if address_soft is not None and address_soft < declared['sampled_group_rss_stop_bytes']:
        raise ValueError('Process address-space soft limit is below the declared RSS envelope')
    headroom = []
    for pair in snapshot['cgroup_pairs']:
        limit, current = files[pair['limit']], files[pair['current']]
        if isinstance(current, str) and not re.fullmatch(r'[0-9]+\s*', current):
            raise ValueError('Malformed exposed cgroup current: ' + pair['current'])
        if not isinstance(limit, str):
            continue
        if limit.strip() == 'max' and pair['version'] == 2:
            continue
        if not re.fullmatch(r'[0-9]+\s*', limit) or int(limit) <= 0:
            raise ValueError('Malformed/nonpositive exposed cgroup limit: ' + pair['limit'])
        if not isinstance(current, str):
            raise ValueError('Finite exposed cgroup limit has unavailable current usage: ' + pair['current'])
        remaining = int(limit) - int(current)
        headroom.append({'limit_path': pair['limit'], 'current_path': pair['current'],
                         'limit_bytes': int(limit), 'current_bytes': int(current), 'headroom_bytes': remaining})
        if remaining < minimum:
            raise ValueError('Exposed cgroup headroom is below the declared admission threshold: ' + pair['limit'])
    return {'mem_total_bytes': parsed['MemTotal'], 'mem_available_bytes': parsed['MemAvailable'],
            'exposed_cgroup_headroom': headroom, 'process_limits': process_limits,
            'limits_note': 'Raw self limits are recorded. Linux RLIMIT_RSS is not an enforced RSS cap; no hidden-limit or hard-RSS guarantee is inferred.'}


class AdmissionRejected(RuntimeError):
    def __init__(self, message, *, run_dir, campaign_dir, status_path, index, result):
        super().__init__(message)
        self.run_dir, self.campaign_dir, self.status_path = run_dir, campaign_dir, status_path
        self.index, self.result = index, result


class AdmissionWrapper:
    def __init__(self, base, plan_path):
        self.base, self.plan_path = base, Path(plan_path).resolve(strict=True)
        self.plan = json.loads(self.plan_path.read_text())
        self.binding = validate_plan(self.plan)
        self.plan_identity = identity(self.plan_path)
        self.original_run_one = base.run_one

    def run_one(self, spec, run_dir, campaign_dir, env, cpus, status, status_path, index,
                sample_s, registry=None, expected_final=None):
        started = time.monotonic()
        record = {'schema': 'observed-memory-admission-record-v1', 'run_id': spec['id'],
                  'offer_index': index, 'plan': self.plan_identity, 'binding': self.binding,
                  'offered_spec_sha256': canonical_hash(spec),
                  'offered_memory_controls': {'supervisor_rss_safety_stop_bytes': spec.get('rss_safety_stop_bytes'),
                                              'per_run_override': spec.get('memory_admission')},
                  'snapshot': memory_snapshot(), 'execution_performed': False,
                  'claim': 'Pre-prepare observation only; preparation and execution may race changing memory availability. No new hard RSS guarantee.'}
        try:
            record['observed_wrapper'] = identity(WRAPPER_PATH)
            record['observed_base_runner'] = identity(BASE_PATH)
            if identity(self.plan_path) != self.plan_identity:
                raise ValueError('Plan changed after wrapper initialization')
            if validate_plan(self.plan) != self.binding:
                raise ValueError('Wrapper/base/admission policy binding changed')
            declared = envelope(spec, self.base.campaign_gate)
            record['declared_envelope'] = declared
            record['observed_admission'] = check_memory(record['snapshot'], declared)
            record['decision'] = 'admitted'
        except (OSError, ValueError, TypeError, KeyError) as exc:
            record.update(decision='rejected', rejection=f'{type(exc).__name__}: {exc}')
        record['admission_elapsed_s'] = time.monotonic() - started
        record['record_sha256'] = canonical_hash(record)
        admission_path = Path(run_dir) / 'memory-admission.json'
        create_json(admission_path, record)
        ref = identity(admission_path)
        status['memory_admission_wrapper'] = self.binding
        if record['decision'] == 'rejected':
            result = {'id': spec['id'], 'ok': False, 'outcome': 'prelaunch_memory_admission_rejected',
                      'execution_performed': False, 'returncode': None, 'timed_out': False,
                      'elapsed_wall_s': None, 'launch_to_first_available_answer_ns': None,
                      'memory_admission': ref, 'rejection': record['rejection'],
                      'finished_utc': self.base.utc()}
            create_json(Path(run_dir) / 'result.json', result)
            raise AdmissionRejected(record['rejection'], run_dir=Path(run_dir), campaign_dir=Path(campaign_dir),
                                    status_path=Path(status_path), index=index, result=result)
        # Exact base behavior, arguments, registry and final-seal context are retained.
        result = self.original_run_one(spec, run_dir, campaign_dir, env, cpus, status, status_path,
                                       index, sample_s, registry, expected_final=expected_final)
        result['memory_admission'] = ref
        self.base.write_json(Path(run_dir) / 'result.json', result)
        return result

    def finalize_rejection(self, rejected):
        status = json.loads(rejected.status_path.read_text())
        status.update(state='prelaunch_memory_admission_rejected', ok=False, active_run=None,
                      active_index=None, updated_utc=self.base.utc(),
                      memory_admission_wrapper=self.binding,
                      rejected_offers=[{'id': rejected.result['id'], 'index': rejected.index,
                                        'outcome': rejected.result['outcome'],
                                        'result': str(rejected.run_dir / 'result.json')}],
                      unstarted_offers=[{'id': spec['id'], 'index': index,
                                         'reason': 'not_offered_after_memory_admission_rejection'}
                                        for index, spec in enumerate(self.plan['runs']) if index > rejected.index])
        self.base.write_json(rejected.status_path, status)
        print(json.dumps({'state': status['state'], 'rejected_offer': status['rejected_offers'][0],
                          'unstarted_offer_count': len(status['unstarted_offers'])}), flush=True)
        return 1


def main():
    base = load_base()
    argv = sys.argv[1:]
    owner = None
    if argv and argv[0] in ('run', 'seal-finalists', 'validate-seal') and not any(x in argv for x in ('-h', '--help')):
        plans = base.campaign_gate.flags(argv, '--plan')
        if len(plans) != 1:
            raise ValueError('Exactly one --plan is required')
        owner = AdmissionWrapper(base, plans[0])
        base.run_one = owner.run_one
    try:
        return base.main()
    except AdmissionRejected as exc:
        if owner is None:
            raise
        return owner.finalize_rejection(exc)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
