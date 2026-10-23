#!/usr/bin/env python3
"""Static-authored tiny four-stage metadata tests. NEVER run during measurement."""
import copy
import importlib.util
from pathlib import Path
import types
import unittest

HERE = Path(__file__).resolve().parent


class StageContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('finite_context_v2_under_test', HERE / 'adapter_v2.py')
        cls.a = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.a)

    def ref(self, name, value):
        # Unit-only bound-document doubles. Identity cryptography stays in the
        # already-qualified generic helper and is NOT simulated as acceptance.
        ref = {'path': '/__TINY_SYNTHETIC_METADATA__/' + name, 'sha256': 'a' * 64, 'bytes': 1}
        self.documents[ref['path']] = value
        return ref

    @staticmethod
    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def setUp(self):
        self.documents = {}
        self.w = types.SimpleNamespace(bound=lambda _s, ref: self.documents[ref['path']], require=self.require)
        self.s = types.SimpleNamespace(canonical=lambda value: Path(value))
        self.manifest = {'stages': []}
        self.ready = {'stages': []}
        self.plans = []
        outputs = []
        for index, (lane, block, count, offset) in enumerate(self.a.STAGES):
            cells = list(range(count)) if block == 0 else list(reversed(range(count)))
            ids = ['b%d-%s-synthetic-%03d' % (block, lane, cell) for cell in cells]
            rows = [{'id': rid, 'state': 'PLANNED_UNSTARTED'} for rid in ids]
            plan = {'runs': [{'id': rid} for rid in ids], 'continue_on_failure': False,
                    'finite_lane': {'stage': lane, 'block': block, 'all_state_rows': rows}, 'memory_admission': {}}
            self.plans.append(plan)
            plan_ref = self.ref('plan-%d' % index, plan)
            parser_ref = self.ref('parser-%d' % index, {})
            envelope_ref = self.ref('envelope-%d' % index, {})
            specs_ref = self.ref('specs-%d' % index, {})
            freeze = {'plan': plan_ref, 'offered': count, 'unoffered': 0,
                      'parser_coverage': parser_ref, 'actual_envelopes': envelope_ref,
                      'prospective_specs': specs_ref, 'memory_admission': {}}
            root = self.a.ROOT / 'experiments' / ('%s-v1-b%d-run' % ('cap96' if lane == 'caps' else 'native216', block))
            stage = {'stage': lane, 'block': block, 'plan': plan_ref,
                     'preparation_freeze': self.ref('freeze-%d' % index, freeze),
                     'parser_coverage': parser_ref, 'actual_runner_envelopes': envelope_ref,
                     'future_serving_root': str(root)}
            self.manifest['stages'].append(stage)
            self.ready['stages'].append(dict(copy.deepcopy(stage), offered=count, original_slots=count, unoffered=0))
            def output(rid, role, name):
                return {'stage': lane, 'block': block, 'run_id': rid, 'role': role,
                        'raw_path': str(root / rid / 'artifact' / name),
                        'frozen_bindings': {'plan_sha256': plan_ref['sha256']},
                        'allow_raw_retirement': True, 'retire_receipt_paths': ['/__UNUSED_SYNTHETIC_RECEIPT__']}
            for rid in ids[:48 if lane == 'caps' else 36]:
                outputs.append(output(rid, 'proof-summary', 'summary.json'))
            if lane == 'native':
                for rid in ids[:24]:
                    for name in ('identity-index.json', 'core_ch-index.json', 'target-partitions.json'):
                        outputs.append(output(rid, 'proof-sidecar', name))
        outputs.extend({'role': 'redundant-metrics'} for _ in range(8))
        authority = self.ref('four-stage-manifest', self.manifest)
        authority['sha256'] = self.a.MANIFEST_SHA
        self.ready['four_stage_plan_manifest'] = authority
        self.request = {'outputs': outputs, 'four_stage_plan_manifest': authority}
        request_ref = self.ref('request', self.request)
        inventory_ref = self.ref('inventory', {})
        self.admission = {'request': self.request, 'request_sha256': request_ref['sha256'],
                          'inventory_sha256': inventory_ref['sha256'], 'measurement_lock': str(self.a.LOCK)}
        self.ready.update(storage_admission=self.ref('admission', self.admission), storage_request=request_ref,
                          before_creation_inventory=inventory_ref)
        self.documents[self.a.READY['path']] = self.ready

    def context(self, index=0):
        return self.a.context(self.w, self.s, index)

    def reject(self, index=0):
        with self.assertRaises((RuntimeError, KeyError, TypeError, ValueError)):
            self.context(index)

    def test_exact_four_counts_offsets_and_separate_lane_reverse(self):
        for index, (_lane, _block, count, offset) in enumerate(self.a.STAGES):
            with self.subTest(index=index):
                result = self.context(index)
                self.assertEqual(len(result[2]['runs']), count)
                self.assertEqual(result[-1], offset)
        ids = [r['id'][3:] for plan in self.plans for r in plan['runs']]
        self.assertNotEqual(ids[156:], list(reversed(ids[:156])))  # Mixed312 is not one reverse pair.

    def test_native_offers_without_eligible_raw_are_still_present(self):
        result = self.context(2)
        self.assertEqual(len(result[4]), 108)
        self.assertTrue(any(not entries for entries in result[4].values()))

    def test_all8_index_and_bool_indices_are_refused(self):
        for index in (-1, 4, 7, True, False, '0'):
            with self.subTest(index=index):
                self.reject(index)

    def test_reordered_four_stage_manifest_is_refused(self):
        self.manifest['stages'][0], self.manifest['stages'][1] = self.manifest['stages'][1], self.manifest['stages'][0]
        self.reject()

    def test_runtime84_shape_is_refused(self):
        self.plans[0]['finite_lane']['all_state_rows'] = self.plans[0]['finite_lane']['all_state_rows'][:47]
        self.reject()

    def test_changed_continue_on_failure_is_refused(self):
        self.plans[0]['continue_on_failure'] = True
        self.reject()

    def test_global_duplicate_id_is_refused(self):
        rid = self.plans[0]['runs'][0]['id']
        self.plans[2]['runs'][0]['id'] = rid
        self.plans[2]['finite_lane']['all_state_rows'][0]['id'] = rid
        self.reject()

    def test_one_lane_reverse_mismatch_is_refused(self):
        self.plans[3]['runs'][0], self.plans[3]['runs'][1] = self.plans[3]['runs'][1], self.plans[3]['runs'][0]
        rows = self.plans[3]['finite_lane']['all_state_rows']
        rows[0], rows[1] = rows[1], rows[0]
        self.reject()

    def test_wrong_future_serving_root_is_refused(self):
        self.manifest['stages'][0]['future_serving_root'] = '/__WRONG_STAGE_ROOT__'
        self.reject()

    def test_changed_storage_request_and_inventory_ancestry_are_refused(self):
        self.admission['inventory_sha256'] = 'f' * 64
        self.reject()

    def test_nonexact_storage_census_is_refused(self):
        self.request['outputs'].pop()
        self.reject()

    def test_cross_stage_raw_identity_is_refused(self):
        self.request['outputs'][0]['raw_path'] = '/__WRONG_STAGE__/artifact/summary.json'
        self.reject()


if __name__ == '__main__':
    unittest.main()
