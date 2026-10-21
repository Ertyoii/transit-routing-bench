#!/usr/bin/env python3
"""Offline patch replay using temporary Git indexes/objects. No checkout/build/run."""
import argparse, hashlib, json, os, subprocess, tempfile
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]

def call(*args, env=None):
    return subprocess.check_output(args, env=env, stderr=subprocess.PIPE)

def verify(base_root):
    pins = json.loads((BUNDLE / 'SOURCE_PINS.json').read_text())
    jobs = []
    for candidate in pins['candidates']:
        for kind in ('routing', 'bench'):
            item = candidate[kind]
            jobs.append((kind, candidate['id'], item['complete_patch'], item['patch_sha256'], item['base_commit'], item['tree']))
    aux = pins['auxiliary']
    jobs.append(('bench', 'auxiliary-source-v2', aux['complete_patch'], aux['patch_sha256'], aux['base_commit'], aux['result_tree']))
    for overlay in pins.get('diagnostic_overlays', []):
        jobs.append((overlay['repository'], overlay['id'], overlay['complete_patch'], overlay['patch_sha256'], overlay['base_commit'], overlay['result_tree']))
    verified = []
    for kind, label, patch, expected_hash, base, expected_tree in jobs:
        repo = Path(base_root) / kind
        patch = BUNDLE / patch
        if hashlib.sha256(patch.read_bytes()).hexdigest() != expected_hash:
            raise ValueError('patch byte hash mismatch: ' + patch.name)
        common = call('git', '-C', str(repo), 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip()
        with tempfile.TemporaryDirectory(prefix='sg-source-replay-') as directory:
            directory = Path(directory)
            bare = directory / 'repo.git'
            call('git', 'init', '--bare', '--quiet', str(bare))
            env = dict(os.environ, GIT_ALTERNATE_OBJECT_DIRECTORIES=str(Path(common) / 'objects'), GIT_INDEX_FILE=str(directory / 'index'))
            def git(*args):
                return call('git', '--git-dir=' + str(bare), *args, env=env)
            git('read-tree', base)
            git('apply', '--cached', '--check', '--binary', str(patch))
            git('apply', '--cached', '--binary', str(patch))
            actual = git('write-tree').decode().strip()
            if actual != expected_tree:
                raise ValueError('replay tree mismatch: ' + label)
            verified.append({'repository': kind, 'variant': label, 'tree': actual, 'patch_sha256': expected_hash})
    return verified

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-root', required=True, help='Directory containing local routing and bench repositories with pinned base objects')
    args = parser.parse_args()
    print(json.dumps({'schema': 'sg-offline-replay-v1', 'checks': verify(args.base_root)}, indent=2))
