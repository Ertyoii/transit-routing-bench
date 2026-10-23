#!/usr/bin/env python3
"""Synthetic-only contract fixtures. Written during timing barrier, not yet run."""
import collections
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r = load('reference_contract_tests', HERE / 'feasible_reference_v1.py')
n = load('reference_evaluator_tests', HERE / 'evaluate_v2_feasible_reference_v3.py')
b = load('frozen_reference_parity_tests', HERE / 'evaluate_v2_certified_delivery_v2.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, sort_keys=True, ensure_ascii=False) + '\n')
    return digest(path)


class Fixture:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.campaign = self.directory / 'native'
        self.run = self.campaign / 'run'
        self.out = self.directory / 'export'
        self.out.mkdir()
        self.source = self.directory / 'source'
        self.source.mkdir()
        self.binary = self.source / 'tadbench'
        self.binary.write_bytes(b'synthetic nonexecuted binary bytes')
        self.model = {'schema_version': '0.2', 'id': 'tiny', 'time_zone': 'UTC', 'service_date': '2026-10-20',
                      'window': {'start': 0, 'end': 1000},
                      'stops': [{'id': name, 'accessible': 'yes'} for name in ('A', 'B')],
                      'footpaths': [{'id': 'walk', 'from': 'A', 'to': 'B', 'duration': 10, 'accessible': 'yes'}]}
        self.query = {'id': 'same-id', 'origin': 'A', 'destination': 'B', 'departure': 0, 'latest_arrival': 100,
                      'transfer_buffer': 0, 'max_walk_seconds': 20, 'max_boardings': 1, 'max_legs': 4,
                      'accessible_only': False, 'walking_limits': {'access_seconds': 20, 'egress_seconds': 20,
                          'transfer_seconds': 20, 'direct_seconds': 20}}
        self.dataset_path = self.directory / 'dataset.json'
        self.workload_path = self.directory / 'workload.json'
        self.dataset_sha = put(self.dataset_path, self.model)
        self.workload = {'dataset_sha256': self.dataset_sha, 'items': [{'query': self.query, 'stratum': 'test'}]}
        self.workload_sha = put(self.workload_path, self.workload)
        self.checker = n.legacy.Checker(self.model)
        self.journey = {'legs': [{'kind': 'walk', 'ref': 'walk', 'departure': 0, 'arrival': 10}]}
        self.checked = self.checker.check(self.query, self.journey)
        self.row = {'query': self.query, 'stratum': 'test', 'complete': False, 'error': 'budget',
                    'raw': [self.journey], 'final': [self.checked]}
        self.pass_path = self.run / 'artifact/pass.json'
        self.pass_payload = {'algorithm': 'tad', 'repetition': 0, 'warmup': False, 'records': [self.row]}
        pass_sha = put(self.pass_path, self.pass_payload)
        binary = {'path': str(self.binary), 'sha256': digest(self.binary)}
        role = {'source_root': str(self.source), 'go_source_hash_sha256': '1'*64, 'git_commit': 'a'*40,
                'routing_file_list_sha256': '2'*64, 'binaries': {'tadbench': binary}}
        recorded = [{'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size}
                    for path in (self.dataset_path, self.workload_path)]
        self.freeze_path = self.directory / 'freeze.json'
        freeze_sha = put(self.freeze_path, {'all_csa_execution_excluded': True, 'source_roles': {'native': role}, 'input_files': recorded})
        freeze_ref = {'path': str(self.freeze_path), 'sha256': freeze_sha}
        argv = [str(self.binary), '-algorithm', 'tad', '-dataset', str(self.dataset_path), '-queries', str(self.workload_path), '-out-dir', '{run_dir}/artifact']
        spec = {'id': 'run', 'cwd': str(self.source), 'argv': argv, 'family': 'tad', 'window': 'weekday-morning-20261020'}
        plan_sha = put(self.campaign / 'plan.json', {'evaluation_mode': 'diagnostic', 'auxiliary_input_source_freeze': freeze_ref, 'runs': [spec]})
        source_state = {'path': str(self.source), 'go_source_hash_sha256': '1'*64, 'commit': 'a'*40, 'status_porcelain': ''}
        command = {'id': 'run', 'cwd': str(self.source), 'requested_cpu_affinity': '0-3',
                   'argv': ['/usr/bin/taskset', '-c', '0-3', *[x.replace('{run_dir}', str(self.run)) for x in argv]],
                   'binary': binary, 'sources_before': [source_state], 'inputs': recorded}
        command_sha = put(self.run / 'command.json', command)
        result = {'id': 'run', 'ok': False, 'returncode': 1, 'termination': 'budget', 'timed_out': False,
                  'source_contents_unchanged': True, 'sources_after': [source_state]}
        result_sha = put(self.run / 'result.json', result)
        manifest = {'dataset_sha256': self.dataset_sha, 'queries_sha256': self.workload_sha,
                    'provenance': {'build_source_sha256': '1'*64, 'runtime_tree_sha256': '1'*64,
                        'routing_source_sha256': '2'*64, 'executable_sha256': binary['sha256'],
                        'source_binding': 'embedded_build_source', 'runtime_matches_build': True},
                    'passes': [{'file': 'pass.json', 'sha256': pass_sha, 'repetition': 0, 'warmup': False, 'algorithm': 'tad'}]}
        manifest_sha = put(self.run / 'artifact/manifest.json', manifest)
        self.context = {'campaign': str(self.campaign), 'run_id': 'run', 'family': 'tad', 'donor_family': 'TAD', 'window': 'morning',
            'native_algorithm': 'tad', 'native_driver': 'tadbench',
            'dataset_path': str(self.dataset_path), 'dataset_sha256': self.dataset_sha, 'dataset_schema_version': '0.2', 'dataset_id': 'tiny',
            'workload_path': str(self.workload_path), 'workload_sha256': self.workload_sha,
            'frozen_plan_path': str(self.campaign / 'plan.json'), 'frozen_plan_sha256': plan_sha,
            'native_source_sha256': '1'*64, 'native_routing_sha256': '2'*64, 'native_binary_sha256': binary['sha256'],
            'command_path': str(self.run / 'command.json'), 'command_sha256': command_sha,
            'result_path': str(self.run / 'result.json'), 'result_sha256': result_sha,
            'source_process_status': {key: result.get(key) for key in ('ok', 'returncode', 'termination', 'timed_out', 'source_contents_unchanged')},
            'source_input_freeze': freeze_ref, 'native_pass_file': 'pass.json', 'native_pass_path': str(self.pass_path),
            'native_pass_sha256': pass_sha, 'native_manifest_path': str(self.run / 'artifact/manifest.json'), 'native_manifest_sha256': manifest_sha,
            'native_repetition': 0, 'native_warmup': False}
        self.offer = {**self.context, 'query': self.query, 'stratum': 'test', 'offered_native_query': self.query,
            'native_row_present': True, 'native_complete': False, 'status': 'feasible_saved_witnesses_native_incomplete',
            'original_native_status': 'incomplete_or_error'}
        self.records = [self.record(stage) for stage in ('raw', 'final')]
        self.schema_bytes = (HERE / 'feasible_reference_schema_v1.json').read_bytes()
        self.report = {'schema': 'sg-native-transit-independent-audit-v1', 'offered_native_rows': 1,
            'feasible_reference_witness_occurrences': 2, 'runs': [{**self.context, 'driver': 'tadbench', 'offered': 1, 'native_complete_rows': 0,
                'binding_status': 'freeze_command_runtime_manifest_pass_bound'}],
            'helper_files': {str(HERE / 'summarize_native_auxiliary_v1.py'): digest(HERE / 'summarize_native_auxiliary_v1.py')}}
        self.write_export()

    def record(self, stage):
        q = self.query
        fragment = r.workload_fragments(self.workload_path.read_text(), self.workload)[q['id']]
        return {'schema': r.SCHEMA, 'kind': 'independently_feasible_saved_native_witness', 'reference_only': True,
            'scalar_optimality_claim': False, 'search_completeness_claim': False, 'dataset_sha256': self.dataset_sha,
            'query': q, 'query_canonical_json_utf8': r.canonical(q), 'query_canonical_sha256': r.canonical_sha(q),
            'query_exact_workload_json_utf8': fragment, 'query_exact_workload_bytes_sha256': hashlib.sha256(fragment.encode()).hexdigest(),
            'native_family': 'tad', 'donor_family': 'TAD', 'validated': self.checked,
            'provenance': {**self.context, 'native_record_index': 0, 'native_stage': stage, 'saved_witness_occurrence_index': 0,
                'source_point_index': 0, 'source_native_query': q, 'source_ready': 0, 'source_ready_query': q,
                'source_branch': 'point_journey', 'source_saved_journey_canonical_sha256': r.canonical_sha(self.journey),
                'source_feasible_at_emitted_ready': True, 'source_ready_validation_error': None,
                'transformation': r.IDENTITY_TRANSFORM, 'transform_kind': 'identity', 'transformed_initial_leg_count': 0,
                'transformed_journey_canonical_sha256': r.canonical_sha(self.journey), 'source_initial_walking_seconds': 10,
                'materialized_ready': 0, 'readiness_contract': 'original base query readiness; fixed latest arrival',
                'source_native_complete': False, 'source_independent_row_status': 'feasible_saved_witnesses_native_incomplete'}}

    def write_export(self):
        schema_path = self.out / 'FEASIBLE_REFERENCE_SCHEMA.json'
        schema_path.write_bytes(self.schema_bytes)
        self.report['feasible_reference_schema_sha256'] = digest(schema_path)
        put(self.out / 'REPORT.json', self.report)
        (self.out / 'OFFERED_NATIVE_ROWS.jsonl').write_text(r.canonical(self.offer) + '\n')
        self.export = self.out / 'FEASIBLE_REFERENCE_WITNESSES.jsonl'
        self.export.write_text(''.join(r.canonical(z) + '\n' for z in self.records))
        put(self.out / 'ARTIFACT_SHA256.json', {path.name: digest(path) for path in self.out.iterdir() if path.name != 'ARTIFACT_SHA256.json'})

    def importer(self):
        return r.ReferenceImporter([str(self.export)], ROOT, {}, n.sha, n.legacy, r.DonorLineage(None, None))

    def remove_selected_source_pass(self):
        path = self.run / 'artifact/manifest.json'
        manifest = json.loads(path.read_text()); manifest['passes'] = []
        new_sha = put(path, manifest)
        self.offer['native_manifest_sha256'] = new_sha
        self.report['runs'][0]['native_manifest_sha256'] = new_sha
        for field in ('native_pass_file', 'native_pass_path', 'native_pass_sha256', 'native_repetition', 'native_warmup'):
            self.offer.pop(field, None)
            self.report['runs'][0].pop(field, None)
        self.offer['native_row_present'] = False
        self.offer['native_complete'] = False
        self.offer['original_native_status'] = None
        self.offer['status'] = 'unavailable_native_row_or_binding'

    def import_pool(self):
        importer = self.importer()
        pool = collections.defaultdict(dict)
        importer.import_dataset(self.dataset_sha, self.checker, {(self.dataset_sha, self.query['id']): self.query}, pool, n.identity)
        return importer, pool


class FeasibleReferenceTests(unittest.TestCase):
    def test_exact_query_binding_rejects_sameqid_wrong_caps_or_horizon(self):
        q = {'id': 'q', 'max_walk_seconds': 3, 'latest_arrival': 9}
        bound = {}
        r.bind_recipient(bound, 'model', q)
        for field in ('max_walk_seconds', 'latest_arrival'):
            other = dict(q); other[field] += 1
            with self.assertRaises(ValueError): r.bind_recipient(bound, 'model', other)
        with self.assertRaises(ValueError): r.offered_queries({'items': [{'query': q}, {'query': q}]})

    def test_partial_native_donates_without_serving_or_oracle_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Fixture(temp); importer, pool = f.import_pool()
            self.assertEqual(len(pool[(f.dataset_sha, f.query['id'])]), 1)
            entry = next(iter(pool[(f.dataset_sha, f.query['id'])].values()))
            self.assertEqual(len(entry['reference_provenance']), 2)
            output = f.directory / 'results'; output.mkdir()
            report = importer.finalize(output)
            self.assertEqual(report['completed_serving_rows_added'], 0)
            self.assertEqual(report['scalar_slots_added'], 0)
            self.assertFalse(f.offer['native_complete'])
            self.assertFalse(f.context['source_process_status']['ok'])
            self.assertEqual(len(importer.inventory), 2)

    def test_fake_complete_oracle_and_duplicate_occurrences_fail_closed(self):
        for mutate in ('oracle', 'duplicate', 'transform', 'source_sha', 'original_sha', 'process', 'metrics', 'wrongquery'):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                f = Fixture(temp)
                if mutate == 'oracle': f.records[0]['result'] = {'complete': True, 'found': True}
                if mutate == 'duplicate': f.records[1] = copy.deepcopy(f.records[0])
                if mutate == 'transform': f.records[0]['provenance']['transformed_journey_canonical_sha256'] = '0'*64
                if mutate == 'source_sha': f.records[0]['provenance']['native_source_sha256'] = '0'*64
                if mutate == 'original_sha': f.records[0]['provenance']['source_saved_journey_canonical_sha256'] = '0'*64
                if mutate == 'process':
                    f.records[0]['provenance']['source_process_status'] = dict(f.context['source_process_status'], ok=True)
                if mutate == 'metrics': f.records[0]['validated'] = copy.deepcopy(f.checked); f.records[0]['validated']['metrics']['arrival'] += 1
                if mutate == 'wrongquery':
                    z = f.records[0]; z['query'] = dict(f.query, latest_arrival=99)
                    z['query_canonical_json_utf8'] = r.canonical(z['query']); z['query_canonical_sha256'] = r.canonical_sha(z['query'])
                f.write_export()
                with self.assertRaises((ValueError, KeyError)): f.import_pool()

    def test_no_witness_same_count_query_or_stratum_ledger_swap_fails(self):
        for mutate in ('query', 'stratum', 'run_missing', 'duplicate_run'):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                f = Fixture(temp); f.records = []; f.report['feasible_reference_witness_occurrences'] = 0
                f.offer['native_row_present'] = False
                if mutate == 'query': f.offer['query'] = dict(f.query, max_walk_seconds=19)
                if mutate == 'stratum': f.offer['stratum'] = 'changed'
                if mutate == 'run_missing': f.report['runs'] = []
                if mutate == 'duplicate_run': f.report['runs'] *= 2
                f.write_export()
                with self.assertRaises(ValueError): f.importer()

    def test_offered_missing_unknown_retained_with_zero_enrichment(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Fixture(temp); f.records = []; f.report['feasible_reference_witness_occurrences'] = 0
            f.remove_selected_source_pass(); f.write_export()
            importer, pool = f.import_pool()
            out = f.directory / 'result'; out.mkdir()
            result = importer.finalize(out)
            self.assertFalse(pool)
            self.assertEqual(result['offered_native_reference_rows'], 1)
            self.assertEqual(result['source_denominators'][0]['source_missing_rows'], 1)
            self.assertEqual(result['completed_serving_rows_added'], 0)
            self.assertEqual(result['scalar_slots_added'], 0)

    def test_no_witness_presence_and_completion_laundering_rejected(self):
        for mutation in ('missing', 'complete'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                f = Fixture(temp); f.records = []; f.report['feasible_reference_witness_occurrences'] = 0
                if mutation == 'missing': f.offer['native_row_present'] = False
                else:
                    f.offer['native_complete'] = True
                    f.report['runs'][0]['native_complete_rows'] = 1
                f.write_export()
                with self.assertRaises(ValueError): f.import_pool()

    def test_prefix_only_transform_keeps_rides_middle_and_egress_fixed(self):
        class Checker:
            walks = {'a': {'duration': 5}, 'middle': {'duration': 7}, 'egress': {'duration': 8}}
        legs = [{'kind': 'walk', 'ref': 'a', 'departure': 20, 'arrival': 25},
                {'kind': 'ride', 'ref': 'r', 'departure': 30, 'arrival': 40},
                {'kind': 'walk', 'ref': 'middle', 'departure': 40, 'arrival': 47},
                {'kind': 'ride', 'ref': 's', 'departure': 50, 'arrival': 60},
                {'kind': 'walk', 'ref': 'egress', 'departure': 60, 'arrival': 68}]
        journey = {'legs': legs}
        r.validate_source_walk_anchor(Checker(), journey, 20)
        transformed, seconds, count = r.reanchor_prefix(Checker(), journey, 0)
        self.assertEqual((seconds, count), (5, 1))
        self.assertEqual(transformed['legs'][1:], legs[1:])
        self.assertEqual((transformed['legs'][0]['departure'], transformed['legs'][0]['arrival']), (0, 5))
        bad = copy.deepcopy(journey); bad['legs'][0]['departure'] = 21
        with self.assertRaises(ValueError): r.validate_source_walk_anchor(Checker(), bad, 20)

    def test_hash_bound_cache_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Fixture(temp); importer = f.importer()
            importer.read_bound(f.workload_path, f.workload_sha)
            f.workload_path.write_text('{}\n')
            with self.assertRaises(ValueError): importer.read_bound(f.workload_path, f.workload_sha)

    def test_empty_reference_is_not_success_or_eligible(self):
        result = n.score_stage([{'duration_seconds': 1, 'metrics': {'transfers': 0, 'walking_seconds': 0}}], [], [{'transfer_seconds': 0, 'extra_walk_weight': 0}], True)
        self.assertTrue(result['reference_empty_or_unavailable'])
        self.assertEqual(result['eligible'], 0)
        self.assertNotIn('covered', result)

    def test_new_import_hook_precedes_counterexamples_and_latency(self):
        text = (HERE / 'evaluate_v2_feasible_reference_v3.py').read_text()
        self.assertLess(text.index('reference_importer.import_dataset('), text.index('native_counterexamples=[]'))
        self.assertLess(text.index("x['status']='native_contract_counterexample'"), text.index('accepted_first_answer=first_answer_acceptance('))
        self.assertLess(text.index("x['status']='native_contract_counterexample'"), text.index("'complete_response_ns':dist("))

    def test_native_false_empty_certificate_invalidates_before_first_answer_and_latency(self):
        with tempfile.TemporaryDirectory() as temp:
            f = Fixture(temp)
            config = {'lean_delivery': True, 'delivery_policy': 'finite_preferences_v2', 'delivery_limits': [3],
                'groups': [{'name': 'tiny', 'description': 'synthetic', 'preferences': [
                    {'id': 'p', 'transfer_seconds': 0, 'extra_walk_weight': 0}]}]}
            config_path = f.directory / 'finite.json'; config_sha = put(config_path, config)
            campaign = f.directory / 'serving'; run = campaign / 'serve'
            argv = [str(f.binary), '-algorithm', 'mc_raptor', '-dataset', str(f.dataset_path), '-queries', str(f.workload_path),
                '-quality', '-display-k', '-1', '-preference-scenarios', str(config_path), '-out-dir', '{run_dir}/artifact']
            put(campaign / 'plan.json', {'runs': [{'id': 'serve', 'variant_id': 'synthetic', 'window': 'morning', 'argv': argv}]})
            row = {'query': f.query, 'stratum': 'test', 'batch': 0, 'attempted': True, 'completed': True, 'status': 'complete',
                'valid_empty': True, 'transit': False, 'raw': [], 'final': [], 'certificates': {'arrival_boardings': True},
                'response_ns': 100, 'quality_ns': 50, 'validation_rank_ns': 70, 'core_ns': 20,
                'published_response_ns': 110, 'serialization_ns': 10,
                'recommendation_quality': {'choices': {'complete': True, 'groups': [{'group': config['groups'][0],
                    'selections': [{'limit': 3, 'complete': True, 'selected': [], 'method': 'preference_minimax'}]}]}}}
            pass_sha = put(run / 'artifact/pass.json', {'algorithm': 'mc_raptor', 'repetition': 0, 'warmup': False, 'records': [row]})
            put(run / 'artifact/summary.json', {'algorithm': 'mc_raptor', 'dataset_sha256': f.dataset_sha,
                'queries_sha256': f.workload_sha, 'quality_enabled': True, 'preference_config': config,
                'preference_config_sha256': config_sha, 'display_k': [], 'batch_deadline_ns': 1000,
                'provenance': {'build_source_sha256': '1'*64, 'runtime_tree_sha256': '1'*64,
                    'routing_source_sha256': '2'*64, 'executable_sha256': digest(f.binary),
                    'source_binding': 'embedded_build_source', 'runtime_matches_build': True},
                'passes': [{'file': 'pass.json', 'sha256': pass_sha, 'repetition': 0, 'warmup': False}]})
            put(run / 'command.json', {'argv': ['/usr/bin/taskset', '-c', '0-3', *[x.replace('{run_dir}', str(run)) for x in argv]],
                'binary': {'sha256': digest(f.binary)}, 'inputs': [{'path': str(config_path), 'sha256': config_sha, 'bytes': config_path.stat().st_size}]})
            put(run / 'result.json', {'ok': True, 'launch_to_first_available_answer_ns': 150, 'publication_receipt': {'valid': True},
                'first_available_answer_events': [{'supervisor_received_since_spawn_ns': 150, 'payload': {'query_id': f.query['id'],
                    'process_elapsed_ns': 120, 'published_response_ns': 110, 'serialization_ns': 10}}]})
            out = f.directory / 'evaluated'
            old_out = f.directory / 'frozen-baseline'
            no_ref_out = f.directory / 'new-no-reference'
            b.evaluate([str(campaign)], [], old_out, 3)
            n.evaluate([str(campaign)], [], no_ref_out, 3)
            for name in ('QUALITY_ROWS.jsonl', 'QUALITY_AGGREGATE.json', 'METRICS_BY_RUN.json', 'ORACLE_COMPARISONS.json',
                         'INDEPENDENT_ORACLE_SLOTS.json', 'NATIVE_COUNTEREXAMPLES.json', 'VALIDATION_ERRORS.json'):
                self.assertEqual((old_out / name).read_bytes(), (no_ref_out / name).read_bytes(), name)
            original_metrics = json.loads((old_out / 'METRICS_BY_RUN.json').read_text())[0]
            self.assertTrue(original_metrics['first_published_native_row_accepted'])
            n.evaluate([str(campaign)], [], out, 3, [str(f.export)])
            report = json.loads((out / 'REPORT.json').read_text())
            metrics = json.loads((out / 'METRICS_BY_RUN.json').read_text())[0]
            self.assertGreater(report['native_contract_counterexamples'], 0)
            self.assertEqual(report['offered_run_rows'], 1)
            self.assertEqual(metrics['completed'], 0)
            self.assertEqual(metrics['complete_response_ns']['count'], 0)
            self.assertFalse(metrics['first_published_native_row_accepted'])
            self.assertIsNone(metrics['accepted_native_launch_to_first_available_answer_ns'])

    def test_explicit_lineage_aliases_hybrids_and_oracle_independence(self):
        evidence = [{'path': 'synthetic', 'sha256': '1'*64}]
        payload = {'schema': 'sg-donor-ancestry-algorithms-v1', 'version': 1,
            'contract': {'path': 'synthetic-contract', 'sha256': '2'*64}, 'algorithms': {}}
        for name, family, groups in [('raptor', 'RAPTOR', ['round']), ('mc_raptor', 'McRAPTOR', ['round']),
                ('ultra_subset', 'ULTRA_capped', ['round']), ('hybrid', 'Hybrid', ['round', 'tb']),
                ('trip_based', 'TripBased', ['tb']), ('independent_scalar_oracle', 'independent_scalar_oracle', ['oracle'])]:
            payload['algorithms'][name] = {'adapter_family': family, 'ancestry_groups': groups, 'source_evidence': evidence}
        def read(path, expected=None, as_text=False): return '' if as_text else (payload if str(path) == 'synthetic-config' else {})
        lineage = r.DonorLineage('synthetic-config', read)
        self.assertEqual(lineage.group('raptor', 'RAPTOR'), lineage.group('mc_raptor', 'McRAPTOR'))
        target = set(lineage.group('raptor'))
        self.assertTrue(target.intersection(lineage.group('hybrid')))
        self.assertFalse(target.intersection(lineage.group('trip_based')))
        self.assertFalse(target.intersection(lineage.group('independent_scalar_oracle')))
        with self.assertRaises(ValueError): lineage.group('unknown_adapter')


if __name__ == '__main__':
    unittest.main(verbosity=2)
