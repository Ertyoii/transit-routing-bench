#!/usr/bin/env python3
"""STATIC-AUTHORED ONLY. Do not import/run until the owner grants a quiet slot.

Contract tests for the required actual-control review gate. The initial adapter
has no validate_actual_control_review function yet: qualification MUST remain
red until that small gate is implemented/reviewed and called before any intent.
No benchmark, scientific reader, router, launch or measurement-output access.
"""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import types
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'harness/run_campaign.py'
BASE_SHA = '206076513f4fb023e38deb9aee96de07c8c885b579e716c56350c7f73ff4480b'


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class MemoryDocuments:
    """Tiny synthetic metadata only. No filesystem-backed results or raw files."""
    def __init__(self):
        self.documents = {}

    def add(self, path, value):
        payload = canonical_bytes(value)
        ref = {'path': path, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
        self.documents[path] = (copy.deepcopy(value), ref)
        return copy.deepcopy(ref)

    def bound(self, reference):
        value, actual = self.documents[reference['path']]
        if any(reference.get(key) != actual[key] for key in ('path', 'sha256', 'bytes')):
            raise RuntimeError('Synthetic changed reference')
        return copy.deepcopy(value)


class ActualControlContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Executed ONLY in the later authorized qualification slot. Extract the
        # exact accepted base function without importing/running the whole runner.
        source = BASE.read_bytes()
        if hashlib.sha256(source).hexdigest() != BASE_SHA:
            raise RuntimeError('Qualified base runner source changed')
        tree = ast.parse(source, filename=str(BASE))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'prepared_binding']
        if len(functions) != 1:
            raise RuntimeError('Qualified base prepared_binding is not unique')
        module = ast.Module(body=functions, type_ignores=[])
        namespace = {}
        exec(compile(module, str(BASE), 'exec'), namespace)
        cls.project = staticmethod(namespace['prepared_binding'])
        spec = importlib.util.spec_from_file_location('finite_adapter_under_test', HERE / 'adapter.py')
        cls.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.adapter)

    def setUp(self):
        self.docs = MemoryDocuments()
        self.w = types.SimpleNamespace(bound=lambda _s, ref: self.docs.bound(ref), require=self.require)
        self.s = object()
        self.rid = 'b0-synthetic-original-slot'
        self.root = Path('/__SYNTHETIC_ACTUAL_STAGE__')
        self.preflight_run = Path('/__REMAINING_FINITE_NOT_EXECUTED__') / self.rid
        self.preflight_root = Path('/__NO_REMAINING_FINITE_CAMPAIGN__')
        self.input_ref = {'path': '/__SYNTHETIC_SOURCE_INPUT__', 'sha256': '1' * 64, 'bytes': 19}
        self.preflight = {
            'id': self.rid, 'argv': ['/usr/bin/taskset', '-c', '0-3', '/__SYNTHETIC_BINARY__',
                                    '-out', str(self.preflight_run / 'artifact'),
                                    '-campaign', str(self.preflight_root)],
            'cwd': '/__SYNTHETIC_SOURCE__', 'timeout_s': 8.0, 'term_grace_s': 3.0,
            'binary': {'path': '/__SYNTHETIC_BINARY__', 'sha256': '2' * 64, 'bytes': 200},
            'inputs': [copy.deepcopy(self.input_ref)],
            'sources_before': [{'path': '/__SYNTHETIC_SOURCE__', 'go_source_hash_sha256': '3' * 64,
                                'commit': 'synthetic', 'status_porcelain': ''}],
            'environment': {'GOMAXPROCS': '4', 'GOGC': '100', 'GOMEMLIMIT': '4GiB'},
            'requested_cpu_affinity': '0-3', 'monitor_cpu_affinity': [0, 1, 2, 3],
            'sampled_rss_safety_stop_bytes': 5_500_000_000,
            'rss_sample_interval_s': 0.1,
            'workload_gate': {'classification': 'registered_development', 'workloads': []},
        }
        self.envelope_ref = self.docs.add('/__SYNTHETIC_PREFLIGHT__/RUNNER_ENVELOPE_PREFLIGHT.json',
                                           {'runs': [self.preflight], 'router_executed': False})
        self.stage = {'plan': {'path': '/__SYNTHETIC_PLAN__', 'sha256': '4' * 64, 'bytes': 100},
                      'actual_runner_envelopes': copy.deepcopy(self.envelope_ref),
                      'future_serving_root': str(self.root), 'stage': 'caps', 'block': 0}
        self.plan = {'runs': [{'id': self.rid, 'inputs': [self.input_ref['path'], self.envelope_ref['path']]}],
                     'memory_admission': {'base_runner': {'path': str(BASE), 'sha256': BASE_SHA}}}
        self.actual = copy.deepcopy(self.preflight)
        self.actual['argv'] = [arg.replace(str(self.preflight_run), str(self.root / self.rid))
                              .replace(str(self.preflight_root), str(self.root))
                              for arg in self.actual['argv']]
        # The preflight envelope cannot include its own final identity. The final
        # plan appends it once; every actual command MUST bind that exact input.
        self.actual['inputs'].append(copy.deepcopy(self.envelope_ref))
        self.actual['monitor_cpu_affinity'] = [6, 7]
        self.actual['rss_sample_interval_s'] = 0.2
        self.actual.update(pid=123456, pgid=123456, process_start_ticks='123456',
                           started_utc='SYNTHETIC_ONLY')
        self.command_ref = self.docs.add(str(self.root / self.rid / 'command.json'), self.actual)
        self.records = {self.rid: {'id': self.rid, 'command': dict(self.command_ref, state='PRESENT')}}
        self.review = {
            'schema': 'finite-four-stage-actual-control-review-v1',
            'scope': 'LOSSLESS_PRESERVATION_ONLY',
            'headline_quality_latency_acceptance': False,
            'projection': 'QUALIFIED_BASE_RUNNER_PREPARED_BINDING',
            'commands': [{'id': self.rid, 'command': copy.deepcopy(self.command_ref),
                          'preflight_envelope': copy.deepcopy(self.envelope_ref),
                          'cadence': {'preflight': 0.1, 'actual': 0.2,
                                      'disposition': 'EXPLICITLY_REVIEWED_PRESERVATION_ONLY_DEVIATION'}}],
        }

    @staticmethod
    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def validate(self):
        gate = getattr(self.adapter, 'validate_actual_control_review', None)
        self.assertTrue(callable(gate), 'Required actual-control gate is not implemented; no qualification allowed')
        return gate(self.w, self.s, self.stage, self.plan, self.records, self.review,
                    prepared_binding=self.project)

    def replace_actual(self):
        self.command_ref = self.docs.add(str(self.root / self.rid / 'command.json'), self.actual)
        self.records[self.rid]['command'] = dict(self.command_ref, state='PRESENT')
        self.review['commands'][0]['command'] = copy.deepcopy(self.command_ref)

    def expect_refusal(self):
        with self.assertRaises((RuntimeError, ValueError, TypeError, KeyError)):
            self.validate()

    def test_qualified_projection_excludes_monitor_affinity_but_not_requested_affinity(self):
        before = self.project(self.preflight, self.preflight_run, self.preflight_root)
        actual = self.project(self.actual, self.root / self.rid, self.root)
        actual['inputs'].pop()  # Only the exact final-plan self-input is separately reconciled.
        self.assertEqual(before, actual)
        self.assertNotIn('monitor_cpu_affinity', before)
        self.assertNotIn('rss_sample_interval_s', before)  # Therefore cadence requires its OWN explicit review.
        self.actual['requested_cpu_affinity'] = '2-5'
        actual = self.project(self.actual, self.root / self.rid, self.root)
        actual['inputs'].pop()
        self.assertNotEqual(before, actual)

    def test_exact_reviewed_actual_point2_is_preservable_not_headline_accepted(self):
        self.validate()
        self.assertEqual(self.actual['rss_sample_interval_s'], 0.2)
        self.assertEqual(self.review['commands'][0]['cadence']['preflight'], 0.1)
        self.assertIs(self.review['headline_quality_latency_acceptance'], False)

    def test_unchanged_exact_point1_is_preservable(self):
        self.actual['rss_sample_interval_s'] = 0.1
        self.replace_actual()
        self.review['commands'][0]['cadence'].update(actual=0.1, disposition='UNCHANGED')
        self.validate()

    def test_missing_review_is_refused(self):
        self.review = None
        self.expect_refusal()

    def test_unapproved_point2_cannot_be_called_unchanged(self):
        self.review['commands'][0]['cadence']['disposition'] = 'UNCHANGED'
        self.expect_refusal()

    def test_point2_cannot_be_relabelled_point1(self):
        self.review['commands'][0]['cadence']['actual'] = 0.1
        self.expect_refusal()

    def test_approval_for_point2_does_not_cover_actual_point3(self):
        self.actual['rss_sample_interval_s'] = 0.3
        self.replace_actual()
        self.expect_refusal()

    def test_malformed_actual_cadence_is_refused_even_if_receipt_matches(self):
        for value in (None, True, False, '0.2', 0, -0.2, float('nan'), float('inf')):
            with self.subTest(value=repr(value)):
                # A malformed JSON value must fail before a raw hash/archive;
                # nonfinite values are inserted directly into this tiny reader.
                self.actual['rss_sample_interval_s'] = value
                if isinstance(value, float) and value != value or value == float('inf'):
                    self.docs.documents[self.command_ref['path']][0]['rss_sample_interval_s'] = value
                else:
                    self.replace_actual()
                self.review['commands'][0]['cadence']['actual'] = value
                self.expect_refusal()

    def test_malformed_preflight_cadence_is_refused(self):
        for value in (None, True, '0.1', 0, -0.1, float('nan'), float('inf')):
            with self.subTest(value=repr(value)):
                self.review['commands'][0]['cadence']['preflight'] = value
                self.expect_refusal()

    def test_preservation_approval_must_not_claim_quality_or_latency_acceptance(self):
        self.review['headline_quality_latency_acceptance'] = True
        self.expect_refusal()

    def test_other_scope_is_refused(self):
        self.review['scope'] = 'HEADLINE_LATENCY_ACCEPTANCE'
        self.expect_refusal()

    def test_missing_or_duplicate_consumed_command_review_is_refused(self):
        one = copy.deepcopy(self.review['commands'][0])
        for commands in ([], [one, copy.deepcopy(one)]):
            with self.subTest(count=len(commands)):
                self.review['commands'] = commands
                self.expect_refusal()

    def test_stale_actual_command_identity_is_refused(self):
        self.review['commands'][0]['command']['sha256'] = 'f' * 64
        self.expect_refusal()

    def test_wrong_preflight_envelope_identity_is_refused(self):
        self.review['commands'][0]['preflight_envelope']['sha256'] = 'f' * 64
        self.expect_refusal()

    def test_exact_final_self_preflight_input_is_mandatory(self):
        self.actual['inputs'].pop()
        self.replace_actual()
        self.expect_refusal()

    def test_final_self_preflight_input_cannot_be_duplicated(self):
        self.actual['inputs'].append(copy.deepcopy(self.envelope_ref))
        self.replace_actual()
        self.expect_refusal()

    def test_final_self_preflight_input_must_match_hash_bytes_and_path(self):
        original = copy.deepcopy(self.actual)
        for key, value in (('sha256', 'f' * 64), ('bytes', 999), ('path', '/__WRONG_ENVELOPE__')):
            with self.subTest(key=key):
                self.actual = copy.deepcopy(original)
                self.actual['inputs'][-1][key] = value
                self.replace_actual()
                self.expect_refusal()

    def test_final_plan_must_append_exact_envelope_input_once(self):
        self.plan['runs'][0]['inputs'].pop()
        self.expect_refusal()

    def test_original_source_input_binary_and_requested_affinity_stay_exact(self):
        original = copy.deepcopy(self.actual)
        changes = [('input', lambda d: d['inputs'][0].update(sha256='f' * 64)),
                   ('source', lambda d: d['sources_before'][0].update(go_source_hash_sha256='f' * 64)),
                   ('binary', lambda d: d['binary'].update(sha256='f' * 64)),
                   ('requested affinity', lambda d: d.update(requested_cpu_affinity='2-5'))]
        for label, change in changes:
            with self.subTest(label=label):
                self.actual = copy.deepcopy(original)
                change(self.actual)
                self.replace_actual()
                self.expect_refusal()

    def test_control_gate_is_called_before_first_preservation_write(self):
        source = (HERE / 'adapter.py').read_bytes()
        tree = ast.parse(source)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'preserve_stage')
        gates = [node.lineno for node in ast.walk(function) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'validate_actual_control_review']
        writes = [node.lineno for node in ast.walk(function) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == 'write_doc']
        self.assertTrue(gates, 'preserve_stage lacks required actual-control gate')
        self.assertTrue(writes)
        self.assertLess(min(gates), min(writes), 'Refuse malformed/unapproved controls BEFORE creating intent/acceptance')


if __name__ == '__main__':
    unittest.main()
