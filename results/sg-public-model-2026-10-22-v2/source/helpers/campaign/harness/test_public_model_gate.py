"""Synthetic-only public-tier coverage. Never reads SG datasets or query outcomes."""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import campaign_gate as gate
import run_campaign as runner
import test_campaign_gate as owner_tests


class PublicModelGateTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_tests.GateTests(methodName='test_matching_seal_read_only_validation')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        f.plan['evaluation_mode'] = gate.PUBLIC_FINAL_MODE
        f.plan['source_provenance'] = {'source_status': 'provisional_community_model',
                                     'formal_baseline_eligible': False, 'latest_official_transit_feed': False}
        self.rewrite(f.registry, lambda r: r['provenance'].update(f.plan['source_provenance']))
        f.plan['workload_registry'] = gate.identity(f.registry)
        expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
        f.dump(f.audit, {'schema': 'public-model-data-audit-v1', 'data_origin': 'public_model',
                         'formal_baseline_eligible': False, 'latest_official_transit_feed': False,
                         'coverage': {'bus': True, 'rail': True}, 'acquired_utc': '2000-01-01T00:00:00Z',
                         'model_assumptions': ['Synthetic time/frequency model only'],
                         'limitations': ['Not a real timetable or authenticity attestation'],
                         'normalized_input_sha256': [gate.digest(f.data)],
                         'sources': [{'source_url': 'https://example.invalid/synthetic-public-source',
                                      'source_owner': 'Synthetic fixture', 'acquired_utc': '2000-01-01T00:00:00Z',
                                      'artifact': gate.identity(f.raw_source)}]})
        f.dump(f.review, {'schema': 'public-model-data-review-v1', 'evaluation_tier': 'public_model',
                          'decision': 'accept_for_bound_public_model_evaluation_only',
                          'reviewed_audit_sha256': gate.digest(f.audit), 'reviewer': 'synthetic reviewer',
                          'basis': ['Synthetic schema review only, not real data qualification'],
                          'approved_input_sha256': [gate.digest(f.data)],
                          'reviewed_utc': '2000-01-02T00:00:00Z', 'valid_until_utc': expires})
        f.dump(f.qualification, {'schema': 'public-model-evaluation-qualification-v1',
                                'evaluation_tier': 'public_model', 'source_status': 'reviewed_public_model_bus_and_rail',
                                'formal_baseline_eligible': False, 'latest_official_transit_feed': False,
                                'audit': gate.identity(f.audit), 'review': gate.identity(f.review),
                                'inputs': [gate.identity(f.data)], 'valid_until_utc': expires})
        self.rebind()

    def rewrite(self, path, mutate):
        value = json.loads(Path(path).read_text())
        mutate(value)
        self.f.dump(path, value)

    def rebind(self):
        f = self.f
        self.rewrite(f.review, lambda r: r.update(reviewed_audit_sha256=gate.digest(f.audit)))
        self.rewrite(f.qualification, lambda q: q.update(audit=gate.identity(f.audit), review=gate.identity(f.review)))
        f.plan['data_qualification'] = gate.identity(f.qualification)
        f.save_plan()

    def verify(self, ref, **kwargs):
        return runner.verify_seal(self.f.plan_path, ref, require_public_model=True, **kwargs)

    def test_public_mode_uses_distinct_seal_and_review_not_official(self):
        f = self.f
        ref = f.make_seal()
        result = self.verify(ref)
        self.assertEqual(json.loads(f.seal.read_text())['schema'], gate.PUBLIC_SEAL_SCHEMA)
        self.assertTrue(result['public_model_data_gate_passed'])
        self.assertFalse(result['official_data_gate_passed'])
        self.assertFalse(result['execution_performed'])
        self.assertFalse(result['data_qualification']['formal_baseline_eligible'])
        self.assertFalse(result['data_qualification']['latest_official_transit_feed'])
        self.assertFalse(result['data_qualification']['official_source_authenticity_established'])
        provenance = result['verified_run_bindings']['synthetic-final']['workload_gate']['registry_provenance']
        self.assertEqual(provenance['source_status'], 'provisional_community_model')

    def test_legacy_official_flag_never_accepts_public_tier(self):
        ref = self.f.make_seal()
        with self.assertRaisesRegex(ValueError, 'not official qualification'):
            runner.verify_seal(self.f.plan_path, ref, require_official=True)

    def test_official_mode_does_not_accept_public_qualification(self):
        self.f.plan['evaluation_mode'] = 'final_evaluation'
        ref = self.f.make_seal()
        with self.assertRaisesRegex(ValueError, 'official-data qualification schema'):
            runner.verify_seal(self.f.plan_path, ref, require_official=True)
        with self.assertRaisesRegex(ValueError, 'requires public_model_final_evaluation'):
            self.verify(ref)

    def test_known_provisional_hashes_allowed_only_in_explicit_public_tier(self):
        f = self.f
        policy = f.base / 'denied-synthetic-policy.json'
        f.dump(policy, {'denied_normalized_inputs': [{'sha256': gate.digest(f.data)}],
                        'known_community_raw_sha256': [gate.digest(f.raw_source)]})
        with mock.patch.object(gate, 'SOURCE_POLICY', policy):
            self.assertTrue(self.verify(f.make_seal())['public_model_data_gate_passed'])

    def test_public_mode_without_seal_rejected_before_launch(self):
        f = self.f
        output = f.base / 'never-launched'
        result = subprocess.run([sys.executable, str(Path(runner.__file__).resolve()), 'run',
                                 '--plan', str(f.plan_path), '--out', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires --seal', result.stderr)
        self.assertFalse(output.exists())

    def test_public_mode_cannot_bypass_diagnostic_heldout_gate(self):
        with self.assertRaisesRegex(ValueError, 'mode-specific seal'):
            gate.reject_execution_claims(self.f.plan)
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            self.f.prepare()

    def test_public_seal_still_requires_registered_test_workloads(self):
        f = self.f
        f.write_workload('tune'); f.write_registry('tune')
        f.plan['workload_registry'] = gate.identity(f.registry)
        with self.assertRaisesRegex(ValueError, 'registered test splits'):
            f.make_seal()

    def test_public_seal_still_requires_exact_query_dataset_binding(self):
        f = self.f
        self.rewrite(f.sidecar, lambda m: m.update(dataset_sha256='0' * 64))
        f.write_registry(); f.plan['workload_registry'] = gate.identity(f.registry)
        with self.assertRaisesRegex(ValueError, 'dataset SHA'):
            f.make_seal()

    def test_public_seal_still_rejects_unknown_renamed_or_reserialized_queries(self):
        f = self.f
        query = f.base / 'unknown.json'
        query.write_text(json.dumps(json.loads(f.query.read_text()), separators=(',', ':')))
        f.plan['runs'][0]['argv'][4] = str(query)
        with self.assertRaisesRegex(ValueError, 'predeclared SHA'):
            f.make_seal()

    def test_reserialized_test_ids_in_explicit_json_inputs_cannot_hide(self):
        f = self.f
        query = f.base / 'unlabelled-input.json'
        query.write_text(json.dumps(json.loads(f.query.read_text()), separators=(',', ':')))
        spec = dict(f.plan['runs'][0], argv=[str(f.binary)], inputs=[str(query)])
        with self.assertRaisesRegex(ValueError, 'Held-out/test execution'):
            f.prepare(spec)
        meta = f.prepare(spec, inspect=True)
        self.assertEqual(meta['workload_gate']['workloads'][0]['registered_test_query_id_overlap'], ['synthetic-1'])

    def test_public_data_flag_cli_and_legacy_official_flag_are_separate(self):
        f = self.f
        ref = f.make_seal()
        command = [sys.executable, str(Path(runner.__file__).resolve()), 'validate-seal', '--plan', str(f.plan_path),
                   '--seal', ref['path'], '--seal-sha256', ref['sha256']]
        public = subprocess.run(command + ['--require-public-model-data'], capture_output=True, text=True)
        self.assertEqual(public.returncode, 0, public.stderr)
        self.assertTrue(json.loads(public.stdout)['public_model_data_gate_passed'])
        official = subprocess.run(command + ['--require-official-data'], capture_output=True, text=True)
        self.assertEqual(official.returncode, 2)
        self.assertIn('not official qualification', official.stderr)

    def test_public_explicit_false_eligibility_flags_required(self):
        self.rewrite(self.f.audit, lambda a: a.pop('latest_official_transit_feed'))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'explicitly deny'):
            self.verify(self.f.make_seal())

    def test_public_tier_rejects_official_claim_in_registry(self):
        f = self.f
        self.rewrite(f.registry, lambda r: r['provenance'].update(formal_baseline_eligible=True))
        f.plan['workload_registry'] = gate.identity(f.registry)
        with self.assertRaisesRegex(ValueError, 'cannot make formal/latest-official'):
            self.verify(f.make_seal())

    def test_public_tier_requires_model_assumptions_and_limitations(self):
        self.rewrite(self.f.audit, lambda a: a.update(limitations=[]))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'nonempty limitations'):
            self.verify(self.f.make_seal())

    def test_public_audit_cannot_be_replaced_with_an_official_schema(self):
        self.rewrite(self.f.audit, lambda a: a.update(schema='official-lta-data-audit-v1'))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'modeled origin'):
            self.verify(self.f.make_seal())

    def test_public_review_must_accept_exact_audit_for_public_use(self):
        self.rewrite(self.f.review, lambda r: r.update(decision='accept_for_bound_evaluation_only'))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'accepted public-model'):
            self.verify(self.f.make_seal())

    def test_public_review_must_cover_exact_normalized_hashes(self):
        self.rewrite(self.f.review, lambda r: r.update(approved_input_sha256=['0' * 64]))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'exact normalized input hashes'):
            self.verify(self.f.make_seal())

    def test_public_qualification_rejects_extra_unused_dataset(self):
        f = self.f
        extra = f.base / 'unused.json'; extra.write_text('{"unused":true}')
        self.rewrite(f.qualification, lambda q: q['inputs'].append(gate.identity(extra)))
        hashes = [gate.digest(f.data), gate.digest(extra)]
        self.rewrite(f.audit, lambda a: a.update(normalized_input_sha256=hashes))
        self.rewrite(f.review, lambda r: r.update(approved_input_sha256=hashes))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'exactly equal'):
            self.verify(f.make_seal())

    def test_expired_public_review_window_rejected(self):
        self.rewrite(self.f.review, lambda r: r.update(valid_until_utc='2000-01-03T00:00:00Z'))
        self.rewrite(self.f.qualification, lambda q: q.update(valid_until_utc='2000-01-03T00:00:00Z'))
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'validity window'):
            self.verify(self.f.make_seal())

    def test_public_seal_binds_every_critical_dependency(self):
        f = self.f
        for path in (f.plan_path, f.query, f.sidecar, f.registry, f.data, f.config, f.binary,
                     f.module / 'fixture.go', f.module / 'support.txt', f.audit, f.review,
                     f.qualification, f.raw_source):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                seal = f.base / ('seal-' + str(len(list(f.base.glob('seal-*')))) + '.json')
                ref = runner.create_seal(f.plan_path, seal)
                path.write_bytes(original + b' ')
                try:
                    with self.assertRaises(ValueError):
                        self.verify(ref)
                finally:
                    path.write_bytes(original)

    def test_public_prelaunch_change_blocks_before_child_launch(self):
        f = self.f
        verified = self.verify(f.make_seal())
        expected = {'run': verified['verified_run_bindings']['synthetic-final'],
                    'source_tree_manifest_by_root': verified['source_tree_manifest_by_root'],
                    'verification_context': verified['verification_context'], 'snapshot_sha256': verified['snapshot_sha256']}
        self.rewrite(f.audit, lambda a: a.update(limitations=['Changed after verification']))
        metadata, _, _, _, roots, _ = runner.prepare_run(f.plan['runs'][0], f.base / 'run', f.base / 'campaign',
            runner.campaign_environment(), '0-3', .2, gate.load_registry(f.plan, f.base), inspect_heldout=True)
        with self.assertRaises(ValueError):
            runner.check_fresh_final_binding(metadata, roots, f.base / 'run', f.base / 'campaign', expected)

    def run_synthetic(self, tamper=False):
        # CPU 8 is the explicitly assigned synthetic-test slot, not an SG run.
        f = self.f
        if tamper:
            f.binary.write_text('#!/bin/sh\nprintf changed > ' + str(f.raw_source) + '\nexit 0\n')
        f.save_plan()
        ref = runner.create_seal(f.plan_path, f.seal, cpus='8', sample_s=.05)
        args = argparse.Namespace(plan=str(f.plan_path), out=str(f.base / 'execution'),
                                  seal=ref['path'], seal_sha256=ref['sha256'], cpus='8', sample_s=.05,
                                  continue_on_failure=False)
        code = runner.run(args)
        result = json.loads((Path(args.out) / 'synthetic-final/result.json').read_text())
        return code, result, json.loads((Path(args.out) / 'status.json').read_text())

    def test_public_synthetic_execution_uses_public_gate_at_every_guard(self):
        code, result, status = self.run_synthetic()
        self.assertEqual(code, 0)
        self.assertTrue(result['final_seal_integrity_after_run'])
        self.assertFalse(result['formal_baseline_eligible'])
        self.assertFalse(result['latest_official_transit_feed'])
        self.assertFalse(status['final_evaluation_gate']['official_data_gate_passed'])
        self.assertTrue(status['final_evaluation_gate']['public_model_data_gate_passed'])

    def test_public_persistent_mutation_during_process_invalidates_result(self):
        code, result, _ = self.run_synthetic(tamper=True)
        self.assertEqual(code, 1)
        self.assertEqual(result['returncode'], 0)
        self.assertFalse(result['final_seal_integrity_after_run'])
        self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
