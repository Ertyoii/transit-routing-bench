"""Synthetic-only tests. Run solely in an owner-granted quiet slot."""
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('storage', Path(__file__).with_name('storage.py'))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sg-storage-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / 'campaign.lock'
        self.lock.write_bytes(b'')
        self.old = self.root / 'old-source-summary.json'
        self.old.write_bytes(b'OLD: never alter or archive\x00\xff')
        self.old_bytes = self.old.read_bytes()
        self.request_path = self.root / 'request.json'
        self.admission = self.root / 'admission.json'
        self.inventory = self.root / 'inventory.json'
        self.entries = [self.entry('future-a'), self.entry('future-b')]
        self.request = {'schema': s.SCHEMA, 'owner': 'synthetic-campaign-owner',
                        'campaign_id': 'synthetic-only', 'campaign_root': str(self.root),
                        'minimum_free_bytes': 0, 'outputs': self.entries}
        self.raw_bytes = b'{"proof":"' + b'x' * 10000 + b'"}\n\x00\xff\r\n'

    def entry(self, name):
        raw = str(self.root / (name + '.json'))
        return {'raw_path': raw, 'archive_path': raw + '.gz',
                'manifest_path': raw + '.archive-manifest.json',
                'acceptance_path': raw + '.storage-acceptance.json',
                'role': 'proof-summary', 'allow_raw_retirement': True,
                'retire_receipt_paths': [raw + '.retirement-1.json', raw + '.retirement-2.json'],
                'restore_receipt_paths': [raw + '.restoration-1.json'],
                'frozen_bindings': {k: str(i) * 64 for i, k in enumerate(sorted(s.REQUIRED_BINDINGS), 1)}}

    def freeze(self):
        self.request_path.write_bytes(s.encoded(self.request))
        return s.freeze(self.request_path, self.admission, self.inventory, self.lock)

    def accepted(self, entry=None, content_outcome_state='EXECUTED_PROCESS_FAILURE'):
        entry = entry or self.entries[0]
        raw = Path(entry['raw_path'])
        raw.write_bytes(self.raw_bytes)
        bindings = dict(entry['frozen_bindings'], run_manifest_sha256='a' * 64,
                        offered_ledger_sha256='b' * 64)
        data = {'schema': s.SCHEMA, 'kind': 'post-measurement-acceptance',
                'campaign_id': 'synthetic-only', 'admission_sha256': s.digest_file(self.admission)[0],
                'raw_path': str(raw), 'raw_sha256': hashlib.sha256(self.raw_bytes).hexdigest(),
                'raw_bytes': len(self.raw_bytes), 'measurement_complete': True,
                'storage_integrity_accepted': True, 'outside_headline_measurement': True,
                'all_offered_statuses_preserved': True, 'content_outcome_state': content_outcome_state,
                'bindings': bindings}
        path = Path(entry['acceptance_path'])
        path.write_bytes(s.encoded(data))
        return path, data

    def archive(self, entry=None):
        entry = entry or self.entries[0]
        return s.archive(self.admission, entry['acceptance_path'], entry['raw_path'], self.lock)

    def retire(self, explicit=True, receipt=None):
        entry = self.entries[0]
        receipt = receipt or entry['retire_receipt_paths'][0]
        return s.retire(self.admission, entry['raw_path'], receipt, explicit, self.lock)

    def restore(self):
        entry = self.entries[0]
        return s.restore(self.admission, entry['raw_path'], entry['restore_receipt_paths'][0], self.lock)

    def test_freeze_preserves_existing_bytes_and_records_inventory(self):
        result = self.freeze()
        self.assertEqual(result['raw_outputs_created'], 0)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        inventory = json.loads(self.inventory.read_text())
        self.assertIn(self.old.name, [e['path'] for e in inventory['entries']])
        self.assertFalse(inventory['content_hashes_of_existing_files'])
        self.assertEqual(self.admission.stat().st_mode & 0o777, 0o444)

    def test_preexisting_raw_refused_before_admission(self):
        Path(self.entries[0]['raw_path']).write_bytes(b'preexisting')
        with self.assertRaises(s.Refusal):
            self.freeze()
        self.assertFalse(self.admission.exists())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)

    def test_preexisting_any_output_or_acceptance_refused(self):
        Path(self.entries[0]['acceptance_path']).write_bytes(b'preexisting')
        with self.assertRaises(s.Refusal):
            self.freeze()

    def test_overlapping_metadata_refused(self):
        self.entries[0]['raw_path'] = str(self.inventory)
        with self.assertRaises(s.Refusal):
            self.freeze()

    def test_symlink_ancestor_refused(self):
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        self.entries[0]['raw_path'] = str(link / 'future.json')
        with self.assertRaises(s.Refusal):
            self.freeze()

    def test_path_outside_campaign_refused(self):
        self.entries[0]['raw_path'] = '/tmp/not-admitted-campaign-evidence.json'
        with self.assertRaises(s.Refusal):
            self.freeze()

    def test_freeze_exclusive_collision(self):
        self.freeze()
        before = self.admission.read_bytes()
        with self.assertRaises(s.Refusal):
            self.freeze()
        self.assertEqual(before, self.admission.read_bytes())

    def test_lock_refuses_freeze(self):
        with self.lock.open('rb') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(s.Refusal):
                self.freeze()
        self.assertFalse(self.admission.exists())

    def test_archive_failure_rows_are_eligible_and_raw_untouched(self):
        self.freeze()
        self.accepted()
        manifest = self.archive()
        self.assertEqual(manifest['content_outcome_state'], 'EXECUTED_PROCESS_FAILURE')
        self.assertTrue(manifest['storage_acceptance_is_not_native_or_quality_acceptance'])
        self.assertEqual(Path(self.entries[0]['raw_path']).read_bytes(), self.raw_bytes)
        self.assertEqual(manifest['raw_bytes'], len(self.raw_bytes))
        self.assertEqual(manifest['reconstruction_verified_sha256'], hashlib.sha256(self.raw_bytes).hexdigest())
        self.assertEqual(self.old.read_bytes(), self.old_bytes)

    def test_gzip_deterministic_no_filename_mtime_zero(self):
        self.freeze()
        identities = []
        for entry in self.entries:
            self.accepted(entry, 'UNKNOWN')
            manifest = self.archive(entry)
            compressed = Path(entry['archive_path']).read_bytes()
            self.assertEqual(compressed[4:8], b'\x00' * 4)
            self.assertEqual(compressed[3] & 8, 0)
            identities.append(manifest['gzip_sha256'])
        self.assertEqual(identities[0], identities[1])

    def test_unlisted_raw_refused(self):
        self.freeze()
        self.accepted()
        with self.assertRaises(s.Refusal):
            s.archive(self.admission, self.entries[0]['acceptance_path'], self.old, self.lock)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)

    def test_unspecified_acceptance_refused(self):
        self.freeze()
        acceptance, _ = self.accepted()
        other = self.root / 'not-allowlisted.json'
        other.write_bytes(acceptance.read_bytes())
        with self.assertRaises(s.Refusal):
            s.archive(self.admission, other, self.entries[0]['raw_path'], self.lock)

    def test_wrong_hash_keeps_raw_and_partial_error(self):
        self.freeze()
        path, doc = self.accepted()
        doc['raw_sha256'] = '0' * 64
        path.write_bytes(s.encoded(doc))
        with self.assertRaises(s.Refusal):
            self.archive()
        self.assertEqual(Path(self.entries[0]['raw_path']).read_bytes(), self.raw_bytes)
        self.assertFalse(Path(self.entries[0]['archive_path']).exists())
        self.assertTrue(list(self.root.glob('future-a.json.gz.partial.*.error.json')))
        self.assertFalse(Path(self.entries[0]['manifest_path']).exists())

    def test_changed_frozen_ancestry_refused(self):
        self.freeze()
        path, doc = self.accepted()
        doc['bindings']['dataset_sha256'] = 'f' * 64
        path.write_bytes(s.encoded(doc))
        with self.assertRaises(s.Refusal):
            self.archive()

    def test_changed_owner_request_refused(self):
        self.freeze()
        self.accepted()
        request = copy.deepcopy(self.request)
        request['owner'] = 'somebody-else'
        self.request_path.write_bytes(s.encoded(request))
        with self.assertRaises(s.Refusal):
            self.archive()

    def test_metrics_requires_checked_projection_binding(self):
        self.entries[0]['role'] = 'redundant-metrics'
        self.freeze()
        path, doc = self.accepted()
        with self.assertRaises(s.Refusal):
            self.archive()
        doc['quality_resource_projections_checked'] = True
        doc['bindings']['projection_manifest_sha256'] = 'c' * 64
        path.write_bytes(s.encoded(doc))
        self.archive()

    def test_incomplete_writer_refused(self):
        self.freeze()
        path, doc = self.accepted()
        doc['measurement_complete'] = False
        path.write_bytes(s.encoded(doc))
        with self.assertRaises(s.Refusal):
            self.archive()

    def test_archiving_twice_never_overwrites(self):
        self.freeze()
        self.accepted()
        self.archive()
        gz = Path(self.entries[0]['archive_path'])
        before = gz.read_bytes()
        with self.assertRaises(s.Refusal):
            self.archive()
        self.assertEqual(before, gz.read_bytes())

    def test_retirement_requires_explicit_request(self):
        self.freeze()
        self.accepted()
        self.archive()
        with self.assertRaises(s.Refusal):
            self.retire(explicit=False)
        self.assertTrue(Path(self.entries[0]['raw_path']).exists())

    def test_retirement_requires_prospective_permission(self):
        self.entries[0]['allow_raw_retirement'] = False
        self.freeze()
        self.accepted()
        self.archive()
        with self.assertRaises(s.Refusal):
            self.retire()
        self.assertTrue(Path(self.entries[0]['raw_path']).exists())

    def test_corrupt_archive_prevents_retirement(self):
        self.freeze()
        self.accepted()
        self.archive()
        gz = Path(self.entries[0]['archive_path'])
        gz.chmod(0o644)
        content = bytearray(gz.read_bytes())
        content[-1] ^= 1
        gz.write_bytes(content)
        with self.assertRaises((s.Refusal, OSError)):
            self.retire()
        self.assertTrue(Path(self.entries[0]['raw_path']).exists())

    def test_changed_raw_prevents_retirement(self):
        self.freeze()
        self.accepted()
        self.archive()
        Path(self.entries[0]['raw_path']).write_bytes(b'changed raw')
        with self.assertRaises(s.Refusal):
            self.retire()
        self.assertEqual(Path(self.entries[0]['raw_path']).read_bytes(), b'changed raw')

    def test_acceptance_tampering_prevents_retirement(self):
        self.freeze()
        path, doc = self.accepted()
        self.archive()
        doc['content_outcome_state'] = 'another-state'
        path.write_bytes(s.encoded(doc))
        with self.assertRaises(s.Refusal):
            self.retire()

    def test_unlisted_receipt_prevents_retirement(self):
        self.freeze()
        self.accepted()
        self.archive()
        with self.assertRaises(s.Refusal):
            self.retire(receipt=self.root / 'unspecified-receipt.json')
        self.assertTrue(Path(self.entries[0]['raw_path']).exists())

    def test_restore_never_overwrites(self):
        self.freeze()
        self.accepted()
        self.archive()
        with self.assertRaises(s.Refusal):
            self.restore()
        self.assertEqual(Path(self.entries[0]['raw_path']).read_bytes(), self.raw_bytes)

    def test_roundtrip_retire_restore_retire_existing_archive_unchanged(self):
        self.freeze()
        self.accepted()
        self.archive()
        gz = Path(self.entries[0]['archive_path'])
        archive_bytes = gz.read_bytes()
        self.retire()
        self.assertFalse(Path(self.entries[0]['raw_path']).exists())
        self.restore()
        self.assertEqual(Path(self.entries[0]['raw_path']).read_bytes(), self.raw_bytes)
        self.retire(receipt=self.entries[0]['retire_receipt_paths'][1])
        self.assertFalse(Path(self.entries[0]['raw_path']).exists())
        self.assertEqual(gz.read_bytes(), archive_bytes)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertTrue(Path(self.entries[0]['retire_receipt_paths'][0] + '.intent.json').exists())

    def test_lock_refuses_archive_retire_restore(self):
        self.freeze()
        self.accepted()
        with self.lock.open('rb') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(s.Refusal):
                self.archive()
        self.archive()
        with self.lock.open('rb') as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(s.Refusal):
                self.retire()
            with self.assertRaises(s.Refusal):
                self.restore()

    def test_hardlinked_existing_inode_never_archived(self):
        self.freeze()
        _, doc = self.accepted()
        raw = Path(self.entries[0]['raw_path'])
        raw.unlink()  # Synthetic fixture only; helper must refuse the new alias.
        os.link(self.old, raw)
        doc['raw_sha256'] = hashlib.sha256(self.old_bytes).hexdigest()
        doc['raw_bytes'] = len(self.old_bytes)
        Path(self.entries[0]['acceptance_path']).write_bytes(s.encoded(doc))
        with self.assertRaises(s.Refusal):
            self.archive()
        self.assertEqual(self.old.read_bytes(), self.old_bytes)

    def test_partial_kept_on_writer_failure(self):
        target = self.root / 'synthetic-target'
        with self.assertRaises(RuntimeError):
            with s.exclusive_output(target) as (f, _):
                f.write(b'partial')
                raise RuntimeError('intentional synthetic failure')
        self.assertFalse(target.exists())
        self.assertTrue(list(self.root.glob('synthetic-target.partial.*.error.json')))

    def test_atomic_publish_collision_preserves_both(self):
        target = self.root / 'synthetic-target'
        with self.assertRaises(FileExistsError):
            with s.exclusive_output(target) as (f, _):
                f.write(b'new')
                target.write_bytes(b'collision-existing')
        self.assertEqual(target.read_bytes(), b'collision-existing')
        self.assertTrue(list(self.root.glob('synthetic-target.partial.*.error.json')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
