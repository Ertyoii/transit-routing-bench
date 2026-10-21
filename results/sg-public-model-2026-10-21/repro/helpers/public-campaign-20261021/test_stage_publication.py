"""Tiny synthetic projection checks. No routers, source datasets or campaign mutation."""
import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('stage_publication', Path(__file__).with_name('stage_publication.py'))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='projection-unit-')
        self.root = Path(self.tmp.name)
        self.old_root = mod.ROOT
        mod.ROOT = self.root
        self.campaign = self.root / 'synthetic-campaign'
        self.campaign.mkdir()
        self.runs = []
        self.write(self.campaign / 'status.json', {'state': 'completed'})

    def tearDown(self):
        mod.ROOT = self.old_root
        self.tmp.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def run_spec(self, algorithm, items=1, warmups=0, repetitions=1):
        run_id = 'run-' + str(len(self.runs))
        query = self.write(self.root / (run_id + '-queries.json'), {'items': [
            {'stratum': 'synthetic', 'query': {'id': str(i), 'origin': 'A', 'destination': 'B', 'departure': 0}}
            for i in range(items)]})
        spec = {'id': run_id, 'argv': [str(self.root / algorithm), '-queries', str(query),
                                     '-warmups', str(warmups), '-repetitions', str(repetitions)]}
        self.runs.append(spec)
        self.write(self.campaign / 'plan.json', {'runs': self.runs})
        base = self.campaign / run_id / 'artifact'
        base.mkdir(parents=True)
        return base

    def pass_file(self, base, name, algorithm, records, repetition=0, warmup=False, **extra):
        path = self.write(base / name, {'algorithm': algorithm, 'repetition': repetition, 'warmup': warmup, 'records': records})
        return dict(file=name, algorithm=algorithm, repetition=repetition, warmup=warmup, sha256=mod.sha(path), **extra)

    def project(self):
        out = self.root / 'projection'
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            result = mod.main(['--campaign', str(self.campaign), '--out', str(out)])
        with gzip.open(out / 'outcome-records.jsonl.gz', 'rt') as stream:
            rows = [json.loads(line) for line in stream]
        manifest = json.loads((out / 'PUBLICATION_MANIFEST.json').read_text())
        for entry in manifest['files']:
            path = out / entry['path']
            self.assertEqual(entry['bytes'], path.stat().st_size)
            self.assertEqual(entry['sha256'], mod.sha(path))
        self.assertEqual(result['manifest']['sha256'], mod.sha(out / 'PUBLICATION_MANIFEST.json'))
        self.assertNotIn(str(self.root), '\n'.join(path.read_text() for path in out.rglob('*.json')))
        self.assertNotIn('"legs"', json.dumps(rows))
        self.assertNotIn('"core_arcs"', json.dumps(rows))
        return rows, out, json.loads(stdout.getvalue())

    def test_tad_manifest_and_native_complete(self):
        base = self.run_spec('tadbench')
        record = {'query': {'id': 'q'}, 'complete': True, 'timed_out': False,
                  'raw': [{'legs': [{'ref': 'private-witness'}]}],
                  'final': [{'journey': {'legs': [{'ref': 'private-witness'}]}, 'metrics': {'arrival': 3}}]}
        summaries = [self.pass_file(base, '00-' + name + '.json', name, [record], queries=1)
                     for name in ('ea_csa', 'raptor', 'tad')]
        self.write(base / 'manifest.json', {'summaries': summaries, 'success': True})
        rows, _, _ = self.project()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['complete'] is True and r['completed'] is True for r in rows))
        self.assertEqual(rows[0]['validated_objectives'][0]['metrics'], {'arrival': 3})

    def test_profile_grid_and_compact_objectives(self):
        base = self.run_spec('profilebench')
        record = {'query': {'base': {'id': 'q'}, 'ready_window_end_inclusive': 1}, 'complete': True,
                  'raw': {'direct_walking': {'duration': 4, 'journey_at_window_start': {'legs': []}}, 'complete': True, 'transit_points': [{'latest_ready': 1, 'arrival': 3, 'boardings': 1, 'journey': {'legs': []}}]},
                  'final_points': [{'latest_ready': 1, 'validated': {'journey': {'legs': []}, 'metrics': {'arrival': 3}}}],
                  'final_direct': {'journey': {'legs': []}, 'metrics': {'arrival': 4}},
                  'every_integer_ready_time': [{'ready': 0, 'arrival_under_boarding_caps': [99, 3]}, {'ready': 1, 'arrival_under_boarding_caps': [99, 3]}]}
        summaries = [self.pass_file(base, '00-' + name + '.json', name, [record], profile_queries=1)
                     for name in ('profile_csa', 'range_raptor')]
        self.write(base / 'manifest.json', {'summaries': summaries})
        rows, _, _ = self.project()
        self.assertEqual(rows[0]['raw_candidate_count'], 2)
        self.assertEqual(rows[0]['validated_candidate_count'], 2)
        self.assertEqual(rows[0]['ready_time_observation_count'], 2)
        self.assertEqual(rows[0]['validated_profile_points'][0]['latest_ready'], 1)
        self.assertEqual(rows[0]['validated_profile_direct']['metrics'], {'arrival': 4})
        self.assertEqual(rows[0]['raw_profile_direct']['duration'], 4)

    def test_ultra_all_twelve_ordinary_preparation_failures(self):
        base = self.run_spec('ultrabench', 12, warmups=1, repetitions=3)
        failures = [{'query': {'id': str(i)}, 'raw': [], 'final': [], 'complete': False,
                     'unsupported': True, 'error': 'preparation unavailable', 'core_ns': 0, 'response_ns': 0}
                    for i in range(12)]
        self.write(base / 'preparation-failures.json', failures)
        self.write(base / 'summary.json', {'success': False, 'requested': 12, 'unavailable': 12, 'assessed': 0})
        rows, _, _ = self.project()
        self.assertEqual(len(rows), 12)
        self.assertEqual({r['measurement_role'] for r in rows}, {'preparation-unavailable'})
        self.assertTrue(all(not r['forced'] and not r['warmup'] and not r['complete'] for r in rows))
        self.assertEqual({r['query']['id'] for r in rows}, {str(i) for i in range(12)})

    def test_corech_cells_and_separate_diagnostics(self):
        base = self.run_spec('corechgraphbench')
        cells = [{'target': 'B', 'found': False, 'duration': 0, 'core_arcs': [], 'raw_edges': []},
                 {'target': 'A', 'found': True, 'duration': 0, 'core_arcs': [], 'raw_edges': []}]
        record = {'requested_source': 'A', 'requested_targets': ['B', 'A'], 'requested_maximum_duration': 600,
                  'request_shape_valid': True, 'core_error_kind': 'none', 'complete': True,
                  'raw': {'source': 'A', 'maximum_duration': 600, 'paths': cells, 'complete': True}, 'final': cells}
        passes = [self.pass_file(base, name + '-pass-00.json', name, [record], rows=1, cells=2)
                  for name in ('identity', 'core_ch')]
        self.write(base / 'summary.json', {'passes': passes})
        self.write(base / 'forced-deadlines.json', [{'algorithm': 'core_ch', 'record': dict(record, complete=False, core_error_kind='context_deadline_exceeded'), 'expected_context_failure_observed': True}])
        self.write(base / 'target-partitions.json', [{'algorithm': 'core_ch', 'record': record}])
        self.write(base / 'forced-preparation.json', {'attempted_query': record['raw'], 'snapshot': {'raw_edges': ['must-not-copy']}, 'expected_failure_observed': True, 'preparation_error_kind': 'context_canceled', 'query_request_shape_valid': True})
        rows, _, _ = self.project()
        self.assertEqual(len(rows), 5)
        row = rows[0]
        self.assertEqual(row['requested_targets'], ['B', 'A'])
        self.assertEqual([x['target'] for x in row['raw']['paths']], ['B', 'A'])
        self.assertEqual(row['raw']['source'], 'A')
        self.assertEqual(row['raw']['maximum_duration'], 600)
        self.assertEqual(row['requested_target_count'], 2)
        self.assertFalse(row['raw']['paths'][0]['found'])
        self.assertEqual({r['measurement_role'] for r in rows}, {'measured', 'forced-deadline', 'forced-preparation', 'diagnostic-target-partition'})
        self.assertTrue(next(r for r in rows if r['measurement_role'] == 'forced-preparation')['forced'])

    def test_family_warmup_and_forced_not_dropped(self):
        base = self.run_spec('familybench', warmups=1, repetitions=1)
        self.runs[-1]['argv'] += ['-algorithm', 'raptor']
        self.write(self.campaign / 'plan.json', {'runs': self.runs})
        record = {'query': {'id': 'q'}, 'completed': False, 'attempted': False, 'status': 'not_run', 'raw': [], 'final': []}
        passes = [self.pass_file(base, 'pass-00.json', 'raptor', [record], repetition=0, warmup=True, requested=1),
                  self.pass_file(base, 'pass-01.json', 'raptor', [record], repetition=1, requested=1),
                  self.pass_file(base, 'forced-deadline.json', 'raptor', [record], repetition=2, forced=True, requested=1)]
        self.write(base / 'summary.json', {'algorithm': 'raptor', 'passes': passes})
        rows, _, _ = self.project()
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['measurement_role'] for r in rows], ['warmup', 'measured', 'forced-deadline'])
        self.assertTrue(all(r['attempted'] is False for r in rows))

    def test_killed_before_manifest_recovers_pass_and_missing_slots(self):
        base = self.run_spec('tadbench', items=2, warmups=1, repetitions=1)
        self.pass_file(base, '00-tad.json', 'tad', [{'complete': True, 'raw': [], 'final': []}] * 2, warmup=True)
        rows, out, _ = self.project()
        self.assertEqual(len(rows), 12)
        self.assertEqual(sum(r['measurement_role'] == 'warmup' for r in rows), 2)
        unresolved = [r for r in rows if r['measurement_role'] == 'offered-unresolved']
        self.assertEqual(len(unresolved), 10)
        self.assertTrue(all(r['attempted'] is None and r['raw_candidate_count'] is None for r in unresolved))
        index = json.loads((out / 'ARTIFACT_INDEX.json').read_text())
        self.assertFalse(index['original_artifact_sha256'][0]['runs'][0]['pass_bindings'][0]['native_summary_bound'])

    def test_corech_preparation_failure_has_native_row_denominators(self):
        base = self.run_spec('corechgraphbench')
        self.write(base / 'summary.json', {'success': False, 'phase': 'independent_audit', 'requested_rows_per_pass': 2, 'requested_cells_per_pass': 4, 'assessed_rows_per_pass': 0})
        rows, _, _ = self.project()
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r['requested_targets'] == ['A', 'B'] and r['denominator_unit'] == 'one-source-many-target-row-and-ordered-cells' for r in rows))

    def test_private_paths_fail_closed_and_root_is_portable(self):
        self.assertEqual(mod.portable(str(self.root / 'artifact.json')), '${SG_ROOT}/artifact.json')
        for value in ['/' + 'home/alice/private', '/' + 'workspace/shared/elsewhere', str(self.root) + '-lookalike/file', 'C:' + chr(92) + 'Users' + chr(92) + 'Alice', '/etc/passwd']:
            with self.assertRaises(ValueError):
                mod.portable(value)
        with self.assertRaises(ValueError):
            mod.portable({'/' + 'home/alice/file': 1})

    def test_traversal_and_symlink_escape_fail_closed(self):
        base = self.root / 'base'
        base.mkdir()
        for name in ('../outside.json', '/outside.json'):
            with self.assertRaises(ValueError):
                mod.artifact_path(base, name)
        (base / 'escape.json').symlink_to(self.root / 'outside.json')
        with self.assertRaises(ValueError):
            mod.artifact_path(base, 'escape.json')

    def test_secret_raw_source_or_witness_payload_refused(self):
        for key in ('journey', 'legs', 'raw_edges', 'connections', 'footpaths', 'api_key'):
            with self.assertRaises(ValueError):
                mod.public_value({key: []})

    def test_active_campaign_refused_before_output_creation(self):
        self.run_spec('tadbench')
        self.write(self.campaign / 'status.json', {'state': 'running'})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mod.main(['--campaign', str(self.campaign), '--out', str(self.root / 'projection')])
        self.assertFalse((self.root / 'projection').exists())

    def test_original_hash_and_declared_denominator_mismatch_refused(self):
        base = self.run_spec('tadbench')
        ps = self.pass_file(base, '00-tad.json', 'tad', [{'complete': True, 'raw': [], 'final': []}], queries=2)
        self.write(base / 'manifest.json', {'summaries': [ps]})
        with self.assertRaisesRegex(ValueError, 'denominator'):
            self.project()
        ps['queries'] = 1
        ps['sha256'] = '0' * 64
        self.write(base / 'manifest.json', {'summaries': [ps]})
        dest = self.root / 'other-projection'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            mod.main(['--campaign', str(self.campaign), '--out', str(dest)])

    def test_exact_semantic_hash_container_renames_only_known_hashes(self):
        raw = {'checked_field_semantic_sha256': {'connections': 'a' * 64, 'stops': 'b' * 64, 'transfers': 'c' * 64, 'trips': 'd' * 64}}
        projected = mod.public_value(raw)
        self.assertEqual(set(projected['checked_field_semantic_sha256']), {'connections_sha256', 'stops_sha256', 'transfers_sha256', 'trips_sha256'})
        self.assertEqual(raw['checked_field_semantic_sha256']['connections'], 'a' * 64)
        for bad in ({'connections': 'a' * 64}, {'checked_field_semantic_sha256': {'connections': 'not-a-hash'}},
                    {'checked_field_semantic_sha256': {'password': 'a' * 64}},
                    {'checked_field_semantic_sha256': {'connections': [{'from': 'A'}]}}):
            with self.assertRaises(ValueError):
                mod.public_value(bad)

    def test_exact_sealed_run_virtual_prefix_normalized(self):
        self.assertEqual(mod.portable('/__SEALED_RUN_DIR__/test-foo/artifact'), '${SEALED_RUN_DIR}/test-foo/artifact')
        for value in ('/__SEALED_RUN_DIR__-private/test/artifact', '/private/__SEALED_RUN_DIR__/test/artifact'):
            with self.assertRaises(ValueError):
                mod.portable(value)

    def test_compact_quality_omits_only_verbose_quality_payload(self):
        quality = {'policy': 'pattern_anchors_v1', 'features': [{'identity': 'DO_NOT_PUBLISH', 'metrics': {'arrival': 4}}],
                   'selections': [{'limit': 3, 'score_envelope_seconds': 120, 'selected': ['DO_NOT_PUBLISH'],
                                   'decisions': {'DO_NOT_PUBLISH': 'selected_score_anchor'}, 'global_optimality_claim': False}]}
        raw = {'query': {'id': 'q'}, 'complete': False, 'error': 'synthetic failure', 'core_ns': 4,
               'core_allocated_bytes': 9, 'certificates': {'budget_exhausted': True}, 'raw': [],
               'final': [{'journey': {'legs': []}, 'metrics': {'arrival': 4}}], 'recommendation_quality': quality}
        full = mod.project_record(raw, {})
        compact = mod.project_record(raw, {}, compact=True)
        self.assertEqual({k:v for k,v in full.items() if k not in ('projection', 'recommendation_quality')},
                         {k:v for k,v in compact.items() if k not in ('projection', 'recommendation_quality')})
        self.assertEqual(compact['recommendation_quality']['original_payload_sha256'], mod.digest(quality))
        self.assertEqual(compact['recommendation_quality']['feature_count'], 1)
        self.assertEqual(compact['recommendation_quality']['selection_configurations'][0]['selected_count'], 1)
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(compact))
        self.assertIn('DO_NOT_PUBLISH', json.dumps(full))

    def test_compact_preparation_hashes_proofs_and_source_tables(self):
        certificates = [{'reason': 'stay_on_trip', 'proofs': [{'witness_connection': 'DO_NOT_PUBLISH', 'legs': []}]}]
        summary = {'passes': [], 'preparation': {'elapsed_ns': 12, 'complete': True, 'error': '',
                    'stats': {'proof_checks': 2}, 'certificates': certificates,
                    'footpaths': [{'from': 'DO_NOT_PUBLISH', 'to': 'B'}]},
                   'index_cost_final': {'complete': True, 'certificates': certificates}}
        compact = mod.compact_summary(summary)
        mod.public_value(compact)
        self.assertEqual(compact['preparation']['elapsed_ns'], 12)
        self.assertEqual(compact['preparation']['certificates']['original_payload_sha256'], mod.digest(certificates))
        self.assertEqual(compact['preparation']['certificates']['item_count'], 1)
        self.assertEqual(compact['preparation']['certificates']['reason_summary']['counts'], {'stay_on_trip': 1})
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(compact))
        self.assertIn('footpaths_projection', compact['preparation'])
        self.assertEqual(summary['preparation']['certificates'], certificates)

    def test_compact_layout_is_deterministic_and_keeps_all_rows(self):
        base = self.run_spec('tadbench')
        record = {'query': {'id': 'q'}, 'complete': False, 'error': 'failure', 'raw': [], 'final': []}
        summaries = [self.pass_file(base, '00-' + name + '.json', name, [record], queries=1)
                     for name in ('ea_csa', 'raptor', 'tad')]
        self.write(base / 'manifest.json', {'summaries': summaries, 'preparation': {'elapsed_ns': 9, 'proofs': [{'ref': 'DO_NOT_PUBLISH'}]}})
        outputs = []
        for name in ('compact-a', 'compact-b'):
            out = self.root / name
            with contextlib.redirect_stdout(io.StringIO()):
                mod.main(['--campaign', str(self.campaign), '--out', str(out), '--compact'])
            outputs.append(out)
        a, b = outputs
        for name in ('outcome-records.jsonl.gz', 'provenance-records.jsonl.gz'):
            self.assertEqual(mod.sha(a / name), mod.sha(b / name))
            self.assertEqual((a / name).read_bytes()[4:8], b'\x00' * 4)
        self.assertFalse((a / 'campaigns').exists())
        with gzip.open(a / 'outcome-records.jsonl.gz', 'rt') as stream:
            rows = [json.loads(line) for line in stream]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['error'] == 'failure' and not r['complete'] for r in rows))
        with gzip.open(a / 'provenance-records.jsonl.gz', 'rt') as stream:
            members = [json.loads(line) for line in stream]
        self.assertEqual(len(members), 3)
        for member in members:
            data = (json.dumps(member['content'], sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
            import hashlib
            self.assertEqual(member['bytes'], len(data))
            self.assertEqual(member['sha256'], hashlib.sha256(data).hexdigest())
        self.assertNotIn('DO_NOT_PUBLISH', json.dumps(members))
        index = json.loads((a / 'ARTIFACT_INDEX.json').read_text())
        self.assertTrue(index['compact_mode'])
        self.assertEqual(index['provenance_member_count'], 3)
        self.assertTrue(index['compact_omissions'])

    def test_duplicate_witnesses_nested_in_native_detail_projected(self):
        journey = {'legs': [{'kind': 'walk', 'ref': 'synthetic', 'departure': 0, 'arrival': 4}]}
        raw = {'complete': True, 'raw': [journey], 'final': [],
               'detail': {'journeys': [journey], 'label_insertions': 12, 'complete': True}}
        row = mod.project_record(raw, {})
        self.assertEqual(row['detail']['journeys_count'], 1)
        self.assertEqual(row['detail']['journey_witnesses'][0]['witness_sha256'], mod.digest(journey))
        self.assertEqual(row['detail']['label_insertions'], 12)
        self.assertNotIn('"legs"', json.dumps(row))
        self.assertNotIn('"journeys"', json.dumps(row))

    def test_runner_error_prelaunch_and_portable_command_provenance(self):
        base = self.run_spec('tadbench')
        self.write(self.campaign / 'status.json', {'state': 'runner_error', 'error': 'missing synthetic sidecar'})
        command = {'argv': ['/usr/bin/taskset', '-c', '0-3', str(self.root / 'tadbench')],
                   'environment': {'GOMAXPROCS': '4'}, 'binary': {'path': str(self.root / 'tadbench'), 'sha256': 'a' * 64},
                   'inputs': [{'path': str(self.root / 'input.json'), 'sha256': 'b' * 64}],
                   'sources_before': [{'path': str(self.root / 'source'), 'go_source_hash_sha256': 'c' * 64}],
                   'rss_definition': 'process-group /proc/PID/statm; stdin /dev/null', 'pid': 99}
        command_path = self.write(base.parent / 'command.json', command)
        rows, out, _ = self.project()
        self.assertTrue(all(r['campaign_terminal_state'] == 'runner_error' and r['launch_state'] == 'launched' for r in rows))
        self.assertTrue(all(r['completed'] is None and r['attempted'] is None for r in rows))
        projected = json.loads((out / 'campaigns' / self.campaign.name / 'run-0.command.portable.json').read_text())
        self.assertEqual(projected['argv'][0], '/usr/bin/taskset')
        self.assertEqual(projected['rss_definition'], command['rss_definition'])
        self.assertEqual(projected['binary']['path'], '${SG_ROOT}/tadbench')
        index = json.loads((out / 'ARTIFACT_INDEX.json').read_text())['original_artifact_sha256'][0]['runs'][0]
        self.assertEqual(index['original_artifacts']['run-0/command.json'], mod.sha(command_path))

    def test_runner_error_unstarted_slots_explicit_prelaunch(self):
        self.run_spec('tadbench', items=2)
        self.write(self.campaign / 'status.json', {'state': 'runner_error', 'completed_runs': []})
        rows, out, _ = self.project()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r['launch_state'] == 'prelaunch' and r['unresolved_phase'] == 'prelaunch' for r in rows))
        self.assertTrue(all(r['completed'] is None and r['attempted'] is None for r in rows))
        self.assertTrue(all(r['measurement_role'] == 'offered-unresolved' for r in rows))
        self.assertEqual(json.loads((out / 'campaigns' / self.campaign.name / 'status.portable.json').read_text())['state'], 'runner_error')

    def test_declared_instrumentation_paths_are_narrow_exceptions(self):
        for value in ('/usr/bin/taskset', '/dev/null', '/proc/PID/statm', 'sample /proc/123/status RSS'):
            self.assertEqual(mod.portable(value), value)
        for value in ('/proc/PID/environ', '/dev/null/secret', '/usr/bin/taskset/private', '/etc/passwd'):
            with self.assertRaises(ValueError):
                mod.portable(value)
        self.assertEqual(mod.public_value({'connections': 12, 'transfers': 3}), {'connections': 12, 'transfers': 3})

    def test_source_table_report_and_csv_refused(self):
        self.run_spec('tadbench')
        report = self.write(self.root / 'source-table.json', {'footpaths': [{'from': 'A', 'to': 'B'}]})
        with self.assertRaisesRegex(ValueError, 'Non-outcome'):
            mod.main(['--campaign', str(self.campaign), '--out', str(self.root / 'bad-json'), '--report', str(report)])
        csv = self.root / 'source.csv'
        csv.write_text('stop_id,stop_name\nA,Do not redistribute\n')
        with self.assertRaisesRegex(ValueError, 'Unsupported report type'):
            mod.main(['--campaign', str(self.campaign), '--out', str(self.root / 'bad-csv'), '--report', str(csv)])

    def test_bounds_and_full_witness_flags_refused(self):
        self.run_spec('tadbench')
        for flags in (['--include-full-witnesses'], ['--witness-rights-review', 'claimed']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                mod.main(['--campaign', str(self.campaign), '--out', str(self.root / 'projection')] + flags)
        path = self.write(self.root / 'bounded' / 'file.json', {})
        old = mod.MAX_OUTPUT_FILES
        try:
            mod.MAX_OUTPUT_FILES = 0
            with self.assertRaisesRegex(ValueError, 'budget'):
                mod.output_manifest(path.parent)
        finally:
            mod.MAX_OUTPUT_FILES = old


if __name__ == '__main__':
    unittest.main()
