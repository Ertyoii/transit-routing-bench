"""Synthetic temporary files only. No SG routing workload or holdout execution."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import campaign_gate as gate
import run_campaign as runner


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='routing-gate-synthetic-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.module = self.base / 'isolated-worktree'
        self.module.mkdir()
        (self.module / 'go.mod').write_text('module synthetic.invalid/fixture\n\ngo 1.27.0\n')
        (self.module / 'fixture.go').write_text('package fixture\nconst Value = 1\n')
        (self.module / 'support.txt').write_text('support-v1\n')
        self.binary = self.module / 'synthetic-command'
        self.binary.write_text('#!/bin/sh\nexit 0\n')
        self.binary.chmod(0o755)
        subprocess.run(['git', 'init', '-q', str(self.module)], check=True)
        subprocess.run(['git', '-C', str(self.module), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.module), '-c', 'user.name=Synthetic Test', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'synthetic fixture'], check=True)
        self.data = self.base / 'data.json'
        self.data.write_text('{"synthetic":true}\n')
        self.config = self.base / 'configuration.json'
        self.config.write_text('{"configuration":"synthetic-only"}\n')
        self.query = self.base / 'queries.json'
        self.sidecar = self.base / 'queries.metadata.json'
        self.write_workload('test')
        self.registry = self.base / 'registry.json'
        self.write_registry()
        self.plan_path = self.base / 'plan.json'
        self.plan = {'evaluation_mode': 'final_evaluation', 'continue_on_failure': False,
                     'source_provenance': {'status': 'synthetic_unit_test_not_real_official_qualification', 'original_source_path': 'preserved-example'},
                     'workload_registry': gate.identity(self.registry), 'runs': [{
                         'id': 'synthetic-final', 'argv': [str(self.binary), '-dataset', str(self.data), '-queries', str(self.query), '-scoped-config', str(self.config), '-out-dir', '{run_dir}/artifact'],
                         'cwd': str(self.module), 'source_roots': [str(self.module)], 'timeout_s': 5}]}
        self.write_qualification()
        self.save_plan()
        self.seal = self.base / 'seal.json'

    def dump(self, path, value):
        Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')

    def save_plan(self):
        self.dump(self.plan_path, self.plan)

    def write_workload(self, split):
        self.dump(self.query, {'seed': 1, 'method': 'synthetic_schema_fixture_only', 'dataset_sha256': gate.digest(self.data),
                               'items': [{'stratum': 'synthetic', 'query': {'id': 'synthetic-1', 'origin': 0, 'destination': 1}}]})
        self.dump(self.sidecar, {'queries_sha256': gate.digest(self.query), 'dataset_sha256': gate.digest(self.data), 'fixture_notice': 'SYNTHETIC TEST ONLY',
                                 'items': [{'query_id': 'synthetic-1', 'split': split}]})

    def write_registry(self, split='test'):
        self.dump(self.registry, {'schema': gate.SCHEMA, 'provenance': {'fixture_notice': 'SYNTHETIC TEST ONLY', 'original_source_path': str(self.query)},
                                  'entries': [{'split': split, 'workload': gate.identity(self.query), 'metadata': gate.identity(self.sidecar), 'source_metadata': {'fixture_notice': 'SYNTHETIC TEST ONLY'}}]})

    def write_qualification(self, eligible=True):
        self.audit = self.base / 'audit.json'
        self.review = self.base / 'review.json'
        self.qualification = self.base / 'qualification.json'
        self.raw_source = self.base / 'synthetic-raw-source.bin'
        self.raw_source.write_bytes(b'SYNTHETIC TEST BYTES, NOT REAL OFFICIAL LTA DATA')
        now = dt.datetime.now(dt.timezone.utc)
        reviewed_utc = (now - dt.timedelta(seconds=1)).isoformat()
        expires_utc = (now + dt.timedelta(hours=1)).isoformat()
        self.dump(self.audit, {'schema': 'official-lta-data-audit-v1', 'formal_baseline_eligible': eligible,
                              'data_origin': 'official_lta', 'freshness': 'latest_at_acquisition', 'coverage': {'bus': True, 'rail': True},
                              'acquired_utc': '2000-01-01T00:00:00Z', 'sources': [{'source_url': 'https://datamall.lta.gov.sg/synthetic-fixture-not-a-real-download', 'source_owner': 'Land Transport Authority', 'acquired_utc': '2000-01-01T00:00:00Z', 'artifact': gate.identity(self.raw_source), 'evidence': 'SYNTHETIC SCHEMA FIXTURE, NOT A REAL OFFICIAL AUDIT'}],
                              'normalized_input_sha256': [gate.digest(self.data)]})
        audit = json.loads(self.audit.read_text()); audit['latest_checked_utc'] = reviewed_utc; self.dump(self.audit, audit)
        self.dump(self.review, {'schema': 'official-lta-data-review-v1', 'decision': 'accept_for_bound_evaluation_only',
                               'reviewed_audit_sha256': gate.digest(self.audit), 'reviewer': 'synthetic-unit-test-fixture',
                               'basis': ['Schema check only; never use as real data qualification'], 'approved_input_sha256': [gate.digest(self.data)]})
        review = json.loads(self.review.read_text()); review.update(reviewed_utc=reviewed_utc, valid_until_utc=expires_utc); self.dump(self.review, review)
        self.dump(self.qualification, {'schema': 'official-lta-evaluation-qualification-v1', 'formal_baseline_eligible': eligible,
                                      'source_status': 'reviewed_latest_official_lta_bus_and_rail' if eligible else 'provisional_community_model',
                                      'audit': gate.identity(self.audit), 'review': gate.identity(self.review), 'inputs': [gate.identity(self.data)],
                                      'fixture_notice': 'SYNTHETIC METADATA STRUCTURE ONLY, NOT REAL OFFICIAL DATA'})
        qualification = json.loads(self.qualification.read_text()); qualification['valid_until_utc'] = expires_utc; self.dump(self.qualification, qualification)
        self.plan['data_qualification'] = gate.identity(self.qualification)

    def make_seal(self):
        self.save_plan()
        return runner.create_seal(self.plan_path, self.seal)

    def verify(self, ref, require_official=False):
        return runner.verify_seal(self.plan_path, ref, require_official=require_official)

    def prepare(self, spec=None, registry=True, inspect=False):
        return runner.prepare_run(spec or self.plan['runs'][0], self.base / 'run', self.base / 'campaign', runner.campaign_environment(), '0-3', 0.2,
                                  gate.load_registry(self.plan, self.base) if registry else None, inspect_heldout=inspect)[0]

    def test_registry_classifies_renamed_test_by_sha(self):
        renamed = self.base / 'innocent-name.json'
        shutil.copyfile(self.query, renamed)
        spec = copy.deepcopy(self.plan['runs'][0]); spec['argv'][4] = str(renamed)
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.prepare(spec)

    def test_reserialized_test_query_ids_still_blocked(self):
        renamed = self.base / 'reformatted.json'
        renamed.write_text(json.dumps(json.loads(self.query.read_text()), separators=(',', ':')))
        self.assertNotEqual(gate.digest(renamed), gate.digest(self.query))
        spec = copy.deepcopy(self.plan['runs'][0]); spec['argv'][4] = str(renamed)
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.prepare(spec)

    def test_reserialized_test_remains_unregistered_during_readonly_inspection(self):
        renamed = self.base / 'reformatted.json'; renamed.write_text(json.dumps(json.loads(self.query.read_text()), separators=(',', ':')))
        spec = copy.deepcopy(self.plan['runs'][0]); spec['argv'][4] = str(renamed)
        meta = self.prepare(spec, inspect=True)
        workload = meta['workload_gate']['workloads'][0]
        self.assertEqual(workload['classification'], 'unknown'); self.assertFalse(workload['registered'])
        self.assertEqual(workload['registered_test_query_id_overlap'], ['synthetic-1'])
        self.assertFalse(workload['heldout_safe_qualification'])

    def test_unknown_query_never_qualified_without_registry(self):
        self.write_workload('tune')
        meta = self.prepare(registry=False)
        self.assertEqual(meta['workload_gate']['classification'], 'unknown')
        self.assertFalse(meta['workload_gate']['heldout_safe_qualification'])

    def test_double_dash_query_flag_cannot_bypass_gate(self):
        spec = copy.deepcopy(self.plan['runs'][0]); spec['argv'][3] = '--queries'
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.prepare(spec)

    def test_renamed_registered_test_in_explicit_inputs_blocked(self):
        renamed = self.base / 'unlabelled-input.json'; shutil.copyfile(self.query, renamed)
        spec = copy.deepcopy(self.plan['runs'][0]); spec['argv'] = [str(self.binary)]; spec['inputs'] = [str(renamed)]
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.prepare(spec)

    def test_test_sidecar_blocks_without_registry(self):
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.prepare(registry=False)

    def test_canonical_test_filename_blocks_without_sidecar(self):
        self.sidecar.unlink(); target = self.base / 'synthetic.test.workload.json'; self.query.rename(target)
        spec = copy.deepcopy(self.plan['runs'][0]); spec['argv'][4] = str(target)
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.prepare(spec, registry=False)

    def test_modified_registered_query_rejected(self):
        self.query.write_text(self.query.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'Registered workload content changed'):
            gate.load_registry(self.plan, self.base)

    def test_modified_sidecar_rejected(self):
        self.sidecar.write_text(self.sidecar.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'Registered metadata content changed'):
            gate.load_registry(self.plan, self.base)

    def test_rehashed_wrong_sidecar_query_hash_rejected(self):
        m = json.loads(self.sidecar.read_text()); m['queries_sha256'] = '0' * 64; self.dump(self.sidecar, m)
        self.write_registry(); self.plan['workload_registry'] = gate.identity(self.registry)
        with self.assertRaisesRegex(ValueError, 'not hash-bound'):
            gate.load_registry(self.plan, self.base)

    def test_registry_split_mismatch_rejected(self):
        self.write_registry('tune'); self.plan['workload_registry'] = gate.identity(self.registry)
        with self.assertRaisesRegex(ValueError, 'split disagrees'):
            gate.load_registry(self.plan, self.base)

    def test_registry_query_id_coverage_rejected(self):
        m = json.loads(self.sidecar.read_text()); m['items'][0]['query_id'] = 'wrong'; self.dump(self.sidecar, m)
        self.write_registry(); self.plan['workload_registry'] = gate.identity(self.registry)
        with self.assertRaisesRegex(ValueError, 'ID coverage'):
            gate.load_registry(self.plan, self.base)

    def test_actual_isolated_module_default_source_root(self):
        spec = copy.deepcopy(self.plan['runs'][0]); spec.pop('source_roots')
        meta = self.prepare(spec, inspect=True)
        self.assertEqual([s['path'] for s in meta['sources_before']], [str(self.module)])

    def test_wrong_hardcoded_source_root_rejected(self):
        other = self.base / 'wrong'; other.mkdir()
        spec = copy.deepcopy(self.plan['runs'][0]); spec['source_roots'] = [str(other)]
        with self.assertRaisesRegex(ValueError, 'Actual execution module root'):
            self.prepare(spec, inspect=True)

    def test_nested_module_cwd_requires_module_root(self):
        nested = self.module / 'cmd'; nested.mkdir()
        spec = copy.deepcopy(self.plan['runs'][0]); spec['cwd'] = str(nested); spec['source_roots'] = [str(nested)]
        with self.assertRaisesRegex(ValueError, 'Actual execution module root'):
            self.prepare(spec, inspect=True)

    def test_matching_seal_read_only_validation(self):
        ref = self.make_seal()
        verified = self.verify(ref, require_official=True)
        self.assertTrue(verified['consistency_valid']); self.assertTrue(verified['official_data_gate_passed'])
        self.assertFalse(verified['execution_performed'])
        self.assertEqual(json.loads(self.seal.read_text())['snapshot']['entire_evaluation_plan']['source_provenance'], self.plan['source_provenance'])

    def test_seal_is_create_only(self):
        self.make_seal()
        with self.assertRaises(FileExistsError):
            runner.create_seal(self.plan_path, self.seal)

    def test_modified_entire_plan_rejected(self):
        ref = self.make_seal(); self.plan['randomized_order_seed'] = 99; self.save_plan()
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_query_rejected_after_seal(self):
        ref = self.make_seal(); self.query.write_text(self.query.read_text() + ' ')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_sidecar_rejected_after_seal(self):
        ref = self.make_seal(); self.sidecar.write_text(self.sidecar.read_text() + ' ')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_go_source_rejected_after_seal(self):
        ref = self.make_seal(); (self.module / 'fixture.go').write_text('package fixture\nconst Value=2\n')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_non_go_support_source_rejected(self):
        ref = self.make_seal(); (self.module / 'support.txt').write_text('changed\n')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_binary_rejected(self):
        ref = self.make_seal(); self.binary.write_text(self.binary.read_text() + '# changed\n')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_configuration_rejected(self):
        ref = self.make_seal(); self.config.write_text('{"changed":true}\n')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_dataset_rejected(self):
        ref = self.make_seal(); self.data.write_text('{"changed":true}\n')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_registry_rejected(self):
        ref = self.make_seal(); self.registry.write_text(self.registry.read_text() + ' ')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_audit_rejected(self):
        ref = self.make_seal(); self.audit.write_text(self.audit.read_text() + ' ')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_modified_raw_audited_artifact_rejected(self):
        ref = self.make_seal(); self.raw_source.write_bytes(b'changed')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_wrong_query_dataset_binding_rejected(self):
        m = json.loads(self.sidecar.read_text()); m['dataset_sha256'] = '0' * 64; self.dump(self.sidecar, m)
        self.write_registry(); self.plan['workload_registry'] = gate.identity(self.registry)
        with self.assertRaisesRegex(ValueError, 'dataset SHA'):
            self.make_seal()

    def test_familybench_exact_shape_and_id_coverage(self):
        self.assertEqual(gate.query_ids(self.query), ['synthetic-1'])
        loaded = gate.load_registry(self.plan, self.base)
        self.assertEqual(loaded['entries'][0]['metadata_contents']['dataset_sha256'], gate.digest(self.data))

    def test_familybench_malformed_query_item_rejected(self):
        q = json.loads(self.query.read_text()); q['items'][0].pop('query'); self.dump(self.query, q)
        with self.assertRaisesRegex(ValueError, 'Malformed familybench'):
            gate.query_ids(self.query)

    def test_fresh_prelaunch_dataset_change_rejected_before_popen(self):
        ref = self.make_seal(); verified = self.verify(ref, require_official=True)
        expected = {'run': verified['verified_run_bindings']['synthetic-final'], 'source_tree_manifest_by_root': verified['source_tree_manifest_by_root'], 'verification_context': verified['verification_context'], 'snapshot_sha256': verified['snapshot_sha256']}
        self.data.write_text('{"mutated_after_last_verification":true}\n')
        run_dir = self.base / 'campaign' / 'synthetic-final'; run_dir.mkdir(parents=True)
        registry = gate.load_registry(self.plan, self.base)
        prepared = runner.prepare_run(self.plan['runs'][0], run_dir, run_dir.parent, runner.campaign_environment(), '0-3', 0.2, registry, inspect_heldout=True)
        real_popen = runner.subprocess.Popen
        def allow_git_only(argv, *args, **kwargs):
            if argv[0] != 'git':
                self.fail('No synthetic router should launch after a changed final input')
            return real_popen(argv, *args, **kwargs)
        with mock.patch.object(runner, 'prepare_run', return_value=prepared), mock.patch.object(runner.subprocess, 'Popen', side_effect=allow_git_only) as popen:
            with self.assertRaises(ValueError):
                runner.run_one(self.plan['runs'][0], run_dir, run_dir.parent, runner.campaign_environment(), '0-3', {}, self.base / 'status.json', 0, 0.2,
                               registry, expected_final=expected)
            self.assertFalse(any(call.args[0][0] == '/usr/bin/taskset' for call in popen.call_args_list))

    def test_fresh_prelaunch_non_go_source_change_rejected(self):
        ref = self.make_seal(); verified = self.verify(ref, require_official=True)
        expected = {'run': verified['verified_run_bindings']['synthetic-final'], 'source_tree_manifest_by_root': verified['source_tree_manifest_by_root'], 'verification_context': verified['verification_context'], 'snapshot_sha256': verified['snapshot_sha256']}
        (self.module / 'support.txt').write_text('mutated after verification\n')
        metadata, _, _, _, roots, _ = runner.prepare_run(self.plan['runs'][0], self.base / 'run', self.base / 'campaign', runner.campaign_environment(), '0-3', 0.2, gate.load_registry(self.plan, self.base), inspect_heldout=True)
        with self.assertRaises(ValueError):
            runner.check_fresh_final_binding(metadata, roots, self.base / 'run', self.base / 'campaign', expected)

    def test_modified_review_rejected(self):
        ref = self.make_seal(); self.review.write_text(self.review.read_text() + ' ')
        with self.assertRaises(ValueError): self.verify(ref)

    def test_missing_review_cannot_be_replaced_by_true_boolean(self):
        q = json.loads(self.qualification.read_text()); q.pop('review'); self.dump(self.qualification, q)
        self.plan['data_qualification'] = gate.identity(self.qualification); ref = self.make_seal()
        with self.assertRaisesRegex(ValueError, 'review record requires'):
            self.verify(ref, require_official=True)

    def test_provisional_data_remains_blocked_despite_valid_seal(self):
        self.write_qualification(eligible=False); ref = self.make_seal()
        self.assertTrue(self.verify(ref)['consistency_valid'])
        with self.assertRaisesRegex(ValueError, 'provisional'):
            self.verify(ref, require_official=True)

    def test_provisional_registry_metadata_cannot_be_promoted(self):
        registry = json.loads(self.registry.read_text()); registry['provenance']['formal_baseline_eligible'] = False; self.dump(self.registry, registry)
        self.plan['workload_registry'] = gate.identity(self.registry); ref = self.make_seal()
        with self.assertRaisesRegex(ValueError, 'Registry preserves provisional'):
            self.verify(ref, require_official=True)

    def test_provisional_workload_metadata_cannot_be_promoted(self):
        metadata = json.loads(self.sidecar.read_text()); metadata['formal_baseline_eligible'] = False; self.dump(self.sidecar, metadata)
        self.write_registry(); self.plan['workload_registry'] = gate.identity(self.registry); ref = self.make_seal()
        with self.assertRaisesRegex(ValueError, 'Workload metadata preserves provisional'):
            self.verify(ref, require_official=True)

    def test_expired_official_review_window_rejected(self):
        expires = '2000-01-01T00:00:00Z'
        r = json.loads(self.review.read_text()); r['valid_until_utc'] = expires; self.dump(self.review, r)
        q = json.loads(self.qualification.read_text()); q['valid_until_utc'] = expires; q['review'] = gate.identity(self.review); self.dump(self.qualification, q)
        self.plan['data_qualification'] = gate.identity(self.qualification); ref = self.make_seal()
        with self.assertRaisesRegex(ValueError, 'freshness window'):
            self.verify(ref, require_official=True)

    def test_known_community_raw_source_blocked_despite_labels(self):
        a = json.loads(self.audit.read_text()); a['raw_source_sha256'] = ['d92173127e9a5cbf8ecb5b4d50ab03f68deb7f8ddff73648b8ffb33c70ab4801']; self.dump(self.audit, a)
        r = json.loads(self.review.read_text()); r['reviewed_audit_sha256'] = gate.digest(self.audit); self.dump(self.review, r)
        q = json.loads(self.qualification.read_text()); q['audit'] = gate.identity(self.audit); q['review'] = gate.identity(self.review); self.dump(self.qualification, q)
        self.plan['data_qualification'] = gate.identity(self.qualification); ref = self.make_seal()
        with self.assertRaisesRegex(ValueError, 'community raw source'):
            self.verify(ref, require_official=True)

    def test_known_provisional_dataset_hash_blocked(self):
        policy = self.base / 'synthetic-policy.json'; self.dump(policy, {'denied_normalized_inputs': [{'sha256': gate.digest(self.data)}]})
        with mock.patch.object(gate, 'SOURCE_POLICY', policy):
            ref = self.make_seal()
            with self.assertRaisesRegex(ValueError, 'Known provisional community/July'):
                self.verify(ref, require_official=True)

    def test_unknown_workload_cannot_be_sealed(self):
        new = self.base / 'unknown.json'; new.write_text('[{"id":"unknown"}]')
        self.plan['runs'][0]['argv'][4] = str(new)
        with self.assertRaisesRegex(ValueError, 'predeclared SHA'):
            self.make_seal()

    def test_final_plan_without_seal_rejected_before_launch(self):
        output = self.base / 'must-not-launch'
        result = subprocess.run([sys.executable, str(Path(runner.__file__).resolve()), 'run', '--plan', str(self.plan_path), '--out', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2); self.assertIn('requires --seal', result.stderr); self.assertFalse(output.exists())

    def test_diagnostic_qualification_claim_rejected(self):
        with self.assertRaisesRegex(ValueError, 'cannot grant'):
            gate.reject_execution_claims({'heldout_safe': True})

    def test_runtime_environment_change_invalidates_seal(self):
        ref = self.make_seal()
        with mock.patch.dict(os.environ, {'GOGC': '87'}):
            with self.assertRaises(ValueError): self.verify(ref)


if __name__ == '__main__':
    unittest.main(verbosity=2)
