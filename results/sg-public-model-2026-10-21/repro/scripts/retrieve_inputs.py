#!/usr/bin/env python3
"""Explicit opt-in HTTPS retrieval; exact size and SHA256 or fail closed. No data is bundled."""
import argparse, hashlib, json, os, urllib.request, urllib.parse
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]

class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme != 'https':
            raise ValueError('refusing non-HTTPS redirect')
        return super().redirect_request(request, fp, code, msg, headers, new_url)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.environ.get('SG_ROOT'))
    parser.add_argument('--accept-provider-terms', action='store_true', help='You reviewed and will comply with provider terms; this does not grant redistribution rights')
    parser.add_argument('--only', choices=['gtfs', 'osm'])
    parser.add_argument('--verify-only', action='store_true', help='Never access the network')
    args = parser.parse_args()
    if not args.root:
        parser.error('set SG_ROOT or pass --root')
    if not args.verify_only and not args.accept_provider_terms:
        parser.error('review the provider terms and explicitly pass --accept-provider-terms before download')
    root = Path(args.root).resolve()
    opener = urllib.request.build_opener(HTTPSOnly())
    for item in json.loads((BUNDLE / 'SOURCE_PINS.json').read_text())['source_inputs']:
        if args.only and args.only != item['id']:
            continue
        destination = root / item['destination']
        if destination.exists():
            if destination.stat().st_size != item['bytes'] or digest(destination) != item['sha256']:
                raise ValueError('existing file differs; refusing replacement: ' + item['id'])
            print(item['id'] + ': existing bytes verified')
            continue
        if args.verify_only:
            raise FileNotFoundError('missing pinned input: ' + item['id'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + '.partial')
        created = False
        try:
            output = partial.open('xb')
            created = True
            with output, opener.open(item['url'], timeout=60) as response:
                if urllib.parse.urlsplit(response.geturl()).scheme != 'https':
                    raise ValueError('non-HTTPS response')
                size = 0
                h = hashlib.sha256()
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    size += len(block)
                    if size > item['bytes']:
                        raise ValueError('input exceeds exact pinned size')
                    h.update(block)
                    output.write(block)
            if size != item['bytes'] or h.hexdigest() != item['sha256']:
                raise ValueError('download size/SHA256 mismatch; refusing input')
            # Hard link is an atomic create-only publication, never replacement.
            os.link(partial, destination)
            partial.unlink()
            print(item['id'] + ': downloaded and exact bytes verified')
        except BaseException:
            # Do not remove an existing partial file owned by another invocation.
            if created and partial.exists():
                partial.unlink()
            raise

if __name__ == '__main__':
    main()
