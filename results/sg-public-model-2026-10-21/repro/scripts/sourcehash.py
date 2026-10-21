#!/usr/bin/env python3
"""Python equivalent of bench/experiment/source.go; no compiler or router."""
from pathlib import Path
import argparse, hashlib, os

def source_hash(root):
    root = Path(root)
    paths = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {'.git', '.cache', 'artifacts'}]
        for name in names:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if name.endswith('.go') or name in {'go.mod', 'routing.lock.json'} or rel == 'vendor/modules.txt':
                paths.append((rel, path))
    if not paths:
        raise ValueError('no Go source files')
    digest = hashlib.sha256()
    for rel, path in sorted(paths):
        content = path.read_bytes()
        digest.update(f'{len(rel.encode())}:{rel}:{len(content)}:'.encode())
        digest.update(content)
    return digest.hexdigest()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    print(source_hash(parser.parse_args().root))
