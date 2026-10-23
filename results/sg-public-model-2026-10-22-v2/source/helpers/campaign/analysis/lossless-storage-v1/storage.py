#!/usr/bin/env python3
"""Create-only operational preservation of admitted FUTURE evidence, not scoring.

CLI operations use the existing authoritative campaign flock. They do not run
routers/evaluators, choose quality rows, or alter any accepted result bytes.
A read-only gzip plus manifest is recoverable preservation, not filtering.
"""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import uuid

CAMPAIGN_LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
SCHEMA = 'prospective-lossless-storage-v1'
CHUNK = 1024 * 1024
REQUIRED_BINDINGS = {'plan_sha256', 'source_sha256', 'input_sha256', 'dataset_sha256'}
ROLES = {'proof-summary', 'proof-sidecar', 'redundant-metrics'}

class Refusal(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise Refusal(message)


def encoded(obj):
    return (json.dumps(obj, sort_keys=True, indent=2) + '\n').encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def canonical(value):
    p = Path(value)
    require(p.is_absolute(), 'Every admitted path must be absolute')
    require(str(p) == os.path.abspath(str(p)), 'Noncanonical path')
    require(p.resolve(strict=False) == p, 'Symlink path or ancestor refused')
    return p


def exists(p):
    return os.path.lexists(p)


def absent(p):
    require(not exists(p), 'Create-only destination already exists: ' + str(p))


def contained(root, p):
    require(p != root and root in p.parents, 'Path outside campaign root: ' + str(p))


def fingerprint(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)


@contextlib.contextmanager
def regular_reader(p):
    canonical(str(p))
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), 'Not a regular file: ' + str(p))
        require(before.st_nlink == 1, 'Hard-linked evidence refused')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            yield f, before
            require(fingerprint(os.fstat(fd)) == fingerprint(before), 'File changed while reading')
            require(fingerprint(os.lstat(p)) == fingerprint(before), 'Path changed while reading')
    finally:
        os.close(fd)


def digest_file(p):
    h, count = hashlib.sha256(), 0
    with regular_reader(p) as (f, _):
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
            count += len(block)
    return h.hexdigest(), count


def read_doc(p):
    with regular_reader(p) as (f, _):
        data = f.read()
    return json.loads(data), sha(data)


@contextlib.contextmanager
def quiet(lock_path=CAMPAIGN_LOCK):
    # Never create or truncate the authoritative lock, and never wait behind a
    # measurement: fail immediately so the caller can schedule a quiet slot.
    lock_path = canonical(str(lock_path))
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'Campaign lock is not a file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal('Measurement/another operation owns the campaign lock')
        yield
    finally:
        os.close(fd)


def fsync_parent(p):
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def exclusive_output(destination, mode=0o444):
    """Publish without replacement; retain partial output on every failure."""
    destination = canonical(str(destination))
    absent(destination)
    require(destination.parent.is_dir(), 'Destination parent must already exist')
    partial = destination.with_name(destination.name + '.partial.' + uuid.uuid4().hex)
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            yield f, partial
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), mode)
        # link() is an atomic exclusive publication, unlike replace()/rename().
        os.link(partial, destination, follow_symlinks=False)
        os.unlink(partial)  # Only our newly created temporary name; never raw evidence.
        fsync_parent(destination)
    except BaseException as exc:
        error = partial.with_name(partial.name + '.error.json')
        try:
            fd = os.open(error, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
            with os.fdopen(fd, 'wb') as f:
                f.write(encoded({'operation_destination': str(destination),
                                 'partial_path': str(partial),
                                 'error_type': type(exc).__name__, 'error': str(exc)}))
        except OSError:
            pass  # Original exception and partial remain authoritative.
        raise


def write_doc(p, obj):
    data = encoded(obj)
    with exclusive_output(p) as (f, _):
        f.write(data)
    return sha(data)


def validate_bindings(value, required=REQUIRED_BINDINGS):
    require(isinstance(value, dict) and required <= value.keys(), 'Missing exact ancestry bindings')
    require(all(is_sha(v) for v in value.values()), 'Ancestry values must be lowercase SHA256 strings')


def declared_paths(entry):
    paths = [entry['raw_path'], entry['archive_path'], entry['manifest_path'], entry['acceptance_path']]
    for kind in ('retire_receipt_paths', 'restore_receipt_paths'):
        for p in entry.get(kind, []):
            paths.extend([p, p + '.intent.json'])
    return paths


def validate_request(request):
    require(request.get('schema') == SCHEMA, 'Wrong request schema')
    require(isinstance(request.get('owner'), str) and request['owner'].strip(), 'Named owner required')
    require(isinstance(request.get('campaign_id'), str) and request['campaign_id'].strip(), 'Campaign ID required')
    root = canonical(request['campaign_root'])
    require(root.is_dir(), 'Campaign root must already exist')
    require(isinstance(request.get('minimum_free_bytes'), int) and request['minimum_free_bytes'] >= 0,
            'Explicit nonnegative free-space reserve required')
    require(request.get('outputs'), 'Exact prospective output allowlist required')
    seen = set()
    for entry in request['outputs']:
        require(entry.get('role') in ROLES, 'Only redundant proof/metrics evidence is eligible')
        validate_bindings(entry['frozen_bindings'])
        for value in declared_paths(entry):
            p = canonical(value)
            contained(root, p)
            require(value not in seen, 'Duplicate/overlapping output path')
            seen.add(value)
    return root


def freeze(request_path, admission_path, inventory_path, lock_path=CAMPAIGN_LOCK):
    """Must precede creation of EVERY exact admitted raw/output/receipt path."""
    with quiet(lock_path):
        request_path, admission_path, inventory_path = map(canonical, map(str, (request_path, admission_path, inventory_path)))
        request, request_sha = read_doc(request_path)
        root = validate_request(request)
        for p in (request_path, admission_path, inventory_path):
            contained(root, p)
        require(len({request_path, admission_path, inventory_path}) == 3, 'Metadata paths must differ')
        absent(admission_path)
        absent(inventory_path)
        for entry in request['outputs']:
            for value in declared_paths(entry):
                p = Path(value)
                require(p not in {request_path, admission_path, inventory_path}, 'Metadata/output overlap')
                absent(p)
        start_ns = time.time_ns()
        entries = []
        # Metadata-only inventory. Do not follow symlinks or read source bytes.
        def inventory_error(error):
            raise error
        for current, dirs, files in os.walk(root, followlinks=False, onerror=inventory_error):
            for name in sorted(dirs + files):
                p = Path(current) / name
                s = os.lstat(p)
                entries.append({'path': str(p.relative_to(root)), 'device': s.st_dev,
                                'inode': s.st_ino, 'mode': s.st_mode, 'bytes': s.st_size,
                                'mtime_ns': s.st_mtime_ns})
        inventory = {'schema': SCHEMA, 'kind': 'before-creation-inventory',
                     'campaign_id': request['campaign_id'], 'campaign_root': str(root),
                     'started_ns': start_ns, 'finished_ns': time.time_ns(),
                     'content_hashes_of_existing_files': False, 'entries': entries}
        for entry in request['outputs']:
            for value in declared_paths(entry):
                absent(Path(value))
        inventory_sha = write_doc(inventory_path, inventory)
        # Recheck after inventory publication. The shared lock prevents the
        # cooperating runner from creating any admitted file during this barrier.
        for entry in request['outputs']:
            for value in declared_paths(entry):
                absent(Path(value))
        admission = {'schema': SCHEMA, 'kind': 'frozen-prospective-admission',
                     'request_path': str(request_path), 'request_sha256': request_sha,
                     'inventory_path': str(inventory_path), 'inventory_sha256': inventory_sha,
                     'campaign_id': request['campaign_id'], 'measurement_lock': str(lock_path),
                     'frozen_before_ns': time.time_ns(), 'request': request}
        write_doc(admission_path, admission)
        return {'admission_path': str(admission_path), 'inventory_path': str(inventory_path),
                'eligible_outputs': len(request['outputs']), 'raw_outputs_created': 0}


def context(admission_path, raw_path, lock_path):
    admission, admission_sha = read_doc(canonical(str(admission_path)))
    require(admission.get('schema') == SCHEMA and admission.get('kind') == 'frozen-prospective-admission',
            'Not a frozen admission')
    require(admission['measurement_lock'] == str(lock_path), 'Wrong campaign measurement lock')
    request = admission['request']
    root = validate_request(request)
    live_request, request_sha = read_doc(Path(admission['request_path']))
    require(request_sha == admission['request_sha256'] and live_request == request, 'Owner request changed')
    inventory, inventory_sha = read_doc(Path(admission['inventory_path']))
    require(inventory_sha == admission['inventory_sha256'], 'Before-creation inventory changed')
    require(inventory['campaign_root'] == str(root) and inventory['campaign_id'] == request['campaign_id'],
            'Inventory campaign mismatch')
    raw_path = canonical(str(raw_path))
    matches = [e for e in request['outputs'] if e['raw_path'] == str(raw_path)]
    require(len(matches) == 1, 'Raw path not explicitly admitted')
    old_paths = {str(root / e['path']) for e in inventory['entries']}
    require(str(raw_path) not in old_paths, 'Pre-existing evidence cannot be admitted')
    return admission, admission_sha, matches[0], inventory


def new_raw(p, admission, inventory, initial):
    require(initial.st_ctime_ns >= admission['frozen_before_ns'], 'Raw predates frozen admission')
    old_inodes = {(e['device'], e['inode']) for e in inventory['entries']}
    require((initial.st_dev, initial.st_ino) not in old_inodes, 'Pre-existing inode refused')
    require(initial.st_nlink == 1, 'Hard-linked raw refused')


def acceptance_doc(path, admission, admission_sha, entry):
    require(str(canonical(str(path))) == entry['acceptance_path'], 'Acceptance path not explicitly admitted')
    accepted, accepted_sha = read_doc(canonical(str(path)))
    require(accepted.get('schema') == SCHEMA and accepted.get('kind') == 'post-measurement-acceptance',
            'Post-measurement acceptance/hash-binding document required')
    require(accepted.get('admission_sha256') == admission_sha, 'Acceptance not bound to this admission')
    require(accepted.get('campaign_id') == admission['campaign_id'], 'Acceptance campaign mismatch')
    require(accepted.get('raw_path') == entry['raw_path'], 'Acceptance raw path mismatch')
    require(accepted.get('measurement_complete') is True and accepted.get('storage_integrity_accepted') is True,
            'Writer must be terminal and storage integrity accepted; native quality success is not required')
    require(accepted.get('outside_headline_measurement') is True, 'Quiet-slot declaration required')
    require(is_sha(accepted.get('raw_sha256')) and type(accepted.get('raw_bytes')) is int and accepted['raw_bytes'] >= 0,
            'Accepted raw SHA256 and byte count required')
    validate_bindings(accepted.get('bindings'), REQUIRED_BINDINGS | {'run_manifest_sha256', 'offered_ledger_sha256'})
    require(all(accepted['bindings'].get(k) == v for k, v in entry['frozen_bindings'].items()),
            'Acceptance changed frozen plan/source/input/dataset ancestry')
    require(accepted.get('all_offered_statuses_preserved') is True, 'Offered failures/unstarted rows must be preserved')
    if entry['role'] == 'redundant-metrics':
        require(accepted.get('quality_resource_projections_checked') is True,
                'METRICS duplicates require checked compact quality/resource projections')
        require(is_sha(accepted['bindings'].get('projection_manifest_sha256')), 'Projection ancestry binding required')
    return accepted, accepted_sha


def stream_gzip_identity(path):
    compressed_hash, compressed_bytes = hashlib.sha256(), 0
    raw_hash, raw_bytes = hashlib.sha256(), 0
    with regular_reader(path) as (f, _):
        for block in iter(lambda: f.read(CHUNK), b''):
            compressed_hash.update(block)
            compressed_bytes += len(block)
        f.seek(0)
        with gzip.GzipFile(fileobj=f, mode='rb') as unzipped:
            for block in iter(lambda: unzipped.read(CHUNK), b''):
                raw_hash.update(block)
                raw_bytes += len(block)
    return {'sha256': compressed_hash.hexdigest(), 'bytes': compressed_bytes,
            'reconstructed_sha256': raw_hash.hexdigest(), 'reconstructed_bytes': raw_bytes}


def archive(admission_path, acceptance_path, raw_path, lock_path=CAMPAIGN_LOCK):
    with quiet(lock_path):
        adm, adm_sha, entry, inventory = context(admission_path, raw_path, lock_path)
        accepted, accepted_sha = acceptance_doc(acceptance_path, adm, adm_sha, entry)
        raw, gz, manifest = map(Path, (entry['raw_path'], entry['archive_path'], entry['manifest_path']))
        absent(gz)
        absent(manifest)
        # Conservative deflate expansion plus owner reserve; no compression-ratio assumption.
        need = accepted['raw_bytes'] + accepted['raw_bytes'] // 100 + CHUNK + adm['request']['minimum_free_bytes']
        require(shutil.disk_usage(gz.parent).free >= need, 'Insufficient disk for worst-case archive plus reserve')
        raw_hash, raw_bytes = hashlib.sha256(), 0
        with regular_reader(raw) as (source, before):
            new_raw(raw, adm, inventory, before)
            with exclusive_output(gz) as (target, partial):
                with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0, compresslevel=6) as zipped:
                    while True:
                        block = source.read(CHUNK)
                        if not block:
                            break
                        zipped.write(block)
                        raw_hash.update(block)
                        raw_bytes += len(block)
                target.flush()
                require(raw_hash.hexdigest() == accepted['raw_sha256'] and raw_bytes == accepted['raw_bytes'],
                        'Raw bytes do not equal accepted identity; archive remains partial')
                identity = stream_gzip_identity(partial)
                require(identity['reconstructed_sha256'] == raw_hash.hexdigest() and identity['reconstructed_bytes'] == raw_bytes,
                        'Streaming reconstruction verification failed')
        result = {'schema': SCHEMA, 'kind': 'immutable-lossless-archive-manifest',
                  'campaign_id': adm['campaign_id'], 'admission_path': str(admission_path),
                  'admission_sha256': adm_sha, 'inventory_sha256': adm['inventory_sha256'],
                  'owner_request_sha256': adm['request_sha256'],
                  'acceptance_path': str(acceptance_path), 'acceptance_sha256': accepted_sha,
                  'role': entry['role'], 'content_outcome_state': accepted.get('content_outcome_state', 'UNKNOWN'),
                  'storage_acceptance_is_not_native_or_quality_acceptance': True, 'raw_path': str(raw), 'raw_sha256': raw_hash.hexdigest(),
                  'raw_bytes': raw_bytes, 'raw_original_mode': stat.S_IMODE(before.st_mode),
                  'archive_path': str(gz), 'gzip_sha256': identity['sha256'], 'gzip_bytes': identity['bytes'],
                  'gzip_mtime': 0, 'gzip_filename': '', 'compression_level': 6,
                  'reconstruction_verified_sha256': identity['reconstructed_sha256'],
                  'reconstruction_verified_bytes': identity['reconstructed_bytes'],
                  'bindings': accepted['bindings'], 'raw_retirement_automatic': False,
                  'created_ns': time.time_ns()}
        write_doc(manifest, result)
        return result


def verified_manifest(admission_path, raw_path, lock_path):
    adm, adm_sha, entry, inventory = context(admission_path, raw_path, lock_path)
    manifest, manifest_sha = read_doc(Path(entry['manifest_path']))
    require(manifest.get('schema') == SCHEMA and manifest.get('kind') == 'immutable-lossless-archive-manifest',
            'Wrong archive manifest')
    require(manifest.get('admission_sha256') == adm_sha and manifest.get('raw_path') == entry['raw_path']
            and manifest.get('archive_path') == entry['archive_path'], 'Manifest path/admission mismatch')
    accepted, accepted_sha = acceptance_doc(Path(manifest['acceptance_path']), adm, adm_sha, entry)
    require(accepted_sha == manifest['acceptance_sha256'], 'Acceptance changed since archiving')
    require(manifest['raw_sha256'] == accepted['raw_sha256'] and manifest['raw_bytes'] == accepted['raw_bytes'],
            'Manifest/accepted raw identity mismatch')
    actual = stream_gzip_identity(Path(entry['archive_path']))
    require(actual == {'sha256': manifest['gzip_sha256'], 'bytes': manifest['gzip_bytes'],
                       'reconstructed_sha256': manifest['raw_sha256'], 'reconstructed_bytes': manifest['raw_bytes']},
            'Archive/reconstruction does not match manifest')
    return adm, entry, inventory, manifest, manifest_sha


def receipt_path(entry, value, kind):
    p = canonical(str(value))
    require(str(p) in entry.get(kind + '_receipt_paths', []), 'Receipt not explicitly admitted before creation')
    absent(p)
    absent(Path(str(p) + '.intent.json'))
    return p


def retire(admission_path, raw_path, receipt, explicitly_requested=False, lock_path=CAMPAIGN_LOCK):
    with quiet(lock_path):
        adm, entry, inventory, manifest, manifest_sha = verified_manifest(admission_path, raw_path, lock_path)
        require(explicitly_requested is True and entry.get('allow_raw_retirement') is True,
                'Raw retirement needs both owner admission and explicit request')
        raw = Path(entry['raw_path'])
        receipt = receipt_path(entry, receipt, 'retire')
        with regular_reader(raw) as (f, before):
            new_raw(raw, adm, inventory, before)
            h, count = hashlib.sha256(), 0
            for block in iter(lambda: f.read(CHUNK), b''):
                h.update(block)
                count += len(block)
            require((h.hexdigest(), count) == (manifest['raw_sha256'], manifest['raw_bytes']), 'Raw changed since archive')
            event = {'schema': SCHEMA, 'operation': 'retire-new-raw-after-exact-reconstruction-verification',
                     'raw_path': str(raw), 'manifest_path': entry['manifest_path'], 'manifest_sha256': manifest_sha,
                     'archive_path': entry['archive_path'], 'raw_sha256': h.hexdigest(), 'raw_bytes': count}
            write_doc(Path(str(receipt) + '.intent.json'), dict(event, state='intent'))
            require(fingerprint(os.fstat(f.fileno())) == fingerprint(before)
                    and fingerprint(os.lstat(raw)) == fingerprint(before), 'Raw changed before retirement')
        # Context above has closed the source. Recheck path identity immediately
        # before unlink; all participating writers must respect the same lock.
        require(fingerprint(os.lstat(raw)) == fingerprint(before), 'Raw changed before unlink')
        os.unlink(raw)  # Recoverable: verified immutable archive+manifest remain.
        fsync_parent(raw)
        write_doc(receipt, dict(event, state='raw-retired-recoverably', completed_ns=time.time_ns()))
        return event


def restore(admission_path, raw_path, receipt, lock_path=CAMPAIGN_LOCK):
    with quiet(lock_path):
        adm, entry, inventory, manifest, manifest_sha = verified_manifest(admission_path, raw_path, lock_path)
        raw = Path(entry['raw_path'])
        absent(raw)
        receipt = receipt_path(entry, receipt, 'restore')
        reserve = adm['request']['minimum_free_bytes']
        require(shutil.disk_usage(raw.parent).free >= manifest['raw_bytes'] + reserve,
                'Insufficient disk for create-only reconstruction plus reserve')
        event = {'schema': SCHEMA, 'operation': 'create-only-exact-raw-reconstruction',
                 'raw_path': str(raw), 'manifest_path': entry['manifest_path'], 'manifest_sha256': manifest_sha,
                 'raw_sha256': manifest['raw_sha256'], 'raw_bytes': manifest['raw_bytes']}
        write_doc(Path(str(receipt) + '.intent.json'), dict(event, state='intent'))
        h, count = hashlib.sha256(), 0
        with exclusive_output(raw, mode=manifest['raw_original_mode']) as (f, _):
            with regular_reader(Path(entry['archive_path'])) as (compressed, _):
                with gzip.GzipFile(fileobj=compressed, mode='rb') as unzipped:
                    for block in iter(lambda: unzipped.read(CHUNK), b''):
                        f.write(block)
                        h.update(block)
                        count += len(block)
            require((h.hexdigest(), count) == (manifest['raw_sha256'], manifest['raw_bytes']),
                    'Restoration verification failed; partial retained')
        write_doc(receipt, dict(event, state='raw-restored-verified', completed_ns=time.time_ns()))
        return event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze')
    p.add_argument('--request', required=True)
    p.add_argument('--admission', required=True)
    p.add_argument('--inventory', required=True)
    for name in ('archive', 'verify', 'retire', 'restore'):
        p = sub.add_parser(name)
        p.add_argument('--admission', required=True)
        p.add_argument('--raw', required=True)
        if name == 'archive':
            p.add_argument('--acceptance', required=True)
        if name in ('retire', 'restore'):
            p.add_argument('--receipt', required=True)
        if name == 'retire':
            p.add_argument('--explicitly-retire-new-raw', action='store_true')
    args = parser.parse_args()
    if args.command == 'freeze':
        result = freeze(args.request, args.admission, args.inventory)
    elif args.command == 'archive':
        result = archive(args.admission, args.acceptance, args.raw)
    elif args.command == 'retire':
        result = retire(args.admission, args.raw, args.receipt, args.explicitly_retire_new_raw)
    elif args.command == 'restore':
        result = restore(args.admission, args.raw, args.receipt)
    else:
        with quiet():
            _, _, _, manifest, manifest_sha = verified_manifest(args.admission, args.raw, CAMPAIGN_LOCK)
            result = {'verified': True, 'manifest_sha256': manifest_sha, 'raw_sha256': manifest['raw_sha256']}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (Refusal, OSError, ValueError, KeyError, EOFError) as exc:
        print(json.dumps({'status': 'REFUSED_OR_FAILED', 'error_type': type(exc).__name__, 'error': str(exc)}), file=sys.stderr)
        sys.exit(2)
