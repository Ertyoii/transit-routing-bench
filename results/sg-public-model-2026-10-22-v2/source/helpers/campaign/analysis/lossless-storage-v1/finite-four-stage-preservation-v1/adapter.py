#!/usr/bin/env python3
"""DRAFT, unqualified. Manual metadata/preservation only; never launch or score.

Reuse V3 typed terminal/memory checks and unchanged storage.py operations.
Only the four-plan authority, stage counts/order and absolute positions differ.
No resume: any existing stage intent/archive/receipt is STOP/inspect, not retry.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path('/workspace/shared/sg-coldstart/campaign-v2-20261021')
HERE = Path(__file__).resolve().parent
Q = ROOT / 'qualification/cap96-native216-v1-bindings'
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
READY = {'path': str(Q / 'READY_FOR_INDEPENDENT_REVIEW.json'), 'bytes': 11963,
         'sha256': '3ce0ab9711987b696587d45850e929fe9337de0c78e4117bf9064e477d0aaea0'}
MANIFEST_SHA = '8bd8914f730772e6ab6ff535cbd78e03c7a1c1b1717643560ff61a7c77e98f5d'
GENERIC = ROOT / 'analysis/lossless-storage-v1/stage-workflow-v3/post_stage.py'
GENERIC_SHA = '6174a8efed3f727da4302a8263dae271c0d6f74cf2d013e1857a5f270b36459e'
STAGES = (('caps', 0, 48, 0), ('caps', 1, 48, 48),
          ('native', 0, 108, 96), ('native', 1, 108, 204))


def load_qualified():
    # Import source only after checking its accepted identity under campaign lock.
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = GENERIC.read_bytes()
        if hashlib.sha256(source).hexdigest() != GENERIC_SHA:
            raise RuntimeError('Qualified generic terminal source changed')
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('finite_preservation_generic', GENERIC)
        w = importlib.util.module_from_spec(spec)
        exec(compile(source, str(GENERIC), 'exec'), w.__dict__)
    finally:
        os.close(fd)
    return w, w.load_helper()


def context(w, s, index):
    w.require(type(index) is int and 0 <= index < 4, 'Not an exact frozen four-stage index')
    ready = w.bound(s, READY)
    authority = ready['four_stage_plan_manifest']
    w.require(authority['sha256'] == MANIFEST_SHA, 'Four-stage authority changed')
    manifest = w.bound(s, authority)
    w.require(len(manifest['stages']) == len(ready['stages']) == 4, 'Four-stage closure changed')
    plans = []
    all_ids = []
    for i, (lane, block, count, offset) in enumerate(STAGES):
        stage, advertised = manifest['stages'][i], ready['stages'][i]
        root = ROOT / 'experiments' / ('%s-v1-b%d-run' % ('cap96' if lane == 'caps' else 'native216', block))
        w.require(stage['stage'] == advertised['stage'] == lane and
                  type(stage['block']) is int and stage['block'] == advertised['block'] == block and
                  stage['plan'] == advertised['plan'] and stage['future_serving_root'] == str(root),
                  'Frozen stage/order/root identity mismatch')
        plan = w.bound(s, stage['plan'])
        freeze = w.bound(s, stage['preparation_freeze'])
        rows = plan['finite_lane']['all_state_rows']
        w.require(plan['continue_on_failure'] is False and plan['finite_lane']['stage'] == lane and
                  type(plan['finite_lane']['block']) is int and plan['finite_lane']['block'] == block and
                  len(rows) == len(plan['runs']) == count and
                  [r['id'] for r in rows] == [r['id'] for r in plan['runs']] and
                  all(r['state'] == 'PLANNED_UNSTARTED' for r in rows) and
                  freeze['plan'] == stage['plan'] and freeze['offered'] == count and freeze['unoffered'] == 0 and
                  advertised['offered'] == count and advertised['original_slots'] == count and advertised['unoffered'] == 0,
                  'Exact finite original/offered census or order changed')
        w.require(freeze['parser_coverage'] == stage['parser_coverage'] and
                  freeze['actual_envelopes'] == stage['actual_runner_envelopes'] and
                  freeze['memory_admission'] == plan['memory_admission'], 'Preparation binding mismatch')
        for key in ('parser_coverage', 'actual_runner_envelopes'):
            w.bound(s, stage[key])
        w.bound(s, freeze['prospective_specs'])
        plans.append(plan)
        all_ids.extend(r['id'] for r in rows)
    w.require(len(all_ids) == len(set(all_ids)) == 312, 'Original312 ID loss/duplication')
    for first in (0, 2):
        a, b = ([r['id'] for r in plans[j]['runs']] for j in (first, first + 1))
        w.require(all(r.startswith('b0-') for r in a) and all(r.startswith('b1-') for r in b) and
                  [r[3:] for r in b] == list(reversed([r[3:] for r in a])),
                  'Each lane block1 must be the exact reverse of its own block0')
    admission = w.bound(s, ready['storage_admission'])
    request = w.bound(s, ready['storage_request'])
    inventory = w.bound(s, ready['before_creation_inventory'])
    w.require(admission['request'] == request and admission['request_sha256'] == ready['storage_request']['sha256'] and
              admission['inventory_sha256'] == ready['before_creation_inventory']['sha256'] and
              admission['measurement_lock'] == str(LOCK) and request['four_stage_plan_manifest'] == authority,
              'Prospective storage ancestry mismatch')
    w.require(len(request['outputs']) == 320 and
              {role: sum(e['role'] == role for e in request['outputs']) for role in
               ('proof-summary', 'proof-sidecar', 'redundant-metrics')} ==
              {'proof-summary': 168, 'proof-sidecar': 144, 'redundant-metrics': 8}, 'Exact320 allowlist changed')
    lane, block, count, offset = STAGES[index]
    stage = dict(manifest['stages'][index], storage_admission=ready['storage_admission'])
    root, plan = s.canonical(stage['future_serving_root']), plans[index]
    by_run = {r['id']: [] for r in plan['runs']}  # Native offers without eligible raw still MUST be checked.
    for entry in request['outputs']:
        if entry['role'] == 'redundant-metrics' or (entry['stage'], entry['block']) != (lane, block):
            continue
        rid = entry['run_id']
        w.require(rid in by_run and entry['role'] in {'proof-summary', 'proof-sidecar'} and
                  Path(entry['raw_path']).parent == root / rid / 'artifact' and
                  entry['frozen_bindings']['plan_sha256'] == stage['plan']['sha256'] and
                  entry['allow_raw_retirement'] is True and entry['retire_receipt_paths'],
                  'Nonexact eligible stage raw path/ancestry')
        by_run[rid].append(entry)
    return ready, stage, plan, root, by_run, offset


def terminal(w, s, index):
    ready, stage, plan, root, by_run, offset = context(w, s, index)
    status, writer, observations = w.terminal_metadata(s, index, ready, stage, plan, root, by_run)
    offered = [r['id'] for r in plan['runs']]
    completed = status['document'].get('completed_runs', [])
    w.require([r['id'] for r in completed] == offered[:len(completed)], 'Consumed offers not exact original prefix')
    records = {}
    for position, spec in enumerate(plan['runs']):
        rid = spec['id']
        command, result, memory = observations[rid]
        consumed = command['state'] != 'MISSING' or result['state'] != 'MISSING' or memory['state'] != 'MISSING'
        if consumed:
            w.require(result['state'] == memory['state'] == 'PRESENT' and result['document'].get('id') == rid,
                      'Consumed offer lacks parseable exact result/admission; no optional skip')
        records[rid] = {'id': rid, 'global_position': offset + position,
                        'initial_state_row': plan['finite_lane']['all_state_rows'][position], 'offered_spec': spec,
                        'state': 'RESULT_RECORDED' if consumed else 'UNSTARTED_AFTER_TERMINAL_STAGE',
                        'command': {k: v for k, v in command.items() if k != 'document'},
                        'result': {k: v for k, v in result.items() if k != 'document'},
                        'memory_admission': {k: v for k, v in memory.items() if k != 'document'},
                        'parsed_result': result['document']}
    return ready, stage, plan, root, by_run, status, writer, records


def record_metadata(w, s, index):
    with s.quiet(LOCK):
        ready, stage, plan, root, by_run, status, writer, records = terminal(w, s, index)
        destination = HERE / ('%s-b%d' % (stage['stage'], stage['block']))
        s.absent(destination)
        destination.mkdir()
        manifests = {}
        for rid, row in records.items():
            path = destination / (rid + '.json')
            s.write_doc(path, {k: v for k, v in row.items() if k != 'parsed_result'})
            manifests[rid] = w.identity(s, path)
        path = destination / 'STAGE_METADATA.json'
        value = {'schema': 'finite-four-stage-terminal-metadata-v1', 'stage_index': index,
                 'ready_receipt': READY, 'four_stage_plan_manifest': ready['four_stage_plan_manifest'],
                 'plan': stage['plan'], 'admission': ready['storage_admission'],
                 'terminal_status': {k: v for k, v in status.items() if k != 'document'},
                 'writer_terminal': writer, 'run_manifests': manifests,
                 'rows': [{k: v for k, v in row.items() if k not in ('offered_spec', 'parsed_result')}
                          for row in records.values()],
                 'operational_exit0_complete': w.success_records(status['document'], plan, records),
                 'scientific_completeness': 'PENDING_INDEPENDENT_SOURCE_OUTPUT_REVIEW',
                 'advancement_authorized': False, 'archive_or_retirement_performed': False}
        s.write_doc(path, value)
        return w.identity(s, path)


def preserve_stage(w, s, index, independent_ref):
    # Independent receipt may cover caps0+1 or native0+1, never inferred from exit0.
    with s.quiet(LOCK):
        ready, stage, plan, root, by_run, status, writer, records = terminal(w, s, index)
        accepted = w.bound(s, independent_ref)
        w.require(accepted['schema'] == 'finite-four-stage-consumed-offer-integrity-acceptance-v1' and
                  accepted['status'] == 'PASS' and accepted['ready_receipt'] == READY and
                  accepted['four_stage_plan_manifest'] == ready['four_stage_plan_manifest'] and
                  accepted['storage_admission'] == ready['storage_admission'], 'Independent integrity acceptance missing/mismatched')
        matches = [x for x in accepted['stages'] if x['stage_index'] == index]
        w.require(len(matches) == 1, 'Independent receipt must bind this stage exactly once')
        audit = matches[0]
        w.require(audit['all_original_slots_accounted'] is True and
                  audit['exact_command_result_wrapper_memory_source_binary_input_config_registry_checked'] is True and
                  audit['typed_process_and_group_terminality_checked'] is True,
                  'Independent consumed-offer checks incomplete')
        metadata = w.bound(s, audit['stage_metadata'])
        w.require(metadata['stage_index'] == index and metadata['ready_receipt'] == READY and
                  metadata['plan'] == stage['plan'] and metadata['admission'] == ready['storage_admission'] and
                  metadata['terminal_status'] == {k: v for k, v in status.items() if k != 'document'},
                  'Accepted stage metadata/status ancestry changed')
        w.require(metadata['rows'] == [{k: v for k, v in row.items() if k not in ('offered_spec', 'parsed_result')}
                                      for row in records.values()], 'Accepted original-position evidence changed')
        for rid, row in records.items():
            w.require(w.bound(s, metadata['run_manifests'][rid]) ==
                      {k: v for k, v in row.items() if k != 'parsed_result'}, 'Accepted run manifest/evidence changed')
        entries = [e for es in by_run.values() for e in es]
        present = {e['raw_path']: e for e in entries if s.exists(Path(e['raw_path']))}
        refs = audit['present_eligible_raw_files']
        w.require(len(refs) == len({r['path'] for r in refs}) and set(present) == {r['path'] for r in refs},
                  'Missing/unexpected raw or previously retired raw; inspect exact accepted ancestry, never retry')
        intent = Path(audit['stage_metadata']['path']).with_name('STORAGE_INTENT.json')
        report = intent.with_name('STORAGE_REPORT.json')
        s.absent(intent)
        s.absent(report)
        for entry in entries:
            for p in s.declared_paths(entry):
                if p != entry['raw_path']:
                    s.absent(Path(p))
        # Stable-source hash/archive/reconstruction/retirement stays in storage.py.
        s.write_doc(intent, {'stage_index': index, 'independent_integrity': independent_ref,
                            'stage_metadata': audit['stage_metadata'], 'no_retry_after_intent': True})
        for ref in refs:
            e = present[ref['path']]
            rid = e['run_id']
            s.write_doc(Path(e['acceptance_path']), {'schema': s.SCHEMA, 'kind': 'post-measurement-acceptance',
                       'campaign_id': 'cap96-native216-v1', 'admission_sha256': ready['storage_admission']['sha256'],
                       'raw_path': ref['path'], 'raw_sha256': ref['sha256'], 'raw_bytes': ref['bytes'],
                       'measurement_complete': True, 'outside_headline_measurement': True,
                       'storage_integrity_accepted': True, 'all_offered_statuses_preserved': True,
                       'quality_resource_projections_checked': False,
                       'storage_acceptance_is_not_native_or_quality_acceptance': True,
                       'independent_consumed_offer_integrity': independent_ref,
                       'bindings': dict(e['frozen_bindings'], run_manifest_sha256=metadata['run_manifests'][rid]['sha256'],
                                        offered_ledger_sha256=audit['stage_metadata']['sha256'])})
    operations = []
    for ref in refs:
        e = present[ref['path']]
        s.archive(Q / 'STORAGE_ADMISSION_ALL320.json', Path(e['acceptance_path']), Path(ref['path']), lock_path=LOCK)
        with s.quiet(LOCK):
            _, _, _, manifest, manifest_sha = s.verified_manifest(Q / 'STORAGE_ADMISSION_ALL320.json', Path(ref['path']), LOCK)
        receipt = Path(e['retire_receipt_paths'][0])
        s.retire(Q / 'STORAGE_ADMISSION_ALL320.json', Path(ref['path']), receipt, explicitly_requested=True, lock_path=LOCK)
        operations.append({'raw_path': ref['path'], 'archive_manifest_sha256': manifest_sha,
                           'retirement_receipt': str(receipt)})
    with s.quiet(LOCK):
        w.require(w.identity(s, root / 'status.json')['sha256'] == status['sha256'], 'Terminal status changed')
        for operation in operations:
            w.require(not s.exists(Path(operation['raw_path'])), 'Retired raw unexpectedly present')
            operation['retirement_receipt'] = w.identity(s, Path(operation['retirement_receipt']))
        s.write_doc(report, {'status': 'EXACT_ACCEPTED_PRESENT_RAW_VERIFIED_AND_RETIRED', 'stage_index': index,
                            'independent_integrity': independent_ref, 'stage_metadata': audit['stage_metadata'],
                            'operations': operations, 'advancement_authorized': False,
                            'scientific_completeness': 'PENDING_INDEPENDENT_SOURCE_OUTPUT_REVIEW'})
        return w.identity(s, report)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('record-metadata', 'preserve-stage'))
    p.add_argument('--stage-index', type=int, required=True)
    p.add_argument('--owner-opened-post-stage-quiet-slot', action='store_true')
    p.add_argument('--qualification', required=True)
    p.add_argument('--qualification-sha256', required=True)
    p.add_argument('--independent-integrity')
    p.add_argument('--independent-integrity-sha256')
    p.add_argument('--explicitly-retire-admitted-raw', action='store_true')
    args = p.parse_args()
    if not args.owner_opened_post_stage_quiet_slot:
        raise RuntimeError('Owner quiet slot required before loading/hashing')
    w, s = load_qualified()
    with s.quiet(LOCK):
        receipt = w.bound(s, {'path': args.qualification, 'sha256': args.qualification_sha256,
                              'bytes': Path(args.qualification).stat().st_size})
        w.require(receipt['status'] == 'PASS' and receipt['adapter'] == w.identity(s, Path(__file__).resolve()) and
                  receipt['generic_terminal_sha256'] == GENERIC_SHA and receipt['storage_helper_sha256'] == w.HELPER_SHA,
                  'This exact draft has not been independently qualified')
    if args.action == 'record-metadata':
        result = record_metadata(w, s, args.stage_index)
    else:
        w.require(args.explicitly_retire_admitted_raw and args.independent_integrity and args.independent_integrity_sha256,
                  'Explicit exact retirement and independent receipt identities required')
        ref = {'path': args.independent_integrity, 'sha256': args.independent_integrity_sha256,
               'bytes': Path(args.independent_integrity).stat().st_size}
        result = preserve_stage(w, s, args.stage_index, ref)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
