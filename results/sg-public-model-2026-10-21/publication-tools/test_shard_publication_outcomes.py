"""Small synthetic-only tests; no campaign/router input reads."""
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('shard_publication_outcomes', Path(__file__).with_name('shard_publication_outcomes.py'))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class ShardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='publication-shards-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def lines(self, count=60):
        return [(' { "ordinal": %d, "unicode": "Singapore \\u65b0", "payload": "%s" }\n' %
                 (i, ''.join(hashlib.sha256(('%d-%d' % (i, j)).encode()).hexdigest() for j in range(3)))).encode()
                for i in range(count)]

    def source(self, lines):
        source = self.root / 'stage'
        source.mkdir()
        (source / 'reports').mkdir()
        (source / 'outcome-records.jsonl.gz').write_bytes(gzip.compress(b''.join(lines), mtime=0))
        (source / 'provenance-records.jsonl.gz').write_bytes(gzip.compress(b'{"path":"synthetic","content":{}}\n', mtime=0))
        mod.write_json(source / 'ARTIFACT_INDEX.json', {'compact_mode': True, 'rows': len(lines), 'original_binding': 'a' * 64})
        (source / 'reports' / 'summary.json').write_text('{"success":false,"failures":2}\n')
        files = [{'path': str(path.relative_to(source)), 'bytes': path.stat().st_size, 'sha256': mod.sha(path)}
                 for path in sorted(source.rglob('*')) if path.is_file()]
        mod.write_json(source / 'SHA256SUMS.json', {entry['path']: entry['sha256'] for entry in files})
        sums = source / 'SHA256SUMS.json'
        files.append({'path': sums.name, 'bytes': sums.stat().st_size, 'sha256': mod.sha(sums)})
        mod.write_json(source / 'PUBLICATION_MANIFEST.json', {'files': files})
        return source

    def assemble(self, lines=None, target=700):
        lines = self.lines() if lines is None else lines
        source = self.source(lines)
        out = self.root / 'sharded'
        result = mod.assemble(source, out, target)
        index = json.loads((out / 'SHARD_INDEX.json').read_text())
        return source, out, result, index, lines

    def test_exact_order_independent_gzip_and_near_target_sizes(self):
        _, out, result, index, lines = self.assemble()
        self.assertGreater(result['shards'], 1)
        restored = []
        for shard in index['shards']:
            data = (out / shard['path']).read_bytes()
            self.assertLessEqual(len(data), 700)
            self.assertLess(len(data), mod.HARD_BYTES)
            self.assertEqual(data[4:8], b'\0' * 4)
            restored += gzip.decompress(data).splitlines(keepends=True)
        self.assertEqual(restored, lines)
        self.assertEqual(index['uncompressed_sha256'], hashlib.sha256(b''.join(lines)).hexdigest())
        self.assertEqual(index['row_count'], len(lines))
        self.assertTrue(all(s['compressed_bytes'] > 700 * .65 for s in index['shards'][:-1]))
        self.assertEqual(mod.verify_shards(out, index), len(lines))

    def test_repeatable_bytes_and_honest_current_manifests(self):
        source, out, _, index, lines = self.assemble()
        other = self.root / 'sharded-again'
        mod.assemble(source, other, 700)
        for path in out.rglob('*'):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (other / path.relative_to(out)).read_bytes())
        self.assertFalse((out / 'outcome-records.jsonl.gz').exists())
        self.assertEqual((out / 'ORIGINAL_STAGE_MANIFEST.json').read_bytes(), (source / 'PUBLICATION_MANIFEST.json').read_bytes())
        self.assertEqual((out / 'ORIGINAL_STAGE_SHA256SUMS.json').read_bytes(), (source / 'SHA256SUMS.json').read_bytes())
        self.assertEqual((out / 'ARTIFACT_INDEX.json').read_bytes(), (source / 'ARTIFACT_INDEX.json').read_bytes())
        manifest = json.loads((out / 'PUBLICATION_MANIFEST.json').read_text())
        current = {entry['path'] for entry in manifest['files']}
        self.assertNotIn('outcome-records.jsonl.gz', current)
        self.assertEqual(current, {str(path.relative_to(out)) for path in out.rglob('*') if path.is_file()} - {'PUBLICATION_MANIFEST.json'})
        for entry in manifest['files']:
            path = out / entry['path']
            self.assertEqual(entry['bytes'], path.stat().st_size)
            self.assertEqual(entry['sha256'], mod.sha(path))

    def test_oversize_invalid_line_and_hard_bound_fail_without_truncation(self):
        for line in (b'{}', b'\n', b'[]\n', b'{"x":"' + b'a' * 90 + b'"}\n'):
            out = self.root / ('writer-' + str(len(list(self.root.iterdir()))))
            out.mkdir()
            writer = mod.ShardWriter(out, target_bytes=100, max_line_bytes=64)
            with self.assertRaises(ValueError):
                writer.add(line)
            self.assertFalse(list((out / 'outcomes').iterdir()))
        old = mod.HARD_BYTES
        try:
            mod.HARD_BYTES = 128
            out = self.root / 'hard'
            out.mkdir()
            writer = mod.ShardWriter(out, target_bytes=100)
            with self.assertRaisesRegex(ValueError, 'hard compressed'):
                writer.add(self.lines(1)[0])
        finally:
            mod.HARD_BYTES = old

    def test_compressed_and_uncompressed_mutations_detected(self):
        _, out, _, index, _ = self.assemble()
        first = index['shards'][0]
        path = out / first['path']
        original = path.read_bytes()
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaisesRegex(ValueError, 'Compressed shard'):
            mod.verify_shards(out, index)
        changed = copy.deepcopy(index)
        raw = gzip.decompress(original).replace(b'Singapore', b'SynthCity', 1)
        path.write_bytes(gzip.compress(raw, mtime=0))
        changed['shards'][0].update(compressed_sha256=mod.sha(path), compressed_bytes=path.stat().st_size)
        with self.assertRaisesRegex(ValueError, 'Uncompressed shard'):
            mod.verify_shards(out, changed)

    def test_ordinal_and_whole_stream_mutations_detected(self):
        _, out, _, index, _ = self.assemble()
        changed = copy.deepcopy(index)
        changed['shards'][1]['start_row_ordinal'] += 1
        with self.assertRaisesRegex(ValueError, 'ordinal'):
            mod.verify_shards(out, changed)
        changed = copy.deepcopy(index)
        changed['uncompressed_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Whole outcome'):
            mod.verify_shards(out, changed)

    def test_original_stage_hash_and_row_count_mismatch_rejected(self):
        source = self.source(self.lines(3))
        source_manifest = source / 'PUBLICATION_MANIFEST.json'
        manifest = json.loads(source_manifest.read_text())
        for entry in manifest['files']:
            if entry['path'] == 'outcome-records.jsonl.gz':
                entry['sha256'] = '0' * 64
        mod.write_json(source_manifest, manifest)
        out = self.root / 'bad-source'
        with self.assertRaisesRegex(ValueError, 'Original compressed outcome'):
            mod.assemble(source, out, 700)
        self.assertFalse((out / 'PUBLICATION_MANIFEST.json').exists())
        for entry in manifest['files']:
            if entry['path'] == 'outcome-records.jsonl.gz':
                entry['sha256'] = mod.sha(source / entry['path'])
        artifact = source / 'ARTIFACT_INDEX.json'
        mod.write_json(artifact, {'compact_mode': True, 'rows': 99})
        for entry in manifest['files']:
            if entry['path'] == 'ARTIFACT_INDEX.json':
                entry.update(bytes=artifact.stat().st_size, sha256=mod.sha(artifact))
        mod.write_json(source_manifest, manifest)
        with self.assertRaisesRegex(ValueError, 'row count'):
            mod.assemble(source, self.root / 'bad-count', 700)

    def test_fresh_output_and_path_traversal_rejected(self):
        source, out, _, _, _ = self.assemble(self.lines(1))
        with self.assertRaises(ValueError):
            mod.assemble(source, out)
        with self.assertRaises(ValueError):
            mod.assemble(source, source / 'nested')
        with self.assertRaises(ValueError):
            mod.safe_path(source, '../private')
        (source / 'escape').symlink_to(self.root / 'elsewhere')
        with self.assertRaises(ValueError):
            mod.safe_path(source, 'escape')


if __name__ == '__main__':
    unittest.main()
