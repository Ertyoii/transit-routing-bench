#!/usr/bin/env python3
"""Reconstruct frozen source trees from public bases plus complete bundled patches."""
import argparse, hashlib, json, os, subprocess
from pathlib import Path
from sourcehash import source_hash

BUNDLE = Path(__file__).resolve().parents[1]

def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.environ.get('SG_ROOT'))
    parser.add_argument('--variant', required=True, help='baseline, auxiliary-source-v2, or a candidate id from SOURCE_PINS.json')
    parser.add_argument('--local-bases', help='Optional offline directory containing routing and bench git repositories')
    args = parser.parse_args()
    if not args.root:
        parser.error('set SG_ROOT or pass --root')
    pins = json.loads((BUNDLE / 'SOURCE_PINS.json').read_text())
    expected_repositories = {
        'routing': 'https://github.com/Ertyoii/transit-routing-go.git',
        'bench': 'https://github.com/Ertyoii/transit-routing-bench.git',
    }
    for kind, repository_url in expected_repositories.items():
        if pins['bases'][kind]['repository_url'] != repository_url:
            raise ValueError('unexpected public base repository URL: ' + kind)
    selected = next((x for x in pins['candidates'] if x['id'] == args.variant), None)
    overlay = next((x for x in pins.get('diagnostic_overlays', []) if x['id'] == args.variant), None)
    if args.variant not in {'baseline', 'auxiliary-source-v2'} and selected is None and overlay is None:
        parser.error('unknown variant')
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for kind in ('routing', 'bench'):
        base = pins['bases'][kind]
        name = kind if args.variant == 'baseline' else kind + '-' + args.variant
        destination = root / name
        if destination.exists():
            raise ValueError('refusing existing checkout: ' + name)
        source = str(Path(args.local_bases).resolve() / kind) if args.local_bases else base['repository_url']
        run('git', 'clone', '--no-checkout', '--no-hardlinks', source, str(destination))
        run('git', 'checkout', '--detach', base['commit'], cwd=destination)
        item = selected[kind] if selected else None
        expected_tree = item['tree'] if item else base['tree']
        if args.variant == 'auxiliary-source-v2' and kind == 'bench':
            item = pins['auxiliary']
            expected_tree = item['result_tree']
        if overlay and kind == overlay['repository']:
            item = overlay
            expected_tree = item['result_tree']
        if item:
            patch = BUNDLE / item['complete_patch']
            if hashlib.sha256(patch.read_bytes()).hexdigest() != item['patch_sha256']:
                raise ValueError('patch hash mismatch')
            run('git', 'apply', '--index', '--binary', str(patch), cwd=destination)
        tree = run('git', 'write-tree', cwd=destination).decode().strip()
        if tree != expected_tree:
            raise ValueError('tree mismatch: ' + name)
        source_digest = source_hash(destination)
        if item and source_digest != item['source_sha256']:
            raise ValueError('source digest mismatch: ' + name)
        records.append({'directory': name, 'base_commit': base['commit'], 'tree': tree, 'source_sha256': source_digest, 'candidate_commit_recreated': False})
    print(json.dumps({'source_trees': records, 'note': 'A source-identical patched tree is not a recreated candidate commit. No build or benchmark was executed.'}, indent=2))

if __name__ == '__main__':
    main()
