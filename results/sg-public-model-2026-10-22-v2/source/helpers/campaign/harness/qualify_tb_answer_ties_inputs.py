#!/usr/bin/env python3
"""Create-only input qualification. No familybench/router is executed."""
import argparse
import fcntl
import json
import subprocess
from pathlib import Path

import campaign_gate
import run_campaign as runner

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n')


def ident(path):
    return runner.file_identity(Path(path).resolve(strict=True))


def flag(argv, name):
    values = campaign_gate.flags(argv, name)
    if len(values) != 1:
        raise ValueError(f'Expected exactly one {name}')
    return values[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--quiet-window-open', action='store_true')
    a = p.parse_args()
    if not a.quiet_window_open:
        raise ValueError('Explicit quiet window is required')
    lock = (runner.LEGACY_SETUP / 'campaign.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX)
    a.out.mkdir(parents=True, exist_ok=False)
    plan_path = a.plan.resolve(strict=True)
    plan = json.loads(plan_path.read_text())
    build_path = ROOT / 'source-evidence/TB_ANSWER_WALK_TIES_BUILD.json'
    build = json.loads(build_path.read_text())
    env = runner.campaign_environment()
    registry = campaign_gate.load_registry(plan, plan_path.parent)
    write(a.out / 'INTENT.json', {
        'scope': 'Strict native-point input parser plus actual runner envelope only; no native router/search/preparation constructor.',
        'plan': ident(plan_path), 'script': ident(Path(__file__)),
        'build': ident(build_path),
        'limitation': 'Main familybench parser/seed/checker/stream identity is inherited from accepted v3 source and bound in TB source qualification. This helper invokes the separately built inputpreflight consumer, not a new familybench input-only mode.',
    })
    for relative, expected in build['binaries'].items():
        actual = ident(ROOT / relative)
        if actual['sha256'] != expected['sha256'] or actual['bytes'] != expected['bytes']:
            raise ValueError('Frozen TB binary changed')
    requests = {}
    prepared = []
    for spec in plan['runs']:
        metadata, argv, _, _, _, _ = runner.prepare_run(
            spec, a.out / '__not_launched__' / spec['id'],
            a.out / '__no_campaign__', env, '0-3', .2, registry,
            inspect_heldout=False)
        if metadata['workload_gate']['heldout_detected']:
            raise ValueError('Held-out input in tune plan')
        if any(w['classification'] != 'tune' for w in metadata['workload_gate']['workloads']):
            raise ValueError('Only registered tune requests are allowed')
        if metadata['sources_before'][0]['go_source_hash_sha256'] != build['build_source_sha256']:
            raise ValueError('Frozen build source changed')
        request = {
            'id': spec['window'] + '-' + flag(argv, '-algorithm'),
            'dataset': flag(argv, '-dataset'), 'queries': flag(argv, '-queries'),
            'schema': 'point', 'algorithm': flag(argv, '-algorithm'),
            'preferences': flag(argv, '-preference-scenarios'),
            'scoped_config': flag(argv, '-scoped-config'),
        }
        requests[(request['dataset'], request['algorithm'])] = request
        prepared.append(metadata)
    if len(prepared) != 16 or len(requests) != 8:
        raise ValueError('Expected 16 process envelopes and 8 dataset/adapter requests')
    reports = []
    datasets = sorted({r['dataset'] for r in requests.values()})
    for index, dataset in enumerate(datasets):
        selected = [r for r in requests.values() if r['dataset'] == dataset]
        manifest = a.out / f'parser-{index}.requests.json'
        write(manifest, selected)
        command = ['/usr/bin/taskset', '-c', '0-3', str(ROOT / 'bin/inputpreflight-tb-answer-ties'), '-manifest', str(manifest)]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=180, check=False)
        (a.out / f'parser-{index}.stdout.json').write_text(result.stdout)
        (a.out / f'parser-{index}.stderr.txt').write_text(result.stderr)
        if result.returncode != 0:
            raise ValueError(f'Input-only parser returned {result.returncode}; see retained output')
        # Existing preflight emits one JSON object per request, not a wrapper.
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != len(selected) or not all(r['accepted'] for r in rows) or {r['id'] for r in rows} != {r['id'] for r in selected}:
            raise ValueError('Strict input parser did not accept every planned adapter')
        reports.append({'command': command, 'manifest': ident(manifest), 'stdout': ident(a.out / f'parser-{index}.stdout.json'), 'stderr': ident(a.out / f'parser-{index}.stderr.txt'), 'rows': rows})
    # Verify before/after identities without executing any familybench binary.
    for relative, expected in build['binaries'].items():
        if ident(ROOT / relative)['sha256'] != expected['sha256']:
            raise ValueError('Binary changed during qualification')
    write(a.out / 'QUALIFICATION.json', {
        'status': 'PASS_INPUT_ONLY_NO_ROUTER', 'router_executed': False,
        'plan': ident(plan_path), 'build': ident(build_path),
        'intent': ident(a.out / 'INTENT.json'),
        'native_schema_requests': len(requests), 'runner_envelopes': len(prepared),
        'parser_reports': reports, 'actual_prepare_run_metadata': prepared,
        'qualifier_script': ident(Path(__file__)),
        'input_parser_boundary': 'Inputpreflight validates strict bytes/query/config schemas. Constructor-only resource positivity remains independently tested in the actual named adapter; no constructor called here.',
    })
    print(json.dumps({'status': 'PASS_INPUT_ONLY_NO_ROUTER', 'report': str(a.out / 'QUALIFICATION.json'), 'envelopes': len(prepared), 'requests': len(requests)}))


if __name__ == '__main__':
    main()
