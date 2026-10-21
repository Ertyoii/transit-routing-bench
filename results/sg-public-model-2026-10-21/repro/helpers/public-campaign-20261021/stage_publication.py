#!/usr/bin/env python3
"""Create-only outcome projections. Never publishes or copies source datasets/witness legs."""
import argparse
from collections import Counter
from contextlib import contextmanager, ExitStack
import io
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_OUTPUT_FILES = 10000
MAX_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
MAX_RECORDS = 2000000
TERMINAL_STATES = {'completed', 'failed', 'stopped', 'stopped_on_failure', 'cancelled', 'interrupted', 'aborted', 'runner_error'}
# Exact public OS executable/instrumentation identifiers, not private files or copied inputs.
DECLARED_SYSTEM_PATH = re.compile(r'''(?<![\w/])(?:/usr/bin/taskset|/dev/null|/proc/(?:PID|[0-9]+|self)/(?:statm|stat|status))(?=$|[\s"'),;:\]])''')
PRIVATE_PATH = re.compile(r"/(?:workspace|home|Users|root|tmp|private)(?:/|$)|(?<![:/\w$}])/(?:[A-Za-z0-9_.~-]+/)+[^\s\"'<>]*|file://|[A-Za-z]:\\")
# Refuse embedded source tables, secret values and full witness payloads, including in reports.
FORBIDDEN_KEYS = {
    'journey', 'journeys', 'journey_at_window_start', 'legs', 'core_arcs', 'raw_edges', 'connections', 'footpaths',
    'stops', 'routes', 'trips', 'transfers', 'vertices', 'edges', 'shortcuts', 'ways', 'nodes', 'relations',
    'stop_times', 'calendar_dates', 'shapes', 'password', 'access_token',
    'refresh_token', 'private_key', 'client_secret', 'api_key',
}
FIELDS = (
    'query', 'stratum', 'completed', 'complete', 'attempted', 'valid_empty',
    'transit', 'status', 'error', 'detail', 'unsupported', 'timed_out',
    'certificates', 'batch', 'core_ns', 'service_start_offset_ns',
    'search_done_offset_ns', 'validation_start_offset_ns', 'response_ns',
    'validation_rank_ns', 'quality_ns', 'core_allocated_bytes', 'stats',
    'recommendation_quality', 'every_integer_ready_time',
    'validated_witness_occurrences', 'requested_source', 'requested_targets',
    'requested_maximum_duration', 'request_shape_valid', 'core_error_kind',
)
ENTRYPOINT_ALGORITHMS = {
    'profilebench': ('profile_csa', 'range_raptor'),
    'tadbench': ('ea_csa', 'raptor', 'tad'),
    'ultrabench': ('ultra_raptor', 'unaccelerated_raptor'),
    'corechgraphbench': ('identity', 'core_ch'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_json(path):
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('Missing or oversized JSON artifact: ' + path.name)
    data = path.read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError('Oversized JSON artifact: ' + path.name)
    return json.loads(data), {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def read(path):
    return load_json(path)[0]


def portable(value):
    if isinstance(value, str):
        value = re.sub(r'(?<![\w/])/__SEALED_RUN_DIR__/', '${SEALED_RUN_DIR}/', value)
        value = value.replace(str(ROOT) + '/', '${SG_ROOT}/')
        value = re.sub(re.escape(str(ROOT)) + r'''(?=$|[\s"'),;])''', '${SG_ROOT}', value)
        if PRIVATE_PATH.search(DECLARED_SYSTEM_PATH.sub('<declared-system-instrumentation>', value)):
            raise ValueError('Private or execution-local path outside SG_ROOT refused')
        return value
    if isinstance(value, list):
        return [portable(x) for x in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            public_key = portable(key)
            if public_key in out:
                raise ValueError('Portable key collision')
            if key == 'checked_field_semantic_sha256' and isinstance(item, dict):
                hashes = {}
                for field, field_value in item.items():
                    target = field + '_sha256' if field in {'connections', 'stops', 'transfers', 'trips'} and isinstance(field_value, str) and re.fullmatch(r'[0-9a-fA-F]{64}', field_value) else field
                    if target in hashes:
                        raise ValueError('Semantic hash key collision')
                    hashes[target] = portable(field_value)
                out[public_key] = hashes
            else:
                out[public_key] = portable(item)
        return out
    return value


def assert_outcome_only(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS and (key.lower() in {'password', 'access_token', 'refresh_token', 'private_key', 'client_secret', 'api_key'} or not isinstance(item, (int, float, bool, type(None)))):
                raise ValueError('Non-outcome payload refused: ' + key)
            assert_outcome_only(item)
    elif isinstance(value, list):
        for item in value:
            assert_outcome_only(item)


def public_value(value):
    value = portable(value)
    assert_outcome_only(value)
    return value


def dump(path, value):
    path.write_text(json.dumps(public_value(value), indent=2, ensure_ascii=False) + '\n')


def safe_name(name):
    if not isinstance(name, str) or name in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', name):
        raise ValueError('Unsafe campaign/run name')
    return name


def artifact_path(base, relative):
    if not isinstance(relative, str):
        raise ValueError('Artifact filename is not a string')
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ('.', '..') for p in parts):
        raise ValueError('Artifact path traversal refused')
    for part in parts:
        safe_name(part)
    path = base / relative
    if not path.resolve().is_relative_to(base.resolve()):
        raise ValueError('Artifact symlink escape refused')
    return path


def validated_vector(value):
    return {'witness_sha256': digest(value.get('journey', value)), 'metrics': value.get('metrics')}


def vectors(row):
    return [validated_vector(value) for value in row.get('final') or []]


def path_cells(cells):
    # Keep every target cell and its order, including unreachable/partial cells.
    return [dict({key: cell[key] for key in ('target', 'found', 'duration') if key in cell},
                 witness_sha256=digest(cell),
                 core_arc_count=len(cell.get('core_arcs') or []),
                 raw_edge_count=len(cell.get('raw_edges') or [])) for cell in cells or []]


def outcome_metadata(value):
    """Retain native diagnostic counters while projecting nested duplicate witnesses."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in {'journey', 'journeys', 'journey_at_window_start', 'legs', 'core_arcs', 'raw_edges'} and isinstance(item, (dict, list)):
                out[key + '_sha256'] = digest(item)
                if isinstance(item, list):
                    out[key + '_count'] = len(item)
                if key == 'journeys':
                    out['journey_witnesses'] = [{'witness_sha256': digest(journey)} for journey in item]
            else:
                out[key] = outcome_metadata(item)
        return out
    if isinstance(value, list):
        return [outcome_metadata(item) for item in value]
    return value


COMPACT_OMISSIONS = [
    'Every emitted outcome, offered slot, request binding, status/error, timing/allocation, diagnostic, objective metric, row certificate and existing witness hash remains present. No outcome rows are sampled or filtered.',
    'recommendation_quality feature identities/patterns/metrics and repeated selected identities/decision maps are omitted. Their original canonical payload SHA256, feature/selection counts, policy, bounded selection configurations and decision-reason counts remain. Recomputing user-choice scores from this compact field alone is not supported.',
    'Preparation/index-cost arrays, including per-transfer sparse certificates and incoming/witness-connection proof cells, are omitted and replaced by original canonical payload SHA256, exact item counts and bounded reason/status counts. Scalar preparation/config/resource/time/count/status/error fields remain; source graph tables and full witness legs are never copied. Detailed proof revalidation requires the original hash-bound artifacts or authorized rerun.',
    'Portable plan/status/command/process/summary metadata are consolidated into provenance-records.jsonl.gz. Each member stores its relative logical path, parsed content, and SHA256/byte size of sorted-key compact UTF8 JSON plus newline. These member hashes are projected bytes, distinct from original file hashes retained in ARTIFACT_INDEX.json.',
    'Canonical payload hashes use sorted-key compact UTF8 JSON without a trailing newline; original raw-file SHA256 remains the authority for original bytes. Configuration/reason summaries are bounded to 64 categories/items; omitted summary categories remain hash-bound, never silently represented as complete.',
]


def category_counts(values):
    counts = Counter(str(value) for value in values)
    ordered = sorted(counts.items())
    return {'counts': dict(ordered[:64]), 'omitted_categories': max(0, len(ordered) - 64),
            'omitted_occurrences': sum(count for _, count in ordered[64:])}


def payload_summary(value, kind):
    result = {'projection': kind, 'original_payload_sha256': digest(value),
              'item_count': len(value) if isinstance(value, (dict, list)) else None}
    if isinstance(value, list):
        for field in ('reason', 'status', 'error_kind', 'complete', 'unsupported'):
            observed = [item[field] for item in value if isinstance(item, dict) and field in item]
            if observed:
                result[field + '_summary'] = category_counts(observed)
    return result


def compact_quality(value):
    result = payload_summary(value, 'compact-quality-summary-v1')
    if not isinstance(value, dict):
        return result
    for key in ('policy', 'config_sha256', 'preference_config_sha256', 'global_optimality_claim'):
        if key in value and isinstance(value[key], (str, int, float, bool, type(None))):
            result[key] = value[key]
    features = value.get('features') or []
    selections = value.get('selections') or []
    result.update(feature_count=len(features), selection_count=len(selections),
                  omitted_selection_configurations=max(0, len(selections) - 64))
    configurations = []
    for selection in selections[:64]:
        entry = {key: selection[key] for key in ('limit', 'score_envelope_seconds', 'global_optimality_claim', 'profile')
                 if key in selection and isinstance(selection[key], (str, int, float, bool, type(None)))}
        entry.update(selected_count=len(selection.get('selected') or []),
                     decision_count=len(selection.get('decisions') or {}),
                     original_selection_sha256=digest(selection))
        entry['decision_reason_summary'] = category_counts((selection.get('decisions') or {}).values())
        configurations.append(entry)
    result['selection_configurations'] = configurations
    return result


def compact_preparation(value):
    if isinstance(value, list):
        return payload_summary(value, 'compact-preparation-array-v1')
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in FORBIDDEN_KEYS and isinstance(item, (dict, list)):
                result[key + '_projection'] = payload_summary(item, 'compact-preparation-payload-v1')
            else:
                result[key] = compact_preparation(item)
        return result
    return value


def compact_summary(value):
    if not isinstance(value, dict):
        raise ValueError('Native summary must be an object')
    result = dict(value)
    for key in ('preparation', 'index_cost_final', 'quality_preparation', 'checker_preparation', 'raptor_preparation'):
        if key in result:
            result[key] = compact_preparation(result[key])
    result['publication_projection'] = 'compact-summary-v1'
    return result


@contextmanager
def gzip_text(path, deterministic=False):
    if not deterministic:
        with gzip.open(path, 'wt', encoding='utf-8') as stream:
            yield stream
    else:
        with path.open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding='utf-8', newline='\n') as stream:
                    yield stream


def project_record(raw, context, compact=False):
    if not isinstance(raw, dict):
        raise ValueError('Outcome record is not an object')
    row = dict(context, projection='outcome-projection-v2', original_record_sha256=digest(raw))
    row.update({key: outcome_metadata(raw[key]) if key in {'detail', 'stats', 'certificates', 'recommendation_quality'} else raw[key] for key in FIELDS if key in raw and not (compact and key == 'recommendation_quality')})
    if compact and 'recommendation_quality' in raw:
        row['recommendation_quality'] = compact_quality(raw['recommendation_quality'])
        row['projection'] = 'compact-outcome-projection-v1'
    if 'complete' in raw:
        # Preserve the native spelling and add the familybench-compatible alias.
        row.setdefault('completed', raw['complete'])
    candidate = raw.get('raw')
    if isinstance(candidate, dict) and 'paths' in candidate:
        row['raw'] = {key: candidate[key] for key in ('source', 'maximum_duration', 'complete', 'stats') if key in candidate}
        row['raw']['paths'] = path_cells(candidate['paths'])
        row['validated_paths'] = path_cells(raw.get('final'))
        row['requested_target_count'] = len(raw.get('requested_targets') or [])
        row['raw_candidate_count'] = len(candidate.get('paths') or [])
        row['validated_candidate_count'] = len(raw.get('final') or [])
        row['denominator_unit'] = 'one-source-many-target-row-and-ordered-cells'
    elif 'requested_targets' in raw:
        row['requested_target_count'] = len(raw.get('requested_targets') or [])
        row['raw_candidate_count'] = None
        row['validated_candidate_count'] = None
        row['denominator_unit'] = 'one-source-many-target-row-and-ordered-cells'
    elif 'final_points' in raw:

        row['validated_profile_points'] = [dict(latest_ready=p.get('latest_ready'),
                                                   **validated_vector(p['validated']))
                                           for p in raw.get('final_points') or []]
        if isinstance(candidate, dict):
            row['raw_profile_points'] = [dict({key: p[key] for key in ('latest_ready', 'arrival', 'boardings') if key in p},
                                              witness_sha256=digest(p.get('journey', p)))
                                         for p in candidate.get('transit_points') or []]
            row['raw_profile_complete'] = candidate.get('complete')
        if raw.get('final_direct') is not None:
            row['validated_profile_direct'] = validated_vector(raw['final_direct'])
        if isinstance(candidate, dict) and candidate.get('direct_walking') is not None:
            direct = candidate['direct_walking']
            row['raw_profile_direct'] = dict({key: direct[key] for key in ('duration',) if key in direct}, witness_sha256=digest(direct.get('journey_at_window_start', direct)))
        row['raw_profile_transit_point_count'] = len(row.get('raw_profile_points') or [])
        row['validated_profile_transit_point_count'] = len(raw.get('final_points') or [])
        row['raw_candidate_count'] = row['raw_profile_transit_point_count'] + int('raw_profile_direct' in row)
        row['validated_candidate_count'] = row['validated_profile_transit_point_count'] + int('validated_profile_direct' in row)
        row['ready_time_observation_count'] = len(raw.get('every_integer_ready_time') or [])
        row['denominator_unit'] = 'whole-inclusive-ready-window-query'
    else:
        row['raw_candidate_count'] = len(candidate or [])
        row['validated_candidate_count'] = len(raw.get('final') or [])
        row['validated_objectives'] = vectors(raw)
        row['denominator_unit'] = 'point-query'
    return public_value(row)


def option(spec, name, default=None):
    argv = spec['argv']
    return argv[argv.index(name) + 1] if name in argv else default


def algorithms(spec):
    chosen = option(spec, '-algorithm')
    return (chosen,) if chosen else ENTRYPOINT_ALGORITHMS.get(Path(spec['argv'][0]).name, (Path(spec['argv'][0]).name,))


def offered_unresolved(spec, summary=None):
    """Offered requests, never invented native completions or accepted empty results."""
    query_path = option(spec, '-queries') or option(spec, '-workload')
    if not query_path:
        raise ValueError('Cannot bind offered workload for run ' + spec['id'])
    query_path = Path(query_path)
    if not query_path.is_absolute():
        query_path = Path(spec.get('cwd', ROOT)) / query_path
    work, binding = load_json(query_path)
    items = work.get('items', [])
    if not items:
        raise ValueError('Offered workload has no items for run ' + spec['id'])
    native = Path(spec['argv'][0]).name
    if native == 'corechgraphbench':
        anchors = sorted({q[key] for item in items for q in [item.get('query', item)] for key in ('origin', 'destination')})
        maximum = int(option(spec, '-maximum-duration', '600'))
        if summary:
            for key, expected in [('requested_rows_per_pass', len(anchors)), ('requested_cells_per_pass', len(anchors) ** 2)]:
                if key in summary and summary[key] != expected:
                    raise ValueError('Native/offered denominator mismatch: ' + key)
        records = [dict(requested_source=source, requested_targets=anchors,
                        requested_maximum_duration=maximum) for source in anchors]
    else:
        records = [dict(query=item.get('query', item), **({'stratum': item['stratum']} if 'stratum' in item else {})) for item in items]
    for algorithm in algorithms(spec):
        for record in records:
            yield dict(record, algorithm=algorithm, attempted=None, completed=None,
                       status='process_unresolved', response_ns=None,
                       offered_workload_sha256=binding['sha256'],
                       record_evidence='offered workload only; no emitted native outcome for this request')


def project_campaign(campaign, destination, emit, compact=False, metadata_writer=None):
    plan, plan_binding = load_json(campaign / 'plan.json')
    status, status_binding = load_json(campaign / 'status.json')
    if status.get('state') not in TERMINAL_STATES:
        raise ValueError('Campaign is active or its terminal state is unknown: ' + campaign.name)
    if metadata_writer is None:
        destination.mkdir()
    put = metadata_writer or dump
    put(destination / 'plan.portable.json', plan)
    put(destination / 'status.portable.json', status)
    index = []
    seen_ids = set()
    for spec in plan['runs']:
        run_id = safe_name(spec['id'])
        if run_id in seen_ids:
            raise ValueError('Duplicate run ID')
        seen_ids.add(run_id)
        run_dir = artifact_path(campaign, run_id)
        base = run_dir / 'artifact'
        item = {'campaign': campaign.name, 'run_id': run_id,
                'original_plan_sha256': plan_binding['sha256'], 'original_artifacts': {},
                'original_artifact_manifest': [], 'projected_record_counts': {},
                'campaign_terminal_state': status['state']}
        counts = Counter()
        process_path = run_dir / 'result.json'
        command_path = run_dir / 'command.json'
        native_artifacts_present = base.exists() and any(base.glob('*.json'))
        command = read(command_path) if command_path.exists() else {}
        launch_state = ('launched' if native_artifacts_present or command.get('pid') or process_path.exists()
                        else 'launch-unconfirmed' if command_path.exists() else 'prelaunch')
        item.update(launch_state=launch_state, command_present=command_path.exists(),
                    process_result_present=process_path.exists(), native_artifacts_present=bool(native_artifacts_present))

        def load(path):
            value, binding = load_json(path)
            relative = str(path.relative_to(campaign))
            item['original_artifacts'][relative] = binding['sha256']
            item['original_artifact_manifest'].append(dict(path=relative, **binding))
            return value, binding

        def records(payload, relative, binding, metadata, role):
            values = payload if isinstance(payload, list) else payload.get('records', [])
            if not isinstance(values, list):
                raise ValueError('Record collection is not a list')
            for number, raw in enumerate(values):
                wrapper = {}
                if 'record' in raw:
                    wrapper = {key: value for key, value in raw.items() if key != 'record'}
                    raw = raw['record']
                context = dict(campaign=campaign.name, run_id=run_id,
                               campaign_terminal_state=status['state'], launch_state=launch_state,
                               algorithm=wrapper.get('algorithm', metadata.get('algorithm')),
                               repetition=metadata.get('repetition'),
                               forced=role.startswith('forced') or bool(metadata.get('forced')),
                               warmup=bool(metadata.get('warmup')), measurement_role=role,
                               record_evidence='emitted native outcome',
                               source_artifact=relative, source_artifact_sha256=binding['sha256'],
                               source_record_index=number)
                if wrapper:
                    context['diagnostic_metadata'] = wrapper
                row = project_record(raw, context, compact=compact)
                if role == 'forced-preparation':
                    row['original_record_sha256'] = wrapper['original_attempted_query_sha256']
                    row['record_projection_source'] = 'attempted_query'
                emit(row)
                counts[role] += 1
            return len(values)

        if command_path.exists():
            value, _ = load(command_path)
            put(destination / (run_id + '.command.portable.json'), value)
        if process_path.exists():
            value, _ = load(process_path)
            put(destination / (run_id + '.process.json'), value)
        summaries = [p for p in (base / 'summary.json', base / 'manifest.json') if p.exists()]
        if len(summaries) > 1:
            raise ValueError('Ambiguous native summary and manifest for ' + run_id)
        summary = {}
        seen_passes = set()
        emitted_slots = set()
        preparation_unavailable = False
        if summaries:
            sf = summaries[0]
            summary, _ = load(sf)
            put(destination / (run_id + '.' + sf.name), compact_summary(summary) if compact else summary)
        passes = summary.get('passes') or summary.get('summaries') or []
        if not isinstance(passes, list):
            raise ValueError('Pass summaries are not a list')

        def emit_pass(pass_spec, summary_bound):
            relative = pass_spec['file']
            if relative in seen_passes:
                raise ValueError('Duplicate native pass reference')
            seen_passes.add(relative)
            path = artifact_path(base, relative)
            payload, binding = load(path)
            if not isinstance(payload, dict) or not isinstance(payload.get('records'), list):
                raise ValueError('Native pass has no record list')
            if pass_spec.get('sha256') not in (None, binding['sha256']):
                raise ValueError('Native pass hash mismatch')
            metadata = {key: payload[key] for key in ('algorithm', 'repetition', 'warmup') if key in payload}
            for key in ('algorithm', 'repetition', 'warmup'):
                if key in pass_spec and key in metadata and pass_spec[key] != metadata[key]:
                    raise ValueError('Native pass metadata mismatch: ' + key)
            metadata = dict(summary, **metadata)
            metadata.update(pass_spec)
            role = 'forced-deadline' if metadata.get('forced') else ('warmup' if metadata.get('warmup') else 'measured')
            n = records(payload, str(path.relative_to(campaign)), binding, metadata, role)
            for key in ('requested', 'queries', 'profile_queries', 'rows'):
                if key in pass_spec and n != pass_spec[key]:
                    raise ValueError('Native pass record denominator mismatch: ' + key)
            if role in ('measured', 'warmup'):
                slot = (metadata.get('algorithm'), metadata.get('repetition'))
                if slot in emitted_slots:
                    raise ValueError('Duplicate emitted algorithm/repetition slot')
                emitted_slots.add(slot)
            item.setdefault('pass_bindings', []).append({
                'file': str(path.relative_to(campaign)), 'native_summary_bound': summary_bound,
                'algorithm': metadata.get('algorithm'), 'repetition': metadata.get('repetition'),
                'warmup': bool(metadata.get('warmup')), 'forced': role == 'forced-deadline',
                'projected_records': n})

        for pass_spec in passes:
            emit_pass(pass_spec, True)
        # Drivers may finish one pass but die before their final manifest is emitted.
        # Discover only known outcome filenames, never indices, snapshots or raw inputs.
        pattern = re.compile(r'(?:pass-\d+|forced-deadline|(?:identity|core_ch|ultra_raptor|unaccelerated_raptor)-pass-\d+|\d+-(?:profile_csa|range_raptor|ea_csa|raptor|tad))\.json')
        if base.exists():
            for path in sorted(base.iterdir()):
                if pattern.fullmatch(path.name) and path.name not in seen_passes:
                    emit_pass({'file': path.name, 'forced': path.name == 'forced-deadline.json'}, False)
        prep_failures = base / 'preparation-failures.json'
        if prep_failures.exists():
            payload, binding = load(prep_failures)
            n = records(payload, str(prep_failures.relative_to(campaign)), binding,
                        {'algorithm': 'ultra_raptor' if Path(spec['argv'][0]).name == 'ultrabench' else algorithms(spec)[0]}, 'preparation-unavailable')
            if 'requested' in summary and n != summary['requested']:
                raise ValueError('Preparation failure denominator mismatch')
            preparation_unavailable = n > 0
        for filename, role in (('forced-deadlines.json', 'forced-deadline'), ('target-partitions.json', 'diagnostic-target-partition')):
            path = base / filename
            if path.exists() and filename not in seen_passes:
                payload, binding = load(path)
                records(payload, str(path.relative_to(campaign)), binding, {}, role)
        path = base / 'forced-preparation.json'
        if path.exists():
            payload, binding = load(path)
            # Snapshot/index contents are intentionally omitted; bind their original file.
            record = payload['attempted_query']
            raw = {'raw': record, 'complete': record.get('complete', False),
                   'request_shape_valid': payload.get('query_request_shape_valid'),
                   'core_error_kind': payload.get('preparation_error_kind')}
            raw.update(requested_source=record.get('source'),
                       requested_targets=[p.get('target') for p in record.get('paths') or []],
                       requested_maximum_duration=record.get('maximum_duration'))
            metadata = {key: payload[key] for key in ('expected_failure_observed', 'preparation_error_kind', 'query_request_shape_valid', 'elapsed_ns') if key in payload}
            metadata['request_binding_source'] = 'native attempted_query plus independently checked native shape flag; requested aliases are derived'
            metadata['original_attempted_query_sha256'] = digest(record)
            records([dict(record=raw, **metadata)], str(path.relative_to(campaign)), binding,
                    {'algorithm': 'core_ch'}, 'forced-preparation')
        warmups = int(option(spec, '-warmups', str(summary.get('warmups', 0))))
        repetitions = int(option(spec, '-repetitions', str(summary.get('repetitions', 1))))
        if warmups < 0 or repetitions < 1 or warmups + repetitions > 10000:
            raise ValueError('Invalid or excessive planned repetition count')
        missing_slots = [(algorithm, rep) for algorithm in algorithms(spec)
                         for rep in range(warmups + repetitions)
                         if (algorithm, rep) not in emitted_slots]
        if missing_slots and not preparation_unavailable:
            offered = list(offered_unresolved(spec, summary))
            for algorithm, rep in missing_slots:
                for number, original in enumerate(offered):
                    if original['algorithm'] != algorithm:
                        continue
                    raw = dict(original)
                    raw.pop('algorithm')
                    evidence = raw.pop('record_evidence')
                    binding = raw.pop('offered_workload_sha256')
                    context = dict(campaign=campaign.name, run_id=run_id, algorithm=algorithm,
                                   campaign_terminal_state=status['state'], launch_state=launch_state,
                                   unresolved_phase='prelaunch' if launch_state == 'prelaunch' else 'no-emitted-native-slot',
                                   repetition=rep, forced=False, warmup=rep < warmups,
                                   measurement_role='offered-unresolved',
                                   planned_measurement_role='warmup' if rep < warmups else 'measured',
                                   source_record_index=number)
                    row = project_record(raw, context, compact=compact)
                    if launch_state == 'prelaunch':
                        evidence = 'offered workload only; prelaunch, no command/process/native execution evidence; no native attempt or completion claimed'
                    row.update(record_evidence=evidence, offered_workload_sha256=binding,
                               raw_candidate_count=None, validated_candidate_count=None)
                    emit(row)
                    counts['offered-unresolved'] += 1
        item['projected_record_counts'] = dict(counts)
        index.append(item)
    return {'campaign': campaign.name, 'plan': dict(path='plan.json', **plan_binding), 'status': dict(path='status.json', **status_binding), 'runs': index}


def output_manifest(out):
    files = []
    total = 0
    for path in sorted(out.rglob('*')):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if len(files) >= MAX_OUTPUT_FILES or total > MAX_OUTPUT_BYTES:
            raise ValueError('Publication output exceeds bounded file/byte budget')
        files.append({'path': str(path.relative_to(out)), 'bytes': size, 'sha256': sha(path)})
    return {'schema': 'public-outcome-projection-file-manifest-v1', 'files': files,
            'file_count': len(files), 'total_bytes': total,
            'bounds': {'max_files': MAX_OUTPUT_FILES, 'max_total_bytes': MAX_OUTPUT_BYTES},
            'scope': 'Every staged file except this self-referential manifest; not byte-identical raw originals.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, action='append', required=True)
    parser.add_argument('--report', type=Path, action='append', default=[])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compact', action='store_true', help='Hash verbose quality/preparation arrays and consolidate portable metadata; no outcome rows omitted')
    # Fail closed instead of allowing an old invocation to redistribute witnesses.
    parser.add_argument('--include-full-witnesses', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--witness-rights-review', default='', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.include_full_witnesses or args.witness_rights_review:
        parser.error('This outcome-only publisher never includes full witness legs or source datasets')
    names = [safe_name(c.name) for c in args.campaign]
    if len(names) != len(set(names)):
        parser.error('Campaign names must be unique')
    # Validate terminal states and portability before creating a destination.
    for campaign in args.campaign:
        state = read(campaign / 'status.json').get('state')
        if state not in TERMINAL_STATES:
            parser.error('Campaign is active or terminal state is unknown: ' + campaign.name)
        public_value(read(campaign / 'plan.json'))
        public_value(read(campaign / 'status.json'))
    args.out.mkdir(parents=True, exist_ok=False)
    if not args.compact:
        (args.out / 'campaigns').mkdir()
    (args.out / 'reports').mkdir()
    row_count = 0
    index = []
    provenance_members = 0
    provenance_bytes = 0
    with ExitStack() as stack:
        stream = stack.enter_context(gzip_text(args.out / 'outcome-records.jsonl.gz', args.compact))
        provenance = stack.enter_context(gzip_text(args.out / 'provenance-records.jsonl.gz', True)) if args.compact else None
        def write_metadata(path, value):
            nonlocal provenance_members, provenance_bytes
            content = public_value(value)
            data = (json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n').encode()
            provenance_members += 1
            provenance_bytes += len(data)
            if provenance_members > MAX_OUTPUT_FILES or provenance_bytes > MAX_OUTPUT_BYTES:
                raise ValueError('Compact provenance member/byte budget exceeded')
            member = {'path': str(path.relative_to(args.out)), 'bytes': len(data),
                      'sha256': hashlib.sha256(data).hexdigest(), 'content': content}
            provenance.write(json.dumps(member, sort_keys=True, separators=(',', ':'), ensure_ascii=False) + '\n')
        def emit(row):
            nonlocal row_count
            row_count += 1
            if row_count > MAX_RECORDS:
                raise ValueError('Outcome record budget exceeded')
            stream.write(json.dumps(public_value(row), sort_keys=args.compact, separators=(',', ':'), ensure_ascii=False) + '\n')
        campaigns = sorted(args.campaign, key=lambda c: c.name) if args.compact else args.campaign
        for campaign in campaigns:
            index.append(project_campaign(campaign, args.out / 'campaigns' / campaign.name, emit, compact=args.compact, metadata_writer=write_metadata if args.compact else None))
    report_bindings = []
    for path in args.report:
        dest = args.out / 'reports' / safe_name(path.name)
        if dest.exists():
            raise ValueError('Duplicate report filename')
        if path.suffix == '.json':
            value, binding = load_json(path)
            report_bindings.append(dict(path=path.name, **binding))
            dump(dest, value)
        else:
            if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError('Missing or oversized text report')
            if path.suffix.lower() not in ('.md', '.txt', '.py', '.sh', '.patch'):
                raise ValueError('Unsupported report type; no binary or dataset copying')
            data = path.read_bytes()
            if len(data) > MAX_SOURCE_BYTES:
                raise ValueError('Oversized text report')
            report_bindings.append({'path': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            dest.write_text(portable(data.decode()))
    dump(args.out / 'ARTIFACT_INDEX.json', {
        'schema': 'public-outcome-portable-projection-v2',
        'original_artifact_sha256': index, 'original_report_artifacts': report_bindings, 'rows': row_count,
        'full_witnesses_included': False, 'projection_source_sha256': sha(Path(__file__)),
        'compact_mode': args.compact, 'provenance_member_count': provenance_members,
        'compact_omissions': COMPACT_OMISSIONS if args.compact else [],
        'qualification_limits': [
            'Outcome projection, not identical raw originals. Original file SHA256 and byte sizes bind retained evidence; projected byte hashes differ.',
            'Every emitted ordinary, warmup, forced-deadline, forced-preparation and target-partition record is retained and labeled. Never pool diagnostic/warmup records into measured latency.',
            'Native complete and completed are retained; no emitted outcome means offered-unresolved with null attempted/completed, never a successful or valid-empty query. Terminal runner_error and prelaunch slots are retained under original campaign status. Preparation-unavailable requests retain the offered denominator.',
            'Portable command records retain exact argv, selected environment, binary/input/source hash provenance. Exact public /usr/bin/taskset, /dev/null and /proc PID/stat/statm/status identifiers are declared OS instrumentation metadata only, not private paths or files read/copied by publication.',
            'CoreCH keeps requested source/cap/ordered targets and every raw/final target cell, including unreachable cells. Witness edges/arcs are digests/counts only; row latency is never divided by cells.',
            'Profile objectives preserve compact latest-ready points and every integer-ready-time arrival vector. Whole-window latency is not point-query latency; TAD/reference output work differs.',
            'No full journey legs, raw graph edges, source database, GTFS/OSM data, LTA assets, binaries or credentials are included by native outcome projection. Attached narrative/source reports still require independent publication review; source-data CSV/TSV and binary reports are refused. Raw-input redistribution rights remain unverified.',
            'Reproduction requires authorized retrieval of independently hash-checked source data and rerun. This package alone cannot reconstruct omitted witness legs or establish real-world/latest-official Singapore validity.',
            'Only allowlisted native schemas are projected. A killed active in-memory pass cannot be recovered; its offered requests remain unassessed, not invented outcomes. No push is performed.',
        ],
    })
    manifest = output_manifest(args.out)
    sums = {file['path']: file['sha256'] for file in manifest['files']}
    dump(args.out / 'SHA256SUMS.json', sums)
    manifest = output_manifest(args.out)
    manifest_bytes = len((json.dumps(public_value(manifest), indent=2, ensure_ascii=False) + '\n').encode())
    if manifest['file_count'] + 1 > MAX_OUTPUT_FILES or manifest['total_bytes'] + manifest_bytes > MAX_OUTPUT_BYTES:
        raise ValueError('Publication including manifest exceeds bounded file/byte budget')
    dump(args.out / 'PUBLICATION_MANIFEST.json', manifest)
    # Scan compressed records as text too; do not let gzip bypass portability checks.
    with gzip.open(args.out / 'outcome-records.jsonl.gz', 'rt', encoding='utf-8') as stream:
        for line in stream:
            public_value(json.loads(line))
    if args.compact:
        with gzip.open(args.out / 'provenance-records.jsonl.gz', 'rt', encoding='utf-8') as stream:
            for line in stream:
                public_value(json.loads(line))
    for path in args.out.rglob('*'):
        if path.is_file() and path.suffix != '.gz':
            portable(path.read_text())
    path = args.out / 'PUBLICATION_MANIFEST.json'
    result = {'out': args.out.name, 'rows': row_count,
              'files': manifest['file_count'] + 1, 'pushed': False,
              'compact_mode': args.compact, 'provenance_members': provenance_members,
              'manifest': {'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)}}
    print(json.dumps(result))
    return result


if __name__ == '__main__':
    main()
