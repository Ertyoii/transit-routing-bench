#!/usr/bin/env python3
"""Create-only deterministic gzip sharding of a completed compact outcome publication.

No rows or fields are changed. This reads only an already projected publication,
not router inputs. Original-stage manifests are retained as historical bindings;
new manifests describe only files actually present in the sharded package.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import zlib

TARGET_BYTES = 1024 * 1024
HARD_BYTES = 2 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_FILES = 10000


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n')


def safe_path(root, relative):
    if not isinstance(relative, str):
        raise ValueError('Publication member path must be a string')
    path = Path(relative)
    if str(path) != relative or path.is_absolute() or not path.parts or any(part in ('.', '..') for part in path.parts):
        raise ValueError('Unsafe publication member path')
    result = root / path
    if result.is_symlink() or not result.resolve().is_relative_to(root.resolve()):
        raise ValueError('Publication member symlink escape refused')
    return result


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()
        self.bytes = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.hash.update(data)
        self.bytes += len(data)
        return data


class ShardWriter:
    def __init__(self, out, target_bytes=TARGET_BYTES, max_line_bytes=MAX_LINE_BYTES):
        if target_bytes < 64 or target_bytes >= HARD_BYTES:
            raise ValueError('Shard target must be at least64 bytes and strictly below2 MiB')
        self.out = out
        (out / 'outcomes').mkdir()
        self.target = target_bytes
        self.max_line = max_line_bytes
        self.shards = []
        self.rows = 0
        self.whole_hash = hashlib.sha256()
        self.whole_bytes = 0
        self.reset()

    def reset(self):
        self.compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
        self.compressed = bytearray()
        self.raw_hash = hashlib.sha256()
        self.raw_bytes = 0
        self.shard_rows = 0

    def preview(self, line):
        trial = self.compressor.copy()
        emitted = trial.compress(line)
        completed = trial.copy().flush(zlib.Z_FINISH)
        return trial, emitted, len(self.compressed) + len(emitted) + len(completed)

    def add(self, line):
        if not line.endswith(b'\n') or not line or len(line) >= self.max_line:
            raise ValueError('Outcome line must end in newline and fit strictly below1 MiB; never truncated')
        try:
            value = json.loads(line)
        except Exception as exc:
            raise ValueError('Invalid outcome JSON line') from exc
        if not isinstance(value, dict):
            raise ValueError('Outcome JSON line must be an object')
        trial, emitted, finished_size = self.preview(line)
        if self.shard_rows and finished_size > self.target:
            self.finish_shard()
            trial, emitted, finished_size = self.preview(line)
        if finished_size >= HARD_BYTES:
            raise ValueError('One outcome line cannot fit the hard compressed shard bound')
        self.compressor = trial
        self.compressed.extend(emitted)
        self.raw_hash.update(line)
        self.raw_bytes += len(line)
        self.shard_rows += 1
        self.whole_hash.update(line)
        self.whole_bytes += len(line)
        self.rows += 1

    def finish_shard(self):
        if not self.shard_rows:
            return
        if len(self.shards) >= MAX_FILES:
            raise ValueError('Shard file-count budget exceeded')
        self.compressed.extend(self.compressor.flush(zlib.Z_FINISH))
        data = bytes(self.compressed)
        if len(data) >= HARD_BYTES:
            raise ValueError('Compressed shard violates hard2 MiB bound')
        relative = 'outcomes/part-%05d.jsonl.gz' % len(self.shards)
        (self.out / relative).write_bytes(data)
        self.shards.append({
            'path': relative, 'row_count': self.shard_rows,
            'start_row_ordinal': self.rows - self.shard_rows,
            'end_row_ordinal_exclusive': self.rows,
            'compressed_bytes': len(data), 'compressed_sha256': hashlib.sha256(data).hexdigest(),
            'uncompressed_bytes': self.raw_bytes, 'uncompressed_sha256': self.raw_hash.hexdigest(),
            'single_row_over_target': len(data) > self.target,
        })
        self.reset()

    def finish(self):
        self.finish_shard()
        return {'shards': self.shards, 'row_count': self.rows,
                'uncompressed_bytes': self.whole_bytes,
                'uncompressed_sha256': self.whole_hash.hexdigest()}


def verify_shards(out, index):
    whole = hashlib.sha256()
    rows = total_bytes = 0
    for shard in index['shards']:
        path = safe_path(out, shard['path'])
        if path.stat().st_size >= HARD_BYTES:
            raise ValueError('Compressed shard violates hard2 MiB bound')
        if path.stat().st_size != shard['compressed_bytes'] or sha(path) != shard['compressed_sha256']:
            raise ValueError('Compressed shard size/hash mismatch: ' + shard['path'])
        digest = hashlib.sha256()
        shard_rows = shard_bytes = 0
        if shard['start_row_ordinal'] != rows:
            raise ValueError('Shard ordinal discontinuity')
        with gzip.open(path, 'rb') as stream:
            for line in stream:
                if not line.endswith(b'\n') or len(line) >= MAX_LINE_BYTES:
                    raise ValueError('Invalid/oversized verified outcome line')
                digest.update(line)
                whole.update(line)
                shard_rows += 1
                shard_bytes += len(line)
        rows += shard_rows
        total_bytes += shard_bytes
        if (shard_rows != shard['row_count'] or rows != shard['end_row_ordinal_exclusive'] or
                shard_bytes != shard['uncompressed_bytes'] or digest.hexdigest() != shard['uncompressed_sha256']):
            raise ValueError('Uncompressed shard row/size/hash mismatch')
    if rows != index['row_count'] or total_bytes != index['uncompressed_bytes'] or whole.hexdigest() != index['uncompressed_sha256']:
        raise ValueError('Whole outcome stream count/size/hash mismatch')
    return rows


def assemble(source, out, target_bytes=TARGET_BYTES):
    source = source.resolve()
    if out.exists() or out.resolve().is_relative_to(source) or source.is_relative_to(out.resolve()):
        raise ValueError('Output must be a fresh directory outside the source stage')
    manifest_path = source / 'PUBLICATION_MANIFEST.json'
    manifest_data = manifest_path.read_bytes()
    manifest = json.loads(manifest_data)
    members = {}
    for member in manifest['files']:
        path = member['path']
        safe_path(source, path)
        if path in members:
            raise ValueError('Duplicate original manifest member')
        members[path] = member
    required = {'outcome-records.jsonl.gz', 'provenance-records.jsonl.gz', 'ARTIFACT_INDEX.json', 'SHA256SUMS.json'}
    if not required.issubset(members):
        raise ValueError('Not a completed compact publication stage')
    artifact = json.loads((source / 'ARTIFACT_INDEX.json').read_bytes())
    if not artifact.get('compact_mode'):
        raise ValueError('Only completed compact stages are accepted')
    for relative in members:
        if relative not in required and not relative.startswith('reports/'):
            raise ValueError('Unrecognized original publication member: ' + relative)
    out.mkdir(parents=True, exist_ok=False)
    copied = []
    # Original metadata is byte-preserved and verified, not reserialized.
    for relative, binding in sorted(members.items()):
        if relative == 'outcome-records.jsonl.gz':
            continue
        src = safe_path(source, relative)
        data = src.read_bytes()
        if len(data) != binding['bytes'] or hashlib.sha256(data).hexdigest() != binding['sha256']:
            raise ValueError('Original publication member size/hash mismatch: ' + relative)
        dest_relative = 'ORIGINAL_STAGE_SHA256SUMS.json' if relative == 'SHA256SUMS.json' else relative
        dest = safe_path(out, dest_relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        copied.append({'original_path': relative, 'path': dest_relative, 'bytes': len(data), 'sha256': binding['sha256']})
    (out / 'ORIGINAL_STAGE_MANIFEST.json').write_bytes(manifest_data)
    writer = ShardWriter(out, target_bytes)
    original = members['outcome-records.jsonl.gz']
    with safe_path(source, 'outcome-records.jsonl.gz').open('rb') as raw:
        reader = HashingReader(raw)
        with gzip.GzipFile(fileobj=reader, mode='rb') as stream:
            for line in stream:
                writer.add(line)
        original_compressed_hash = reader.hash.hexdigest()
        original_compressed_bytes = reader.bytes
    index = writer.finish()
    if original_compressed_hash != original['sha256'] or original_compressed_bytes != original['bytes']:
        raise ValueError('Original compressed outcome size/hash mismatch')
    if index['row_count'] != artifact['rows']:
        raise ValueError('Original ARTIFACT_INDEX outcome row count mismatch')
    index.update({
        'schema': 'public-outcome-independent-gzip-shards-v1',
        'original_outcome': dict(original, present_in_sharded_package=False, uncompressed_bytes=index['uncompressed_bytes'],
                                 uncompressed_sha256=index['uncompressed_sha256'], row_count=index['row_count']),
        'original_stage_manifest': {'path': 'ORIGINAL_STAGE_MANIFEST.json', 'bytes': len(manifest_data),
                                    'sha256': hashlib.sha256(manifest_data).hexdigest()},
        'copied_original_members': copied,
        'target_compressed_bytes': target_bytes, 'hard_compressed_bytes_exclusive': HARD_BYTES,
        'max_line_bytes_exclusive': MAX_LINE_BYTES,
        'gzip': {'mtime': 0, 'filename': None, 'level': 9, 'zlib_version': zlib.ZLIB_VERSION},
        'sharder_source_sha256': sha(Path(__file__)),
        'scope': 'Exact original JSONL bytes and row order, no field changes or row omissions. Ordinals are zero-based, end-exclusive. Each shard is independently decompressable. Historical ORIGINAL_STAGE manifests describe the original stage, not current package contents or a still-present original outcome gzip. Current PUBLICATION_MANIFEST and SHA256SUMS describe only current files.',
    })
    verify_shards(out, index)
    write_json(out / 'SHARD_INDEX.json', index)
    files = [{'path': str(path.relative_to(out)), 'bytes': path.stat().st_size, 'sha256': sha(path)}
             for path in sorted(out.rglob('*')) if path.is_file()]
    if len(files) + 2 > MAX_FILES:
        raise ValueError('Sharded publication file-count budget exceeded')
    write_json(out / 'SHA256SUMS.json', {item['path']: item['sha256'] for item in files})
    sums = out / 'SHA256SUMS.json'
    files.append({'path': sums.name, 'bytes': sums.stat().st_size, 'sha256': sha(sums)})
    files.sort(key=lambda item: item['path'])
    write_json(out / 'PUBLICATION_MANIFEST.json', {
        'schema': 'public-sharded-outcome-file-manifest-v1', 'files': files,
        'file_count': len(files), 'total_bytes': sum(item['bytes'] for item in files),
        'rows': index['row_count'], 'shard_count': len(index['shards']),
        'scope': 'Every file actually present except this self-referential manifest. Original-stage manifests are explicitly historical bindings.',
    })
    path = out / 'PUBLICATION_MANIFEST.json'
    return {'out': out.name, 'rows': index['row_count'], 'shards': len(index['shards']),
            'uncompressed_sha256': index['uncompressed_sha256'],
            'largest_compressed_shard_bytes': max((s['compressed_bytes'] for s in index['shards']), default=0),
            'files': len(files) + 1, 'pushed': False,
            'manifest': {'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--target-bytes', type=int, default=TARGET_BYTES)
    args = parser.parse_args(argv)
    result = assemble(args.stage, args.out, args.target_bytes)
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == '__main__':
    main()
