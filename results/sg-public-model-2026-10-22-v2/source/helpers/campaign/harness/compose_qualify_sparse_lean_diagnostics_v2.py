#!/usr/bin/env python3
"""Create-only future quiet-window composition and scoped qualification.

STATIC STAGING ONLY until the campaign owner explicitly allocates the lock.
No real dataset, real router, campaign process, or CSA algorithm is executed.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT.parent / 'setup'
GO = SETUP / 'toolchain/go/bin/go'
DELTA = ROOT / 'source-evidence/sparse-lean-diagnostics-staging-v2'
SOURCE_BASE = ROOT / 'src/routing-tb-answer-ties'
BENCH_BASE = ROOT / 'src/bench-tb-answer-ties'
QUALITY = ROOT / 'src/routing-noncsa-quality'
VP = Path('vendor/github.com/ertyoii/transit-routing-go')
DRIVER_FILES = ['adapters.go', 'scoped.go', 'main.go', 'diagnostics.go', 'diagnostics_test.go']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    with path.open('x') as out:
        json.dump(value, out, sort_keys=True, indent=2)
        out.write('\n')

def run(args, cwd, env, log):
    with log.open('x') as out:
        out.write('COMMAND ' + json.dumps([str(x) for x in args]) + '\n')
        out.flush()
        subprocess.run([str(x) for x in args], cwd=cwd, env=env,
                       stdout=out, stderr=subprocess.STDOUT, check=True)

def static_preflight():
    required = [SOURCE_BASE / 'ultra/sparse.go', SOURCE_BASE / 'tripbased/capped_answer_walk_ties.go',
                BENCH_BASE / 'cmd/familybench/main.go', BENCH_BASE / 'cmd/familybench/scoped.go',
                BENCH_BASE / VP / 'ultra/local_walk_ties.go',
                DELTA / 'ultra/sparse_cost.go', DELTA / 'ultra/sparse_cost_test.go',
                DELTA / 'nativeinputprobe/probe.go', QUALITY / 'ultra/local_walk_ties.go',
                QUALITY / 'ultra/local_walk_ties_test.go']
    required += [DELTA / 'familybench' / name for name in DRIVER_FILES]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    if (QUALITY / 'ultra/local_walk_ties.go').read_bytes() != (BENCH_BASE / VP / 'ultra/local_walk_ties.go').read_bytes():
        raise ValueError('Previously qualified ULTRA local-tie source differs from the TB vendor composition')
    for target in [BENCH_BASE / 'nativeinputprobe', SOURCE_BASE / 'ultra/local_walk_ties.go',
                   SOURCE_BASE / 'ultra/local_walk_ties_test.go', SOURCE_BASE / 'ultra/sparse_cost.go']:
        if target.exists():
            raise FileExistsError('Expected new composition target already exists in its base: ' + str(target))
    main = (DELTA / 'familybench/main.go').read_text()
    if main.index('if *inputOnly {') > main.index('ctx, cancel := context.WithTimeout(context.Background(), *prepTimeout)'):
        raise ValueError('Actual-driver input-only branch must precede all native construction')
    if 'trip_based_capped_answer_walk_ties' not in (DELTA / 'familybench/scoped.go').read_text():
        raise ValueError('New TB answer-tie adapter must be retained')
    if 'raptor_early_local_walk_ties' not in (DELTA / 'familybench/adapters.go').read_text():
        raise ValueError('Previously qualified RAPTOR local ties must be retained')
    return {str(path.relative_to(ROOT)): sha(path) for path in required}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quiet-window-open', action='store_true')
    parser.add_argument('--prefix', default='sparse-lean-v2')
    args = parser.parse_args()
    if not args.quiet_window_open:
        raise SystemExit('Explicit campaign quiet-window allocation is required')
    if not args.prefix or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.prefix):
        raise ValueError('Use a fresh lowercase, numeric, hyphenated prefix')
    lock = (SETUP / 'campaign.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX)  # Authorized offline jobs wait, never EAGAIN-as-failure.
    anchors = static_preflight()  # Validate every optional/required source before any tree is copied.
    source = ROOT / 'src' / ('routing-' + args.prefix)
    bench = ROOT / 'src' / ('bench-' + args.prefix)
    evidence = ROOT / 'source-evidence' / args.prefix
    binary = ROOT / 'bin' / ('familybench-' + args.prefix)
    for target in [source, bench, evidence, binary]:
        if target.exists():
            raise FileExistsError('Create-only target exists; preserve it and choose a new prefix: ' + str(target))
    evidence.mkdir()
    write(evidence / 'COMPOSITION_INTENT.json', {
        'status': 'composition_started_not_qualified', 'script': str(Path(__file__).resolve()),
        'source_base': str(SOURCE_BASE), 'bench_base': str(BENCH_BASE), 'anchor_files': anchors,
        'scope': 'Diagnostics-only API/driver; native proof construction, original Preparation ownership and all kernels unchanged. No CSA algorithm execution.'})
    env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off', GOPROXY='off', GOSUMDB='off',
               GOMAXPROCS='2', GOCACHE=str(SETUP / 'cache/go-build'), GOMODCACHE=str(SETUP / 'cache/go-mod'))
    env['PATH'] = str(GO.parent) + os.pathsep + env.get('PATH', '')
    try:
        ignore = shutil.ignore_patterns('.git', '.cache', 'artifacts', '__pycache__')
        shutil.copytree(SOURCE_BASE, source, ignore=ignore)
        shutil.copytree(BENCH_BASE, bench, ignore=ignore)
        # The routing TB tree has bounded previous-best preparation and the TB
        # answer-tie API. Its bench already includes the qualified ULTRA local
        # ties, so add those exact two source files explicitly, not an older tree.
        for name in ['local_walk_ties.go', 'local_walk_ties_test.go']:
            target = source / 'ultra' / name
            if target.exists():
                raise FileExistsError('Unexpected source overlay target: ' + str(target))
            shutil.copy2(QUALITY / 'ultra' / name, target)
        for name in ['sparse_cost.go', 'sparse_cost_test.go']:
            shutil.copy2(DELTA / 'ultra' / name, source / 'ultra' / name)
        for name in DRIVER_FILES:
            shutil.copy2(DELTA / 'familybench' / name, bench / 'cmd/familybench' / name)
        (bench / 'nativeinputprobe').mkdir(exist_ok=False)
        shutil.copy2(DELTA / 'nativeinputprobe/probe.go', bench / 'nativeinputprobe/probe.go')
        files = [source / 'ultra/sparse_cost.go', source / 'ultra/sparse_cost_test.go']
        files += [bench / 'cmd/familybench' / name for name in DRIVER_FILES]
        files += [bench / 'nativeinputprobe/probe.go']
        run([GO.parent / 'gofmt', '-w', *files], ROOT, env, evidence / 'gofmt.log')
        shutil.copy2(source / 'ultra/sparse_cost.go', bench / VP / 'ultra/sparse_cost.go')
        # Every pre-existing native source/vendor file must remain byte-identical.
        for original in SOURCE_BASE.rglob('*.go'):
            if '.git' in original.parts or '.cache' in original.parts:
                continue
            if original.read_bytes() != (source / original.relative_to(SOURCE_BASE)).read_bytes():
                raise ValueError('Original native source changed: ' + str(original))
        for original in (BENCH_BASE / VP).rglob('*'):
            if original.is_file() and original.read_bytes() != (bench / VP / original.relative_to(BENCH_BASE / VP)).read_bytes():
                raise ValueError('Original native vendor file changed: ' + str(original))
        lockpath = bench / 'routing.lock.json'
        routing_lock = json.loads(lockpath.read_text())
        routing_files = {str(path.relative_to(bench / VP)): sha(path)
                         for path in sorted((bench / VP).rglob('*')) if path.is_file()}
        routing_lock.update(files=routing_files,
            source_sha256=hashlib.sha256(json.dumps(routing_files, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            origin='TB-answer-tie common source plus NEW Sparse scalar cost summary; previous native vendor bytes unchanged. Full same-index proof evidence retained after serving; diagnostics-only, not a query-kernel speedup.')
        lockpath.write_text(json.dumps(routing_lock, sort_keys=True, indent=2) + '\n')
        run(['git', 'init', '-b', args.prefix], bench, env, evidence / 'git-init.log')
        run(['git', 'add', '--all'], bench, env, evidence / 'git-add.log')
        run(['git', '-c', 'commit.gpgsign=false', '-c', 'user.name=Cloud auxiliary build',
             '-c', 'user.email=local-build@assistant.invalid', 'commit', '-m',
             'Compose common Sparse lean diagnostics without native kernel changes'],
            bench, env, evidence / 'git-commit.log')
        run([GO, 'test', '-buildvcs=false', './ultra', '-run',
             '^Test(SparseCost|CappedDenseFrozenSparseCertificates)', '-count=1', '-timeout=180s'],
            source, env, evidence / 'source-counts-ownership-native-parity.log')
        run([GO, 'test', '-race', '-buildvcs=false', './ultra', '-run',
             '^TestSparseCostConcurrent', '-count=1', '-timeout=180s'],
            source, env, evidence / 'source-concurrency-race.log')
        run([GO, 'test', '-buildvcs=false', '-mod=vendor', './cmd/familybench', '-run',
             '^Test(SparseDiagnostics|TBAnswerWalkTiesNamedAdapter|LocalWalkTiesScopedAdapters|ResponsePublisher)',
             '-count=1', '-timeout=180s'], bench, env, evidence / 'driver-primary-parity-serving-clock.log')
        run([GO, 'test', '-buildvcs=false', '-mod=vendor', './cmd/inputpreflight', '-run',
             '^TestPreflightTBAnswerWalkTiesExactConfig', '-count=1', '-timeout=90s'],
            bench, env, evidence / 'preflight-tb-adapter-preserved.log')
        fingerprint = subprocess.check_output([str(GO), 'run', '-buildvcs=false', '-mod=vendor', './cmd/sourcehash'],
                                             cwd=bench, env=env, text=True).strip()
        run([GO, 'build', '-buildvcs=false', '-mod=vendor', '-trimpath', '-ldflags',
             '-X github.com/ertyoii/transit-routing-bench/experiment.BuildSourceSHA256=' + fingerprint,
             '-o', binary, './cmd/familybench'], bench, env, evidence / 'build.log')
        source_files = {str(path.relative_to(source)): sha(path) for path in sorted(source.rglob('*')) if path.is_file()}
        write(evidence / 'QUALIFIED_SOURCE.json', {
            'status': 'QUALIFIED_SYNTHETIC_ONLY_NOT_MEASURED', 'source': str(source), 'bench': str(bench),
            'source_hash': fingerprint, 'routing_file_list_sha256': routing_lock['source_sha256'],
            'native_source_files': source_files, 'binary': {'path': str(binary), 'sha256': sha(binary)},
            'scope': 'Original native source/vendor bytes preserved; complete scalar/count diagnostics, full same-index proof evidence after serving. No real-model run, no query-kernel claim, no CSA execution.'})
        print(str(evidence / 'QUALIFIED_SOURCE.json'))
    except Exception as error:
        write(evidence / 'FAILURE.json', {'status': 'failed_partial_targets_preserved',
              'error': repr(error), 'source': str(source), 'bench': str(bench), 'binary': str(binary),
              'next_action': 'Diagnose preserved logs and use a materially repaired revision/fresh prefix; never overwrite failed artifacts.'})
        raise

if __name__ == '__main__':
    main()
