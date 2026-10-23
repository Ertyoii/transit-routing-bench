#!/usr/bin/env python3
"""Create-only post-stage preservation. Never a router, evaluator, or quality gate.

CLI requires an owner-opened post-stage slot and exact admitted retirement.
Every read/hash/archive/verification/retirement occurs under campaign flock.
A partial intent is a stop requiring inspection, never permission to retry.
"""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time

ROOT = Path('/workspace/shared/sg-coldstart/campaign-v2-20261021')
HELPER = ROOT / 'analysis/lossless-storage-v1/storage.py'
HELPER_SHA = '0efb3a80a2c3b3e90bda34d5a90bfc690d8353f446b51881e7c4e9779588bd22'
READY = ROOT / 'qualification/runtime-finite20-v6-bindings/READY_TO_MEASURE.json'
READY_SHA = 'df73087ae90637ebcdde2b1348b06109f700fa8d751a661cd28d7717d0bc2acb'
WORK = ROOT / 'analysis/lossless-storage-v1/stage-workflow-v2'
LOCK = Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
TERMINAL = {'completed', 'stopped_on_failure', 'cancelled', 'runner_error', 'prelaunch_memory_admission_rejected'}


def require(value, message):
    if not value:
        raise RuntimeError(message)


@contextlib.contextmanager
def bootstrap_quiet(lock):
    """The qualified helper is not imported/hashed until this lock is held."""
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def load_helper(path=HELPER, expected=HELPER_SHA, lock=LOCK):
    with bootstrap_quiet(lock):
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Qualified storage helper changed')
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('qualified_lossless_storage_v1', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def identity(s, path):
    digest, size = s.digest_file(Path(path))
    return {'path': str(path), 'sha256': digest, 'bytes': size}


def bound(s, reference):
    actual = identity(s, Path(reference['path']))
    require(all(actual[k] == reference[k] for k in ('sha256', 'bytes')), 'Changed frozen reference: ' + reference['path'])
    return s.read_doc(Path(reference['path']))[0]


def optional_doc(s, path):
    if not s.exists(path):
        return {'path': str(path), 'state': 'MISSING', 'document': None}
    ref = identity(s, path)
    try:
        doc = s.read_doc(path)[0]
        return dict(ref, state='PRESENT', document=doc)
    except (ValueError, UnicodeError) as exc:
        return dict(ref, state='PRESENT_UNPARSEABLE', document=None, parse_error=str(exc))


def positive_tick_string(value):
    # The unchanged qualified harness emits /proc start ticks as STRINGS.
    # Preserve raw evidence; normalize only after exact, bounded ASCII grammar.
    require(type(value) is str and 1 <= len(value) <= 20 and value[0] in '123456789'
            and all(c in '0123456789' for c in value),
            'Start ticks must be a canonical positive ASCII decimal string')
    parsed = int(value)
    require(parsed <= 18446744073709551615, 'Start ticks exceed unsigned64 domain')
    return parsed


def pid_start(pid):
    try:
        # comm may contain spaces or parentheses; starttime is field22.
        data = Path('/proc') / str(pid) / 'stat'
        return int(data.read_text().rsplit(')', 1)[1].split()[19])
    except FileNotFoundError:
        return None


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def assert_writer_terminal(status, commands):
    require(status.get('state') in TERMINAL, 'Writer status is not terminal')
    require(type(status.get('runner_pid')) is int and status['runner_pid'] > 0, 'Cannot establish runner identity')
    runner_ticks = positive_tick_string(status.get('runner_start_ticks'))
    require(pid_start(status['runner_pid']) != runner_ticks, 'Original runner is still alive')
    for command in commands:
        require(isinstance(command, dict) and all(type(command.get(k)) is int and command[k] > 0
                for k in ('pid','pgid')), 'Started/output-bearing run lacks typed full command process identity')
        require(command['pgid'] == command['pid'], 'Command process-group identity differs from qualified harness')
        command_ticks = positive_tick_string(command.get('process_start_ticks'))
        require(pid_start(command['pid']) != command_ticks, 'Original command process is alive')
        try:
            os.killpg(command['pgid'], 0)
        except ProcessLookupError:
            pass
        else:
            raise RuntimeError('Command process group still exists; writer terminality uncertain')
    return {'status_state': status['state'], 'runner_pid': status['runner_pid'],
            'runner_start_ticks': status['runner_start_ticks'], 'runner_start_ticks_normalized':runner_ticks,
            'original_runner_absent': True,
            'recorded_command_processes_and_groups_absent': True, 'checked_ns': time.time_ns()}


def validate_memory_record(record, rid, offer_index, spec, plan, stage, expected_decision):
    require(isinstance(record,dict) and record.get('schema') == 'observed-memory-admission-record-v1',
            'Missing/unparseable required memory admission record')
    require(record.get('run_id') == rid and type(record.get('offer_index')) is int
            and record['offer_index'] == offer_index and record.get('decision') == expected_decision,
            'Memory admission run/index/decision mismatch')
    require(record.get('plan') == stage['plan'] and record.get('offered_spec_sha256') == canonical_hash(spec),
            'Memory admission exact plan/spec binding mismatch')
    require(record.get('binding') == plan.get('memory_admission'), 'Memory admission wrapper/policy binding mismatch')
    unsigned = dict(record)
    claimed = unsigned.pop('record_sha256',None)
    require(claimed == canonical_hash(unsigned), 'Memory admission record self-hash mismatch')


def success_records(status, plan, records):
    offered = [r['id'] for r in plan['runs']]
    completed = status.get('completed_runs',[])
    if (status.get('state') != 'completed' or status.get('ok') is not True
            or [r.get('id') for r in completed] != offered):
        return False
    for row in completed:
        record = records[row['id']]
        result = record['parsed_result']
        if not (isinstance(result,dict) and result.get('id') == row['id'] and result.get('ok') is True
                and type(result.get('returncode')) is int and result['returncode'] == 0
                and result.get('timed_out') is False and type(row.get('returncode')) is int
                and row.get('ok') is True and row['returncode'] == result['returncode']
                and row.get('timed_out') is result['timed_out']
                and record['command']['state'] == 'PRESENT' and record['memory_admission']['state'] == 'PRESENT'):
            return False
    return True


def validate_stage_coordinates(stage,runtime_stage,index):
    block,segment=divmod(index,4)
    require(type(stage.get('block')) is int and stage['block']==block
            and type(stage.get('segment')) is int and stage['segment']==segment,
            'READY block/segment coordinates differ from exact stage index')
    require(type(runtime_stage.get('block')) is int and runtime_stage['block']==block
            and type(runtime_stage.get('segment')) is int and runtime_stage['segment']==segment,
            'Plan block/segment coordinates differ from exact stage index')
    require(type(runtime_stage.get('global_start_position')) is int
            and runtime_stage['global_start_position']==segment*84,
            'Plan block-relative start position differs from exact segment*84')


def validate_stage_slice(ready,runtime_stage,index):
    rows=runtime_stage['all84_state_rows']
    require(len(rows)==84 and rows==ready['all672_state_rows'][index*84:(index+1)*84],
            'Stage does not preserve exact contiguous84 absolute ledger positions')
    return rows


def stage_context(s, stage_index, ready_path, ready_sha):
    ready, actual_sha = s.read_doc(ready_path)
    require(actual_sha == ready_sha, 'READY receipt changed')
    require(ready.get('runtime_slots') == 672 and len(ready.get('all672_state_rows', [])) == 672
            and len(ready.get('stages', [])) == 8, 'Exact all8/672 closure required')
    require(0 <= stage_index < 8, 'Stage index outside frozen all8 sequence')
    stage = ready['stages'][stage_index]
    plan = bound(s, stage['plan'])
    for key in ('freeze', 'prospective_specs', 'request', 'storage_admission', 'storage_inventory'):
        bound(s, stage[key])
    require(stage['admission_path'] == stage['storage_admission']['path'], 'Admission pointer mismatch')
    require(stage['inventory_path'] == stage['storage_inventory']['path'], 'Inventory pointer mismatch')
    validate_stage_coordinates(stage,plan['runtime_stage'],stage_index)
    rows=validate_stage_slice(ready,plan['runtime_stage'],stage_index)
    offered = [r['id'] for r in rows if r['state'] == 'PLANNED_UNSTARTED']
    refused = [r for r in rows if r['state'] == 'NOT_OFFERED_MEMORY_FORECAST']
    require(len(offered) + len(refused) == 84 and [r['id'] for r in plan['runs']] == offered,
            'Offered plan/order differs from exact84 ledger')
    require(len(offered) == stage['offered_runs'] and len(refused) == stage['unoffered_runs'], 'Stage census changed')
    require(len(set(r['id'] for r in rows)) == 84, 'Duplicate stage IDs')
    admission = s.read_doc(Path(stage['admission_path']))[0]
    request = admission['request']
    require(request == s.read_doc(Path(stage['request']['path']))[0], 'Frozen owner request mismatch')
    root = s.canonical(stage['future_serving_root'])
    require(request['future_serving_root_must_remain_absent_until_admitted'] == str(root), 'Serving root mismatch')
    counts = {'proof-summary': 0, 'proof-sidecar': 0}
    by_run = {rid: [] for rid in offered}
    for entry in request['outputs']:
        rid = entry.get('run_id')
        require(rid in by_run and entry['role'] in counts, 'Unknown run/role in raw allowlist')
        name = 'summary.json' if entry['role'] == 'proof-summary' else 'sparse-full-preparation.json'
        require(entry['raw_path'] == str(root / rid / 'artifact' / name), 'Nonexact raw artifact path')
        require(entry['frozen_bindings']['plan_sha256'] == stage['plan']['sha256'], 'Plan ancestry mismatch')
        if entry['role'] == 'proof-sidecar':
            require('-ultra-subset-local-walk-ties-' in rid and '-old-native-' not in rid,
                    'Only admitted SourceB subset sidecars are eligible')
        require(entry.get('allow_raw_retirement') is True and entry.get('retire_receipt_paths'), 'No admitted retirement')
        expected_receipt = Path(entry['raw_path']).with_name(name[:-5] + '.retirement-after-stage.json')
        require(entry['retire_receipt_paths'][0] == str(expected_receipt), 'Wrong admitted stage retirement receipt')
        counts[entry['role']] += 1
        by_run[rid].append(entry)
    require(counts == {'proof-summary': stage['raw_summary_paths'], 'proof-sidecar': stage['raw_full_proof_sidecar_paths']},
            'Raw allowlist census changed')
    require(all(sum(e['role'] == 'proof-summary' for e in entries) == 1 for entries in by_run.values()),
            'Every offered run needs exactly one admitted summary')
    inventory = s.read_doc(Path(stage['inventory_path']))[0]
    return ready, stage, plan, admission, inventory, root, by_run


def terminal_metadata(s, index, ready, stage, plan, root, by_run):
    status_ref = optional_doc(s, root / 'status.json')
    status = status_ref['document']
    require(isinstance(status, dict), 'Missing/unparseable writer status')
    require(status.get('plan_sha256') == stage['plan']['sha256'] and status.get('out_dir') == str(root), 'Status plan/root mismatch')
    require(status.get('total_runs') == len(plan['runs']), 'Status run count mismatch')
    require(identity(s, root / 'plan.json')['sha256'] == stage['plan']['sha256'], 'Actual runner plan differs from frozen plan')
    status_rows = {r['id']: r for r in status.get('completed_runs', [])}
    require(len(status_rows) == len(status.get('completed_runs', [])) and set(status_rows) <= set(by_run), 'Bad completed ledger')
    rejected = {r['id']: r for r in status.get('rejected_offers', [])}
    unstarted = {r['id']: r for r in status.get('unstarted_offers', [])}
    specs = {r['id']: r for r in plan['runs']}
    observations = {}
    started_commands = []
    # Establish full recorded writer terminality BEFORE any raw-byte digest.
    assert_writer_terminal(status, [])
    for offer_index, spec in enumerate(plan['runs']):
        rid = spec['id']
        command = optional_doc(s, root / rid / 'command.json')
        result = optional_doc(s, root / rid / 'result.json')
        memory = optional_doc(s, root / rid / 'memory-admission.json')
        has_raw = any(s.exists(Path(e['raw_path'])) for e in by_run[rid])
        rd = result['document']
        explicitly_rejected = (isinstance(rd,dict) and rd.get('outcome') == 'prelaunch_memory_admission_rejected'
                               and rd.get('execution_performed') is False)
        if explicitly_rejected:
            require(command['state'] == 'MISSING' and not has_raw, 'Rejected nonexecuted offer has command/raw output')
            validate_memory_record(memory['document'],rid,offer_index,spec,plan,stage,'rejected')
        elif command['state'] != 'MISSING' or result['state'] != 'MISSING' or memory['state'] != 'MISSING' or has_raw:
            require(command['state'] == 'PRESENT', 'Started/output-bearing run missing/unparseable required command')
            started_commands.append(command['document'])
            validate_memory_record(memory['document'],rid,offer_index,spec,plan,stage,'admitted')
        observations[rid] = (command,result,memory)
    terminal = assert_writer_terminal(status,started_commands)
    return status_ref, terminal, observations


def collect(s, index, ready, stage, plan, admission, inventory, root, by_run):
    status_ref, terminal, observations = terminal_metadata(s,index,ready,stage,plan,root,by_run)
    status = status_ref['document']
    status_rows = {r['id']:r for r in status.get('completed_runs',[])}
    rejected = {r['id']:r for r in status.get('rejected_offers',[])}
    unstarted = {r['id']:r for r in status.get('unstarted_offers',[])}
    specs = {r['id']:r for r in plan['runs']}
    records, ledger = {}, []
    for position, initial in enumerate(plan['runtime_stage']['all84_state_rows']):
        rid = initial['id']
        row = {'id': rid, 'global_position': index * 84 + position, 'initial_state_row': initial}
        if rid not in by_run:
            require(not s.exists(root / rid), 'Forecast-refused run unexpectedly has an output directory')
            row.update(state=initial['state'], result=None, admitted_raw_files=[])
            ledger.append(row)
            continue
        command, result, memory = observations[rid]
        raw = []
        for entry in by_run[rid]:
            p = Path(entry['raw_path'])
            if s.exists(p):
                with s.regular_reader(p) as (_, before):
                    s.new_raw(p, admission, inventory, before)
                raw.append(dict(identity(s, p), state='PRESENT'))
            else:
                raw.append({'path': str(p), 'state': 'MISSING'})
        result_doc = result['document']
        if isinstance(result_doc, dict):
            require(result_doc.get('id') == rid, 'Actual result ID mismatch')
        state = ('RESULT_RECORDED' if isinstance(result_doc, dict) else
                 'UNKNOWN_UNPARSEABLE_RESULT' if result['state'] == 'PRESENT_UNPARSEABLE' else
                 'UNKNOWN_MISSING_RESULT' if command['state'] != 'MISSING' or any(r['state'] == 'PRESENT' for r in raw) else
                 'UNSTARTED_AFTER_TERMINAL_STAGE')
        row.update(state=state, result={k: v for k, v in result.items() if k != 'document'},
                   actual_result_fields={k: result_doc.get(k) for k in ('ok','outcome','returncode','termination','timed_out','execution_performed')}
                   if isinstance(result_doc, dict) else None,
                   completed_status_entry=status_rows.get(rid), rejected_status_entry=rejected.get(rid),
                   unstarted_status_entry=unstarted.get(rid), admitted_raw_files=raw)
        records[rid] = {'schema': 'runtime-stage-actual-run-manifest-v1', 'id': rid,
                        'global_position': row['global_position'], 'frozen_stage_plan': stage['plan'],
                        'offered_spec': specs[rid], 'command': {k: v for k, v in command.items() if k != 'document'},
                        'result': {k: v for k, v in result.items() if k != 'document'},
                        'memory_admission': {k: v for k, v in memory.items() if k != 'document'},
                        'status': {k: v for k, v in status_ref.items() if k != 'document'},
                        'observed_state': state, 'actual_result_fields': row['actual_result_fields'], 'parsed_result':result_doc}
        ledger.append(row)
    require([r['id'] for r in ledger] == [r['id'] for r in plan['runtime_stage']['all84_state_rows']], 'Ledger loss')
    return status_ref, terminal, records, ledger


def validate_prior_ancestry(report,old_ledger,old_global,prior,ready,ready_ref):
    pstage = ready['stages'][prior]
    require(report.get('status') == 'ALL_PRESENT_ADMITTED_RAW_VERIFIED_AND_RETIRED'
            and report.get('terminal_stage_success') is True, 'Prior stage terminal success/storage incomplete')
    require(report.get('stage_index') == prior and report.get('ready_receipt') == ready_ref
            and report.get('plan') == pstage['plan'] and report.get('admission') == pstage['storage_admission'],
            'Prior report READY/plan/admission ancestry mismatch')
    require(old_ledger.get('ready_receipt') == ready_ref and old_ledger.get('plan') == pstage['plan']
            and old_ledger.get('stage_index') == prior and len(old_ledger.get('rows',[])) == 84,
            'Prior ledger closure ancestry mismatch')
    expected = ready['all672_state_rows'][prior*84:(prior+1)*84]
    require([r['initial_state_row'] for r in old_ledger['rows']] == expected
            and [r['global_position'] for r in old_ledger['rows']] == list(range(prior*84,(prior+1)*84))
            and [r['id'] for r in old_ledger['rows']] == [r['id'] for r in expected],
            'Prior ledger exact global-position ancestry mismatch')
    require(old_global.get('ready_receipt') == ready_ref and old_global.get('through_stage_index') == prior
            and len(old_global.get('rows',[])) == 672 and old_global['rows'][prior*84:(prior+1)*84] == old_ledger['rows']
            and [r['id'] for r in old_global['rows']] == [r['id'] for r in ready['all672_state_rows']],
            'Prior global672 snapshot ancestry mismatch')


def preserve(s, index, ready_path=READY, ready_sha=READY_SHA, work=WORK, lock=LOCK):
    stage_work = None
    created_work = False
    try:
        with s.quiet(lock):
            ready, stage, plan, admission, inventory, root, by_run = stage_context(s, index, ready_path, ready_sha)
            stage_work = work / ('b%d-s%d' % (stage['block'], stage['segment']))
            s.absent(stage_work)
            status_ref, terminal, records, rows = collect(s, index, ready, stage, plan, admission, inventory, root, by_run)
            # Fail before intent if ANY admitted destination has an uncertain prior operation.
            for entries in by_run.values():
                for entry in entries:
                    for p in s.declared_paths(entry):
                        if p != entry['raw_path']:
                            s.absent(Path(p))
            stage_work.mkdir()
            created_work = True
            (stage_work / 'RUN_MANIFESTS').mkdir()
            s.write_doc(stage_work / 'STAGE_INTENT.json', {'schema':'runtime-stage-storage-intent-v1',
                        'stage_index':index, 'ready_receipt':identity(s, ready_path), 'admission':stage['storage_admission'],
                        'writer_terminal':terminal, 'no_retry_after_intent':True, 'created_ns':time.time_ns()})
            manifest_refs = {}
            for rid, record in records.items():
                p = stage_work / 'RUN_MANIFESTS' / (rid + '.json')
                s.write_doc(p, dict({k:v for k,v in record.items() if k != 'parsed_result'}, writer_terminal=terminal))
                manifest_refs[rid] = identity(s, p)
            ledger_path = stage_work / 'OFFERED_LEDGER.json'
            s.write_doc(ledger_path, {'schema':'runtime-stage-all84-offered-ledger-v1', 'stage_index':index,
                        'ready_receipt':identity(s, ready_path), 'plan':stage['plan'],
                        'terminal_status':{k:v for k,v in status_ref.items() if k != 'document'},
                        'writer_terminal':terminal, 'rows':rows})
            ledger_ref = identity(s, ledger_path)
            # These are the already-frozen RESOURCE_FORECAST assumptions, not
            # a measured maximum or a new scientific/source policy. Preserve
            # oversized bytes equally, but never continue launching silently.
            forecast_exceedances = []
            for row in rows:
                if row['id'] not in by_run:
                    continue
                allowance = 120_000_000 if 'ultra-subset-' in row['id'] else 8_000_000
                actual = sum(r.get('bytes',0) for r in row['admitted_raw_files'])
                if actual > allowance:
                    forecast_exceedances.append({'id':row['id'], 'admitted_raw_bytes':actual,
                                                 'frozen_assumption_raw_bytes_per_run':allowance})
            global_rows = [{'id':r['id'], 'global_position':i, 'initial_state_row':r, 'state':r['state']}
                           for i,r in enumerate(ready['all672_state_rows'])]
            prior_refs = []
            for prior in range(index):
                pstage = ready['stages'][prior]
                p = work / ('b%d-s%d' % (pstage['block'],pstage['segment'])) / 'STAGE_STORAGE_REPORT.json'
                report = s.read_doc(p)[0]
                require(report.get('terminal_stage_success') is True, 'Prior stage terminal success/storage incomplete')
                old_ledger = bound(s, report['offered_ledger'])
                old_global = bound(s, report['global_ledger_snapshot'])
                validate_prior_ancestry(report,old_ledger,old_global,prior,ready,identity(s,ready_path))
                global_rows[prior*84:(prior+1)*84] = old_ledger['rows']
                prior_refs.append(identity(s,p))
            global_rows[index*84:(index+1)*84] = rows
            require(len(global_rows) == 672 and [r['id'] for r in global_rows] == [r['id'] for r in ready['all672_state_rows']], 'Global672 ledger loss')
            global_path = stage_work / 'GLOBAL_LEDGER_SNAPSHOT.json'
            s.write_doc(global_path, {'schema':'runtime-all672-offered-ledger-snapshot-v1', 'through_stage_index':index,
                        'ready_receipt':identity(s,ready_path), 'prior_stage_reports':prior_refs, 'rows':global_rows})
            global_ref = identity(s,global_path)
            present = []
            missing = []
            for row in rows:
                for raw_ref in row.get('admitted_raw_files', []):
                    if raw_ref['state'] == 'MISSING':
                        missing.append({'id':row['id'], **raw_ref, 'observed_run_state':row['state']})
                        continue
                    entry = next(e for e in by_run[row['id']] if e['raw_path'] == raw_ref['path'])
                    acceptance = {'schema':s.SCHEMA, 'kind':'post-measurement-acceptance', 'campaign_id':admission['campaign_id'],
                        'admission_sha256':stage['storage_admission']['sha256'], 'raw_path':entry['raw_path'],
                        'raw_sha256':raw_ref['sha256'], 'raw_bytes':raw_ref['bytes'], 'measurement_complete':True,
                        'outside_headline_measurement':True, 'storage_integrity_accepted':True,
                        'storage_acceptance_is_not_native_or_quality_acceptance':True,
                        'content_outcome_state':row['state'], 'actual_result_fields':row['actual_result_fields'],
                        'all_offered_statuses_preserved':True, 'quality_resource_projections_checked':False,
                        'writer_terminal':terminal, 'run_manifest':manifest_refs[row['id']], 'offered_ledger':ledger_ref,
                        'global_ledger_snapshot':global_ref, 'bindings':dict(entry['frozen_bindings'],
                            run_manifest_sha256=manifest_refs[row['id']]['sha256'], offered_ledger_sha256=ledger_ref['sha256'],
                            ready_receipt_sha256=ready_sha, terminal_status_sha256=status_ref['sha256'], global_ledger_sha256=global_ref['sha256'])}
                    s.write_doc(Path(entry['acceptance_path']), acceptance)
                    present.append(entry)
        operations = []
        for entry in present:
            # Each unchanged operation acquires the same lock itself. No I/O/hash
            # is performed between these lock-protected qualified operations.
            s.archive(Path(stage['admission_path']), Path(entry['acceptance_path']), Path(entry['raw_path']), lock_path=lock)
            with s.quiet(lock):
                _, _, _, manifest, manifest_sha = s.verified_manifest(Path(stage['admission_path']), Path(entry['raw_path']), lock)
                verified = {'manifest_sha256':manifest_sha, 'raw_sha256':manifest['raw_sha256'], 'raw_bytes':manifest['raw_bytes']}
            receipt = Path(entry['retire_receipt_paths'][0])
            s.retire(Path(stage['admission_path']), Path(entry['raw_path']), receipt,
                     explicitly_requested=True, lock_path=lock)
            operations.append({'raw_path':entry['raw_path'], 'independent_verify':verified, 'retirement_receipt':str(receipt)})
        with s.quiet(lock):
            final_status = identity(s, root / 'status.json')
            require(final_status['sha256'] == status_ref['sha256'], 'Writer status changed during storage')
            for op in operations:
                require(not s.exists(Path(op['raw_path'])), 'Raw unexpectedly remains after retirement')
                op['retirement_receipt'] = identity(s, Path(op['retirement_receipt']))
            status = status_ref['document']
            terminal_success = success_records(status,plan,records) and not missing and not forecast_exceedances
            report = {'schema':'runtime-stage-storage-report-v1', 'status':'ALL_PRESENT_ADMITTED_RAW_VERIFIED_AND_RETIRED',
                        'stage_index':index, 'ready_receipt':identity(s,ready_path), 'admission':stage['storage_admission'],
                        'plan':stage['plan'], 'terminal_status':{k:v for k,v in status_ref.items() if k != 'document'},
                        'offered_ledger':ledger_ref, 'global_ledger_snapshot':global_ref, 'writer_terminal':terminal,
                        'terminal_stage_success':terminal_success, 'offers':len(plan['runs']), 'ledger_positions':84,
                        'present_artifacts_preserved':len(operations), 'missing_artifacts':missing,
                        'raw_forecast_exceedances':forecast_exceedances, 'operations':operations,
                        'storage_acceptance_is_not_native_or_quality_acceptance':True, 'finished_ns':time.time_ns()}
            s.write_doc(stage_work / 'STAGE_STORAGE_REPORT.json',report)
            return report
    except BaseException as exc:
        if created_work:
            try:
                with s.quiet(lock):
                    s.write_doc(stage_work / 'STOP_INSPECT_DO_NOT_RETRY.json', {'status':'STOP_INSPECT_DO_NOT_RETRY',
                                'error_type':type(exc).__name__, 'error':str(exc), 'uncertain_intents_must_be_inspected':True})
            except BaseException:
                pass
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage-index',type=int,required=True)
    p.add_argument('--owner-opened-post-stage-quiet-slot',action='store_true')
    p.add_argument('--explicitly-retire-admitted-raw',action='store_true')
    args = p.parse_args()
    require(args.owner_opened_post_stage_quiet_slot and args.explicitly_retire_admitted_raw,
            'Owner quiet-slot and exact admitted recoverable retirement authorization required')
    result = preserve(load_helper(), args.stage_index)
    print(json.dumps({'status':result['status'], 'stage_index':args.stage_index,
                      'terminal_stage_success':result['terminal_stage_success'],
                      'present_artifacts_preserved':result['present_artifacts_preserved'],
                      'missing_artifacts':len(result['missing_artifacts'])}, sort_keys=True),flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError) as exc:
        print(json.dumps({'status':'STOP_INSPECT_DO_NOT_RETRY','error_type':type(exc).__name__,'error':str(exc)}),file=sys.stderr)
        sys.exit(2)
