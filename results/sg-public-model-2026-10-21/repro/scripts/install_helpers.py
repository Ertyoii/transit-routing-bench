#!/usr/bin/env python3
"""Install portable helper snapshots create-only; expand only JSON root placeholders."""
import argparse, hashlib, json, os, shutil
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.environ.get('SG_ROOT'))
    args = parser.parse_args()
    if not args.root:
        parser.error('set SG_ROOT or pass --root')
    root = Path(args.root).resolve()
    source = BUNDLE / 'helpers'
    paths = [p for p in sorted(source.rglob('*')) if p.is_file()]
    for path in paths:
        if (root / path.relative_to(source)).exists():
            raise ValueError('refusing existing helper: ' + str(path.relative_to(source)))
    records = []
    for path in paths:
        rel = path.relative_to(source)
        content = path.read_bytes()
        if path.suffix == '.json':
            obj = json.loads(content)
            def expand(value):
                if isinstance(value, str):
                    return value.replace('${SG_ROOT}', str(root))
                if isinstance(value, dict):
                    return {k: expand(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [expand(v) for v in value]
                return value
            if b'${SG_ROOT}' in content:
                content = (json.dumps(expand(obj), indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as output:
            output.write(content)
        if path.suffix == '.sh':
            destination.chmod(0o755)
        records.append({'path': rel.as_posix(), 'sha256': hashlib.sha256(content).hexdigest()})
    report = root / 'REPRODUCED_HELPERS.json'
    with report.open('x') as output:
        json.dump({'schema': 'sg-materialized-helpers-v1', 'files': records}, output, indent=2)
        output.write('\n')
    print('Installed ' + str(len(records)) + ' helper files; original historical seals must not be reused.')

if __name__ == '__main__':
    main()
