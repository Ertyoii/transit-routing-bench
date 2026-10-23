#!/usr/bin/env python3
"""DRAFT: create-only ALL8/window operational consumer of UNCHANGED FINALV4.

Not an evaluator, reference generator, quality acceptance or policy selector.
All actual modes require later independent qualification + owner quiet slot.
No route/model/evaluator import occurs in this module. Runtime evaluation uses
one unchanged subprocess per exact model/window, while holding campaign.lock.
"""
import argparse
import collections
import contextlib
import copy
import fcntl
import glob
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path('/workspace/shared/sg-coldstart/campaign-v2-20261021')
LOCK=Path('/workspace/shared/sg-coldstart/setup/campaign.lock')
STORAGE=ROOT/'analysis/lossless-storage-v1/storage.py'
STORAGE_SHA='0efb3a80a2c3b3e90bda34d5a90bfc690d8353f446b51881e7c4e9779588bd22'
READY_SHA='df73087ae90637ebcdde2b1348b06109f700fa8d751a661cd28d7717d0bc2acb'
V4_SHA='b75ff1d989896d411fa33d39f70ccc995a2af25f5b2d598c23fa0004c1dc37b0'
ANCESTRY_SHA='2603ef345f56a311477097e540ca1eae8d254ad512518f67642e8b0aa8733f7c'
RUNTIME_CODE_ROOT=ROOT/'analysis/lossless-storage-v1/stage-workflow-v3'
RUNTIME_STATE_ROOT=ROOT/'analysis/lossless-storage-v1/stage-workflow-v2'
RUNTIME_V3_POST_SHA='6174a8efed3f727da4302a8263dae271c0d6f74cf2d013e1857a5f270b36459e'
RUNTIME_V3_QUAL_SHA='5a364202a5d1be5ed519cad7dafcfd99217f57fafb45032b40af5c32cd98762f'
RUNTIME_V3_CONDUCTOR_SHA='20e68df22bb28f8fe605f0deeb5a15cb4a3b449b91dd454c2b03fcc9fbd566ab'
RUNTIME_V3_ACCEPTANCE_PATH=ROOT.parent/'campaign-v2-audit-20261021/STAGE_WORKFLOW_INDEPENDENT_ACCEPTANCE_V3.json'
RUNTIME_V3_ACCEPTANCE_SHA='58f62a0a6365e4c30cca657cb14855af135f915a6db4f18091a3991785cae168'
RUNTIME_ALL8_ACCEPTANCE_SHA='2faf48a53fd07368b81a035f9fa9df8be827d5ac61ee57a0c896fbdd2e2de32f'
RUNTIME_ACTUAL_SOURCE_SHA='1cd06a6d398146484053be997857ddcc83d0c18a0f4fa2e55ac3a821b6875887'
WINDOWS=tuple('weekday-'+name+'-20261020' for name in ('morning','midday','evening','overnight'))
OUTPUT_NAMES=('CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl','METRICS_BY_RUN.json','QUALITY_ROWS.jsonl',
 'ORACLE_COMPARISONS.json','FEASIBLE_REFERENCE_IMPORT.json','FEASIBLE_REFERENCE_PROVENANCE.json',
 'QUALITY_AGGREGATE.json','INDEPENDENT_ORACLE_SLOTS.json','NATIVE_COUNTEREXAMPLES.json','VALIDATION_ERRORS.json','REPORT.json')
DOWNSTREAM=('REPORT.json','METRICS_BY_RUN.json','QUALITY_ROWS.jsonl','QUALITY_AGGREGATE.json','ORACLE_COMPARISONS.json')

class Stop(RuntimeError):
    pass

def need(ok,message):
    if not ok: raise Stop(message)

def encoded(obj):
    return (json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()

def semantic(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)

def canonical_hash(obj):
    return hashlib.sha256(semantic(obj).encode()).hexdigest()

def flag(argv,name):
    need(argv.count(name)==1,'Missing/ambiguous frozen argv flag '+name)
    index=argv.index(name)
    need(index+1<len(argv),'Missing frozen argv value '+name)
    return argv[index+1]

@contextlib.contextmanager
def bootstrap_quiet(lock=LOCK):
    fd=os.open(lock,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally: os.close(fd)

def load_storage():
    with bootstrap_quiet():
        data=STORAGE.read_bytes()
        need(hashlib.sha256(data).hexdigest()==STORAGE_SHA,'Qualified storage.py changed')
        # Execute exactly the just-hashed source, not an unchecked bytecode cache.
        namespace={'__name__':'qualified_lossless_storage','__file__':str(STORAGE)}
        exec(compile(data,str(STORAGE),'exec'),namespace)
        return type('QualifiedStorage',(),namespace)

def ident(s,path):
    sha,size=s.digest_file(Path(path))
    return {'path':str(path),'sha256':sha,'bytes':size}

def bound(s,ref):
    actual=ident(s,Path(ref['path']))
    need(actual==ref,'Changed exact reference '+ref['path'])
    return s.read_doc(Path(ref['path']))[0]

def exact_path(value):
    p=Path(value)
    need(p.is_absolute() and str(p)==os.path.abspath(str(p)),'Noncanonical lexical absolute path')
    return p

def child(root,path):
    p=exact_path(path)
    need(root in p.parents,'Future path outside exact bundle')
    return p


def derive_plan(parent,selected_ids,original_campaign,registry_path):
    """Only stable run-subsequence, absolute ORIGINAL registry and provenance."""
    selected=set(selected_ids)
    need(len(selected)==len(selected_ids),'Duplicate selected metric ID')
    source=[r for r in parent['runs'] if r['id'] in selected]
    need([r['id'] for r in source]==selected_ids,'Selection is not exact frozen stable subsequence')
    derived=copy.deepcopy(parent)
    derived['runs']=copy.deepcopy(source)
    if parent.get('workload_registry') is not None:
        need(isinstance(parent['workload_registry'],dict),'Unsupported registry schema')
        derived['workload_registry']=copy.deepcopy(parent['workload_registry'])
        derived['workload_registry']['path']=str(registry_path)
    derived['consumer_view']={'schema':'sg-runtime8-derived-input-view-v1','purpose':'NONEXECUTABLE_CONSUMER_ONLY',
        'original_campaign':str(original_campaign),'original_run_indexes':[i for i,r in enumerate(parent['runs']) if r['id'] in selected],
        'selected_original_ids':selected_ids,'original_plan_value_sha256':canonical_hash(parent)}
    equivalent(parent,derived,selected_ids,registry_path)
    return derived


def equivalent(parent,derived,selected_ids,registry_path):
    need(derived['runs']==[r for r in parent['runs'] if r['id'] in set(selected_ids)],'Derived run objects/argv/config changed')
    need([r['id'] for r in derived['runs']]==selected_ids,'Derived order changed')
    for key,value in parent.items():
        if key not in ('runs','workload_registry','consumer_view'):
            need(derived.get(key)==value,'Derived top-level ancestry changed '+key)
    need(set(derived)==set(parent)|{'consumer_view'},'Unexpected derived top-level fields')
    if parent.get('workload_registry') is not None:
        expected=dict(parent['workload_registry'],path=str(registry_path))
        need(derived['workload_registry']==expected,'Registry identity changed beyond lexical absolute path')
    return True


def partition(ready,plans,specs,ledgers,requests,window_defs):
    """Pure ALL8/672 proof, including ledger-only refusal membership from specs."""
    need(len(plans)==len(specs)==len(ledgers)==len(requests)==8,'Need all8 parent inputs')
    need(ready.get('runtime_slots')==672 and len(ready['all672_state_rows'])==672,'Global672 READY required')
    need(set(window_defs)==set(WINDOWS),'Exact four original windows required')
    groups={w:{'runs':[],'rows':[],'parents':[]} for w in WINDOWS}
    all_run_ids=[];all_row_ids=[]
    for index,(plan,spec,ledger,request) in enumerate(zip(plans,specs,ledgers,requests)):
        initial=ready['all672_state_rows'][84*index:84*(index+1)]
        block,segment=divmod(index,4)
        metadata=plan['runtime_stage']
        need(type(metadata.get('block'))is int and metadata['block']==block
             and type(metadata.get('segment'))is int and metadata['segment']==segment
             and type(metadata.get('global_start_position'))is int and metadata['global_start_position']==84*segment
             and metadata['all84_state_rows']==initial,'Frozen block-relative plan/absolute global order mismatch')
        need(len(ledger['rows'])==84 and [r['initial_state_row'] for r in ledger['rows']]==initial
             and [r['global_position'] for r in ledger['rows']]==list(range(84*index,84*(index+1))),
             'Observed ledger does not preserve exact84 positions')
        need([r['id'] for r in ledger['rows']]==[r['id'] for r in initial],'Ledger IDs changed')
        specmap={r['id']:r for r in spec['run_specs']}
        need(len(specmap)==84 and set(specmap)=={r['id'] for r in initial},'Full84 prospective specs required for refusals')
        offered=[r['id'] for r in initial if r['state']=='PLANNED_UNSTARTED']
        need([r['id'] for r in plan['runs']]==offered,'No adding/dropping/reordering offered runtime runs')
        rawmap={e['run_id']:e for e in request['outputs'] if e['role']=='proof-summary'}
        need(set(rawmap)==set(offered),'Exact summary admission per offered run required')
        runmap={r['id']:r for r in plan['runs']}
        for row,origin in zip(ledger['rows'],initial):
            rid=row['id'];need(Path(rid).name==rid and rid not in ('.','..'),'Unsafe original run ID')
            frozen=specmap[rid];window=frozen['window']
            need(window in groups,'Unknown exact window field')
            definition=window_defs[window]
            need(flag(frozen['argv'],'-dataset')==definition['dataset']['path'],'Frozen dataset lexical alias mismatch')
            groups[window]['rows'].append(copy.deepcopy(row));all_row_ids.append(rid)
            if rid in runmap:
                run=runmap[rid]
                need(run['window']==window and flag(run['argv'],'-dataset')==definition['dataset']['path'],
                     'Run/spec window or lexical dataset mismatch')
                need(rawmap[rid]['frozen_bindings']['dataset_sha256']==definition['dataset']['sha256'],'Exact model hash differs from storage ancestry')
                for name in ('-dataset','-queries','-preference-scenarios'):
                    exact_path(flag(run['argv'],name))
                groups[window]['runs'].append({'id':rid,'stage_index':index,'run':copy.deepcopy(run),'summary_entry':rawmap[rid],
                    'original_campaign':ready['stages'][index]['future_serving_root'],'global_position':row['global_position']})
                all_run_ids.append(rid)
            else:
                need(origin['state']=='NOT_OFFERED_MEMORY_FORECAST','Nonrun ledger row is not an explicit forecast refusal')
                need(row['state']=='NOT_OFFERED_MEMORY_FORECAST','Forecast refusal observation was rewritten')
        for window in WINDOWS:
            ids=[r['id'] for r in plan['runs'] if r['window']==window]
            groups[window]['parents'].append({'stage_index':index,'selected_ids':ids})
    need(len(all_run_ids)==len(set(all_run_ids))==640,'Exact unique640 runtime metric IDs required')
    need(len(all_row_ids)==len(set(all_row_ids))==672,'Exact unique672 ledger IDs required')
    need(set(all_row_ids)=={r['id'] for r in ready['all672_state_rows']},'Global672 membership changed')
    for window,g in groups.items():
        need(len(g['runs'])==160 and len(g['rows'])==168,'Window requires all160 offered+8refusals')
        need(sum(r['state']=='NOT_OFFERED_MEMORY_FORECAST' for r in g['rows'])==8,'Window forecast-refusal denominator changed')
        need([p['stage_index'] for p in g['parents']]==list(range(8)),'Stage-local closure forbidden')
    return groups


def scalar_census(s,sources,weights):
    """Original headers + frozen workloads, never invented scalar_result rows."""
    need(isinstance(weights,list) and len(weights)==9,'Frozen scalar9 required')
    slots=[];seen=set();headers={}
    for source in sources:
        path=Path(source['file']['path'])
        need(path.is_file(),'Required entire original scalar file/header missing; unchanged V4 cannot expand it')
        need(ident(s,path)==source['file'],'Original scalar file identity changed')
        workload=bound(s,source['workload'])
        need(workload.get('dataset_sha256')==source['dataset_sha256'],'Scalar frozen workload/model mismatch')
        with s.regular_reader(path) as (file,_):
            first=file.readline()
            need(bool(first),'Entire scalar metadata header absent')
            header=json.loads(first)
            need(header.get('kind')=='metadata' and header.get('dataset_sha256')==source['dataset_sha256']
                 and header.get('workload_sha256')==source['workload']['sha256']
                 and header.get('weights_sha256')==source['weights_sha256'],'Scalar header/request/weights binding changed')
            emitted={}
            expected_queries={x['query']['id']:x['query'] for x in workload['items']}
            for line in file:
                z=json.loads(line)
                if z.get('kind')!='scalar_result': continue
                wi=z.get('weight_index');q=z['query']
                need(type(wi)is int and 0<=wi<9 and z.get('weight')==weights[wi]
                     and expected_queries.get(q['id'])==q,'Scalar emitted request/weight changed')
                key=(q['id'],wi)
                need(key not in emitted,'Duplicate scalar semantic slot')
                emitted[key]=z
        headers[str(path)]=header
        for item in workload['items']:
            q=item['query']
            for wi,weight in enumerate(weights):
                key=(source['dataset_sha256'],source['workload']['sha256'],source['weights_sha256'],q['id'],wi)
                need(key not in seen,'Duplicate scalar semantic slot across files');seen.add(key)
                original=emitted.get((q['id'],wi))
                slots.append({'key':list(key),'weight':weight,'source':str(path),'query':q,
                    'state':'PRESENT_ORIGINAL_SCALAR_RESULT' if original is not None else 'UNRESOLVED_MISSING_ORIGINAL_ROW',
                    'original_result':original})
    need(len(slots)==432,'Original scalar Cartesian denominator must remain432')
    return {'schema':'sg-runtime8-original-scalar432-census-v1','slots':slots,'headers':headers}


def scalar_partition(census,window_defs):
    parts={window:[slot for slot in census['slots'] if slot['key'][0]==definition['dataset']['sha256']]
           for window,definition in window_defs.items()}
    keys=[tuple(slot['key']) for group in parts.values() for slot in group]
    need(len(keys)==len(set(keys))==432 and set(keys)=={tuple(s['key']) for s in census['slots']},
         'Four scalar partitions are not disjoint/exhaustive original432')
    #108 follows the frozen original request, never success/emitted-row count.
    need(all(len(group)==108 for group in parts.values()),'Original request does not bind expected108 slots per exact window')
    return parts


def check_scalar_output(rows,expected_slots,headers,weights):
    expected_by_key={tuple(s['key']):s for s in expected_slots};expected=set(expected_by_key);actual=[]
    for row in rows:
        source=row['source'];need(source in headers,'Unexpected scalar source')
        matches=[i for i,w in enumerate(weights) if row.get('weight')==w]
        need(len(matches)==1,'Ambiguous/nonfrozen scalar weight')
        header=headers[source]
        key=(row['dataset_sha256'],header['workload_sha256'],header['weights_sha256'],row['query_id'],matches[0])
        actual.append(key)
        need(type(row.get('complete'))is bool and type(row.get('found'))is bool,'Scalar output unknowns cannot be coerced')
        need(key in expected_by_key,'Unexpected scalar semantic slot')
        original=expected_by_key[key].get('original_result')
        if original is None:
            need(row['complete'] is False and row['found'] is False
                 and row.get('error')=='unresolved_missing_oracle_output','Originally missing scalar slot was promoted or relabeled')
        else:
            result=original['result']
            need(row['found'] is result.get('found',False) and (result.get('complete',False) is True or row['complete'] is False),
                 'Original scalar unknown/incomplete status was promoted')

    need(len(actual)==len(set(actual))==len(expected) and set(actual)==expected,'V4 silently lost/duplicated original scalar Cartesian slots')
    return True


def native_census(rows):
    need(len(rows)==960,'Native global denominator is960 offered rows, not witness occurrences')
    counts=collections.Counter();statuses=collections.defaultdict(collections.Counter);completion=collections.Counter();missing=collections.Counter();seen=set()
    for row in rows:
        key=(row['dataset_sha256'],row['campaign'],row['run_id']);qid=row['query']['id']
        need((key,qid)not in seen,'Duplicate native offered source/query');seen.add((key,qid));counts[key]+=1;statuses[key][row['status']]+=1
        need(type(row.get('native_complete'))is bool and type(row.get('native_row_present'))is bool,'Native original presence/completion booleans required')
        completion[key]+=row['native_complete'];missing[key]+=not row['native_row_present']
    return {'counts':counts,'statuses':statuses,'completion':completion,'missing':missing,'offered_rows':960}


def check_native_import(summary,expected,current_dataset):
    need(summary.get('offered_native_reference_rows')==960 and summary.get('offered_serving_rows_added')==0
         and summary.get('completed_serving_rows_added')==0 and summary.get('scalar_slots_added')==0,'Native refs changed denominator or became serving/scalar rows')
    actual={};statuses={}
    for source in summary['source_denominators']:
        key=(source['dataset_sha256'],source['campaign'],source['run_id'])
        need(key not in actual,'Duplicate native source denominator');actual[key]=source['offered_rows']
        statuses[key]=source['independent_materialization_statuses_source_audit_asserted']
        need(source['source_native_complete_rows']==expected['completion'][key]
             and source['source_unknown_or_incomplete_rows']==expected['counts'][key]-expected['completion'][key]
             and source['source_missing_rows']==expected['missing'][key],'Native original unknown/missing/completion counts changed')
        if key[0]!=current_dataset:
            need(source['native_presence_and_completion_rechecked_from_pass'] is False,
                 'Nonrecipient model native statuses falsely promoted to current rechecks')
    need(actual==dict(expected['counts']) and sum(actual.values())==960,'Lost global native960 source provenance')
    need(statuses=={key:dict(value) for key,value in expected['statuses'].items()},'Native audit statuses were filtered/rewritten')
    return True


def iter_array(path):
    """Strict one-record reader: linear boundary scan, one JSON decode/record."""
    import re
    decoder=json.JSONDecoder();tokens=re.compile(r'["\\{}\[\]]')
    with Path(path).open() as file:
        chunk='';position=0;offset=0
        def next_nonspace():
            nonlocal chunk,position,offset
            while True:
                while position<len(chunk) and chunk[position].isspace():position+=1
                if position<len(chunk):return chunk[position]
                offset+=len(chunk);chunk=file.read(65536);position=0
                need(bool(chunk),'Truncated metrics JSON array')
        need(next_nonspace()=='[','Metrics must be JSON array');position+=1
        if next_nonspace()!=']':
            while True:
                need(next_nonspace()=='{','Metric element must be an object')
                pieces=[];stack=[];quoted=False;escaped_at=None;start=position
                while True:
                    closed=False
                    for match in tokens.finditer(chunk,position):
                        token=match.group();absolute=offset+match.start()
                        if quoted:
                            if escaped_at is not None:
                                if absolute==escaped_at:
                                    escaped_at=None;continue
                                if absolute>escaped_at:escaped_at=None
                            if token=='\\':escaped_at=absolute+1
                            elif token=='"':quoted=False
                        elif token=='"':quoted=True
                        elif token in '{[':stack.append('}' if token=='{' else ']')
                        elif token in '}]':
                            need(bool(stack) and stack.pop()==token,'Mismatched metrics JSON nesting')
                            if not stack:
                                position=match.end();pieces.append(chunk[start:position]);closed=True;break
                    if closed:break
                    pieces.append(chunk[start:]);offset+=len(chunk);chunk=file.read(65536);position=0;start=0
                    need(bool(chunk),'Truncated/invalid metrics JSON')
                record=''.join(pieces)
                try:value,end=decoder.raw_decode(record)
                except json.JSONDecodeError as error:raise Stop('Invalid metrics JSON record') from error
                need(end==len(record) and isinstance(value,dict),'Invalid/non-object metrics element')
                yield value
                record=None;pieces=None;value=None
                token=next_nonspace()
                if token==']':break
                need(token==',','Missing metrics comma');position+=1
                need(next_nonspace()!=']','Trailing metrics comma')
        position+=1
        need(not chunk[position:].strip(),'Trailing metrics bytes')
        while True:
            trailing=file.read(65536)
            if not trailing:return
            need(not trailing.strip(),'Trailing metrics bytes')


def load_inputs(s,request,request_ref,verify_model_bytes=True):
    ready=bound(s,request['ready_receipt']);need(request['ready_receipt']['sha256']==READY_SHA,'Wrong READY')
    # No post_stage/stage_context import: bind the independently accepted V3
    # CODE provenance, while every original report stays in the single V2 STATE.
    operational=request['runtime_storage_composition']
    need(operational['code_root']==str(RUNTIME_CODE_ROOT) and operational['state_root']==str(RUNTIME_STATE_ROOT),
         'Runtime V3 code/V2 state distinction changed')
    need(operational['post_stage']['path']==str(RUNTIME_CODE_ROOT/'post_stage.py')
         and operational['post_stage']['sha256']==RUNTIME_V3_POST_SHA
         and ident(s,Path(operational['post_stage']['path']))==operational['post_stage'],'Wrong accepted V3 operational source')
    need(operational['qualification']['path']==str(RUNTIME_CODE_ROOT/'QUALIFICATION_SYNTHETIC_ATTEMPT02.json')
         and operational['qualification']['sha256']==RUNTIME_V3_QUAL_SHA,'Wrong accepted V3 operational qualification')
    operational_qualification=bound(s,operational['qualification'])
    need(operational_qualification['files']['post_stage.py']==operational['post_stage']
         and operational_qualification['state_root']==str(RUNTIME_STATE_ROOT),'Operational qualification/code/state ancestry mismatch')
    need(operational['conductor']['path']==str(RUNTIME_CODE_ROOT/'conductor.py')
         and operational['conductor']['sha256']==RUNTIME_V3_CONDUCTOR_SHA
         and operational_qualification['files']['conductor.py']==operational['conductor']
         and ident(s,Path(operational['conductor']['path']))==operational['conductor'],'Wrong accepted V3 conductor source')
    need(operational['independent_acceptance']['path']==str(RUNTIME_V3_ACCEPTANCE_PATH)
         and operational['independent_acceptance']['sha256']==RUNTIME_V3_ACCEPTANCE_SHA,
         'Exact independent V3 receipt path required; own SHA/bytes must be bound in later quiet slot')
    bound(s,operational['independent_acceptance'])
    need(request['all8_storage_acceptance']['sha256']==RUNTIME_ALL8_ACCEPTANCE_SHA
         and request['runtime_actual_source_audit']['sha256']==RUNTIME_ACTUAL_SOURCE_SHA,'Wrong final runtime audit identities')
    closure=bound(s,request['all8_storage_acceptance']);actual_audit=bound(s,request['runtime_actual_source_audit'])
    need(closure.get('status')=='PASS' and closure.get('runtime_positions')==672 and closure.get('actual_processes_exit0')==640
         and closure.get('forecast_not_offered')==32 and closure.get('native_or_quality_acceptance_implied')is False,
         'Storage acceptance is incomplete or misrepresented as quality acceptance')
    need(actual_audit.get('status')=='PASS' and actual_audit.get('actual_processes')==640
         and actual_audit.get('ordinary_offered_stream_rows_exact')==38400
         and actual_audit.get('native_or_quality_success_not_inferred_from_process_exit')is True,
         'Actual runtime receipt/source/ordinary stream audit mismatch')

    need(request['evaluator']['sha256']==V4_SHA and request['donor_lineage']['sha256']==ANCESTRY_SHA,'Wrong frozen evaluator/ancestry')
    for name in ('evaluator','donor_lineage','preference_seal','preference_exposure_ledger','heldout_config','scalar_config','serving_config','projection_helper','sourceB96_accepted_report'):
        ident_ref=request[name];need(ident(s,Path(ident_ref['path']))==ident_ref,'Changed frozen input '+name)
    accepted_context=bound(s,request['sourceB96_input_manifest'])
    sourceB_report=bound(s,request['sourceB96_accepted_report'])
    need(len(request.get('sourceB96_acceptance_receipts',[]))>=3,'Exact accepted SourceB96 provenance receipts required')
    for receipt in request['sourceB96_acceptance_receipts']:bound(s,receipt)
    need(accepted_context.get('inputs')==sourceB_report.get('inputs'),'Accepted SourceB96 full-context input identity set differs')
    need(request['cwd']==str(ROOT),'Preserve original accepted working directory')
    native_root=ROOT/'analysis/native-transit-independent-v1-attempt01'
    need(request['native_reference']['path']==str(native_root/'FEASIBLE_REFERENCE_WITNESSES.jsonl')
         and request['native_offered_ledger']['path']==str(native_root/'OFFERED_NATIVE_ROWS.jsonl'),
         'Only the original complete native export/ledger is authorized')
    companion_names={Path(ref['path']).name for ref in request['native_companions']}
    need({'ARTIFACT_SHA256.json','REPORT.json','FEASIBLE_REFERENCE_SCHEMA.json','OFFERED_NATIVE_ROWS.jsonl'}<=companion_names,
         'Full native companion receipt/schema/offered ledger closure required')
    scalar_root=ROOT/'selector-quality/results/oracle-tune-full1h-48x9'
    for source in request['scalar_sources']:
        need(scalar_root in Path(source['file']['path']).parents and source['weights_sha256']==request['scalar_config']['sha256'],
             'Only exact original scalar432 source/weights lane is authorized')
    need(len(request['stage_reports'])==8,'All8 terminal storage reports required; stopped/uncertain future stages need separate owner evidence')
    plans=[];specs=[];ledgers=[];requests=[];stage_reports=[]
    for index,stage in enumerate(ready['stages']):
        plan=bound(s,stage['plan']);spec=bound(s,stage['prospective_specs']);storage_request=bound(s,stage['request'])
        expected_report=RUNTIME_STATE_ROOT/('b%d-s%d'%(index//4,index%4))/'STAGE_STORAGE_REPORT.json'
        need(request['stage_reports'][index]['path']==str(expected_report),'Original runtime report moved/copied out of V2 STATE')
        report=bound(s,request['stage_reports'][index]);need(report['stage_index']==index,'Stage report order changed')
        need(report['status']=='ALL_PRESENT_ADMITTED_RAW_VERIFIED_AND_RETIRED'
             and report['ready_receipt']==request['ready_receipt'] and report['plan']==stage['plan']
             and report['admission']==stage['storage_admission'],'Stage preservation/source ancestry missing')
        # Native/quality failure is NOT grounds to drop a run. A failed report can
        # feed a diagnostic view if all8 independently finalized ledgers exist.
        ledger=bound(s,report['offered_ledger'])
        need(ledger['ready_receipt']==request['ready_receipt'] and ledger['plan']==stage['plan'],'Ledger ancestry mismatch')
        plans.append(plan);specs.append(spec);requests.append(storage_request);ledgers.append(ledger);stage_reports.append(report)
    final=bound(s,stage_reports[-1]['global_ledger_snapshot'])
    need(final['through_stage_index']==7 and final['ready_receipt']==request['ready_receipt'] and len(final['rows'])==672,'Final global672 snapshot required')
    need(final['rows']==[r for ledger in ledgers for r in ledger['rows']],'Global672 does not equal exact8 observed ledgers')
    windows={w['window']:w for w in request['windows']}
    need(len({w['dataset']['sha256'] for w in request['windows']})==4,'Four distinct exact dataset/model hashes required')
    groups=partition(ready,plans,specs,ledgers,requests,windows)
    input_cache={}
    for group in groups.values():
        for run in group['runs']:
            argv=run['run']['argv'];query=Path(flag(argv,'-queries'))
            if str(query) not in input_cache:input_cache[str(query)]=ident(s,query)
            need(input_cache[str(query)]['sha256']==run['summary_entry']['frozen_bindings']['input_sha256'],
                 'Original exact workload bytes changed')
            need(flag(argv,'-preference-scenarios')==request['serving_config']['path'],'Frozen serving preference lexical path changed')
    weights_doc=bound(s,request['scalar_config']);weights=weights_doc.get('weights',weights_doc) if isinstance(weights_doc,dict) else weights_doc
    scalar=scalar_census(s,request['scalar_sources'],weights);scalar_parts=scalar_partition(scalar,windows)
    for ref in request['native_companions']:
        need(ident(s,Path(ref['path']))==ref,'Native complete companion/source identity changed')
    native_rows=[]
    need(ident(s,Path(request['native_offered_ledger']['path']))==request['native_offered_ledger'],'Native960 ledger changed')
    with s.regular_reader(Path(request['native_offered_ledger']['path'])) as (f,_):
        native_rows=[json.loads(line) for line in f]
    native=native_census(native_rows)
    need(ident(s,Path(request['native_reference']['path']))==request['native_reference'],'Native full original export changed')
    for window in windows.values():
        if verify_model_bytes:
            need(ident(s,Path(window['dataset']['path']))==window['dataset'],'Exact model bytes changed')
        else:
            need(Path(window['dataset']['path']).is_file() and Path(window['dataset']['path']).stat().st_size==window['dataset']['bytes'],
                 'Metadata-only model path/size differs; content is deliberately not opened')
        need(type(window['required_free_bytes'])is int and window['required_free_bytes']>=1_000_000_000,'Explicit restoration+fullV4/projection/archive forecast/reserve required')
    return {'ready':ready,'plans':plans,'ledgers':ledgers,'stage_reports':stage_reports,'groups':groups,'windows':windows,
            'scalar':scalar,'scalar_parts':scalar_parts,'weights':weights,'native':native,'request_ref':request_ref}


def paths(request,window):
    bundle=exact_path(request['bundle_root']);base=child(bundle,str(bundle/window))
    return {'bundle':bundle,'base':base,'views':base/'views','out':base/'v4','projection':base/'projection',
            'inputs':base/'VIEW_INPUTS.json','rows':base/'RUNTIME_STATE_ROWS.json',
            'check':base/'CONSUMER_CHECK.json','acceptance':base/'WINDOW_ACCEPTANCE.json',
            'projection_check':base/'PROJECTION_RETENTION_ACCEPTANCE.json'}


def future_files(request,groups):
    result=[str(paths(request,w)['out']/name) for w in WINDOWS for name in OUTPUT_NAMES]
    for window in WINDOWS:
        p=paths(request,window)
        result += [str(p[key]) for key in ('inputs','rows','check','acceptance','projection_check')]
        result += [str(p['base']/name) for name in ('EVALUATION_INTENT.json','EVALUATION_OUTCOME.json','EVALUATION.log',
            'PROJECTION_INTENT.json','PROJECTION_OUTCOME.json','PROJECTION.log','RETENTION_COMPLETE.json')]
        result += [str(p['projection']/name) for name in ('ORDINARY_ACTUAL_ROWS.jsonl','WINDOW_PROJECTION.json')]
        result += [str(p['views']/('stage-%d'%i)/'plan.json') for i in range(8)]
    bundle=Path(request['bundle_root'])
    result += [str(bundle/name) for name in ('GLOBAL_COMPOSITION_CHECK.json','COMBINE_INTENT.json','COMBINE_OUTCOME.json','COMBINE.log')]
    result += [str(bundle/'combined-projection'/'RUNTIME8_FRONTIER.json')]
    return result


def scalar_census_path(request):
    return exact_path(request['storage_control_root'])/'ORIGINAL_SCALAR432_CENSUS.json'


def storage_entry(request,window,request_ref,group):
    p=paths(request,window);raw=p['out']/'METRICS_BY_RUN.json';prefix=raw.with_suffix('')
    return {'role':'redundant-metrics','window':window,'raw_path':str(raw),'archive_path':str(raw)+'.gz',
        'manifest_path':str(prefix)+'.archive-manifest.json','acceptance_path':str(prefix)+'.storage-acceptance.json',
        'allow_raw_retirement':True,'retire_receipt_paths':[str(prefix)+'.retirement-after-projection.json'],
        'restore_receipt_paths':[str(prefix)+'.restoration-for-authorized-recheck.json'],
        'frozen_bindings':{'plan_sha256':canonical_hash([r['run'] for r in group['runs']]),'source_sha256':V4_SHA,
                          'input_sha256':request_ref['sha256'],'dataset_sha256':request['window_map'][window]['dataset']['sha256']}}


def admission_paths(request):
    control=exact_path(request['storage_control_root'])
    need(control.is_dir(),'Exact separate storage control root must already exist')
    return control/'STORAGE_REQUEST.json',control/'STORAGE_ADMISSION.json',control/'BEFORE_CREATION_INVENTORY.json'


def admit(s,request,request_ref):
    with s.quiet():
        context=load_inputs(s,request,request_ref)
        s.absent(exact_path(request['bundle_root']))
        declared=future_files(request,context['groups'])
        for name in declared:s.absent(Path(name))
        s.absent(scalar_census_path(request))
        request['window_map']=context['windows']
        entries=[storage_entry(request,window,request_ref,context['groups'][window]) for window in WINDOWS]
        owner_request={'schema':s.SCHEMA,'owner':request['owner'],'campaign_id':request['campaign_id'],
            'campaign_root':str(ROOT),'minimum_free_bytes':request['minimum_free_bytes'],'outputs':entries,
            'future_consumer_bundle_root':request['bundle_root'],'future_full_v4_output_files':declared,
            'future_scalar432_census_path':str(scalar_census_path(request)),
            'consumer_owner_request':request_ref,'reference_generation_inputs':request['native_reference'],
            'original_scalar432_census_value_sha256':canonical_hash(context['scalar']),
            'all672_state_value_sha256':canonical_hash([r for l in context['ledgers'] for r in l['rows']])}
        req,adm,inv=admission_paths(request)
        for path in (req,adm,inv):s.absent(path)
        s.write_doc(req,owner_request)
    # Unchanged freeze obtains its own lock. No root has been created.
    s.freeze(req,adm,inv)
    with s.quiet():
        s.absent(Path(request['bundle_root']))
        s.write_doc(scalar_census_path(request),context['scalar'])
        return {'storage_admission':ident(s,adm),'storage_inventory':ident(s,inv),'storage_request':ident(s,req)}


def check_admitted(s,request,context):
    req,adm,inv=admission_paths(request)
    admission=s.read_doc(adm)[0];owner=s.read_doc(req)[0]
    need(admission['request']==owner and admission['request_sha256']==ident(s,req)['sha256'],'Consumer storage request changed')
    need(owner['consumer_owner_request']==context['request_ref'] and owner['future_consumer_bundle_root']==request['bundle_root'],'Admission not bound to this exact consumer request')
    need(owner['original_scalar432_census_value_sha256']==canonical_hash(context['scalar'])
         and owner['all672_state_value_sha256']==canonical_hash([r for l in context['ledgers'] for r in l['rows']]),'Global432/672 census changed after admission')
    need(admission['inventory_sha256']==ident(s,inv)['sha256'],'Consumer before-creation inventory changed')
    need(owner['future_full_v4_output_files']==future_files(request,context['groups']), 'Exact full output/control path census changed')
    need(owner['future_scalar432_census_path']==str(scalar_census_path(request))
         and s.read_doc(scalar_census_path(request))[0]==context['scalar'],'Global scalar432 census changed')
    return adm,admission


def registry_identity(s,plan,parent):
    ref=plan.get('workload_registry')
    if ref is None:return None,None
    path=Path(ref['path']);path=path if path.is_absolute() else Path(parent)/path
    path=path.resolve();actual=ident(s,path)
    need(actual['sha256']==ref['sha256'] and actual['bytes']==ref['bytes'],'Original registry identity changed')
    payload=s.read_doc(path)[0]
    source=payload.get('source_manifest')
    if source:
        need(Path(source['path']).is_absolute(),'Relative raw source_manifest requires separate accepted cwd proof; no rebasing')
    return path,actual


def build(s,request,request_ref,window):
    with s.quiet():
        context=load_inputs(s,request,request_ref);check_admitted(s,request,context)
        p=paths(request,window);s.absent(p['base'])
        # No other closure's restored summaries may remain active.
        for other in WINDOWS:
            if other==window:continue
            for run in context['groups'][other]['runs']:
                need(not s.exists(Path(run['summary_entry']['raw_path'])),'Another model/window raw closure is restored')
        need(shutil.disk_usage(Path(request['bundle_root']).parent).free>=context['windows'][window]['required_free_bytes'],
             'Closure restoration/fullV4/projection/archive forecast plus reserve does not fit')
        group=context['groups'][window]
        restore=[]
        for run in group['runs']:
            entry=run['summary_entry'];raw=Path(entry['raw_path'])
            original_row=next(r for r in group['rows'] if r['id']==run['id'])
            observed=next(r for r in original_row['admitted_raw_files'] if r['path']==str(raw))
            if observed['state']=='MISSING':
                need(not s.exists(raw),'Originally missing raw unexpectedly appeared');continue
            need(observed['state']=='PRESENT','Unknown original raw state')
            need(not s.exists(raw),'Expected admitted stage-retired summary absent; uncertain already-restored state')
            receipt=Path(entry['restore_receipt_paths'][0]);s.absent(receipt);s.absent(Path(str(receipt)+'.intent.json'))
            restore.append((run,receipt))
    for run,receipt in restore:
        admission=context['ready']['stages'][run['stage_index']]['admission_path']
        s.restore(Path(admission),Path(run['summary_entry']['raw_path']),receipt)
    with s.quiet():
        # Storage admission predates this FIRST consumer/output-root creation.
        check_admitted(s,request,context)
        if not p['bundle'].exists():p['bundle'].mkdir()
        p['base'].mkdir();p['views'].mkdir()
        parent_refs=[]
        for parent in group['parents']:
            index=parent['stage_index'];ids=parent['selected_ids'];stage=context['ready']['stages'][index]
            plan=context['plans'][index];original=Path(stage['future_serving_root'])
            registry,regref=registry_identity(s,plan,original)
            derived=derive_plan(plan,ids,original,registry)
            root=p['views']/('stage-%d'%index);root.mkdir();s.write_doc(root/'plan.json',derived)
            for rid in ids:
                target=original/rid
                if target.is_dir():os.symlink(str(target),str(root/rid),target_is_directory=True)
                else:need(not os.path.lexists(target),'Original run dir is not ordinary directory/absent')
            parent_refs.append({'stage_index':index,'campaign':str(original),'plan':stage['plan'],
                'selected_indexes':derived['consumer_view']['original_run_indexes'],'selected_run_ids':ids,
                'derived_campaign':str(root),'derived_plan':ident(s,root/'plan.json'),'registry':regref})
        state={'schema':'sg-runtime8-window-state-rows-v1','window':window,'dataset_sha256':context['windows'][window]['dataset']['sha256'],
            'ready_receipt':request['ready_receipt'],'state_ledger_refs':[r['offered_ledger'] for r in context['stage_reports']],
            'rows':group['rows']}
        s.write_doc(p['rows'],state)
        manifest={'schema':'sg-runtime8-all8-window-view-inputs-v1','status':'INPUT_CLOSURE_BOUND_NOT_INDEPENDENTLY_ACCEPTED',
            'window':window,'dataset_sha256':context['windows'][window]['dataset']['sha256'],'ready_receipt':request['ready_receipt'],
            'evaluator':request['evaluator'],'owner_request':request_ref,'runtime_storage_composition':request['runtime_storage_composition'],'original_parents':parent_refs,
            'runtime_run_ids':[r['id'] for r in group['runs']],'runtime_state_rows':group['rows'],
            'all_stage_indexes':list(range(8)),'scalar432_value_sha256':canonical_hash(context['scalar']),
            'scalar_expected_slots':context['scalar_parts'][window],'native_global_offered_rows':960,
            'native_reference':request['native_reference'],'native_companions':request['native_companions'],
            'donor_lineage':request['donor_lineage'],'state_rows':ident(s,p['rows']),
            'storage_admission':ident(s,admission_paths(request)[1]),'original_path_restoration_receipts':[
                ident(s,receipt) for _,receipt in restore],'no_algorithm_success_filter':True}
        s.write_doc(p['inputs'],manifest)
        return manifest


def evaluate(s,request,request_ref,window):
    with s.quiet():
        context=load_inputs(s,request,request_ref);check_admitted(s,request,context);p=paths(request,window)
        view=s.read_doc(p['inputs'])[0];need(view['owner_request']==request_ref,'Derived input binding changed')
        need(view['runtime_run_ids']==[r['id'] for r in context['groups'][window]['runs']]
             and view['runtime_state_rows']==context['groups'][window]['rows'] and view['all_stage_indexes']==list(range(8))
             and [parent['stage_index'] for parent in view['original_parents']]==list(range(8)),
             'Derived ALL8 closure changed')
        s.absent(p['out']);intent=p['base']/'EVALUATION_INTENT.json';s.absent(intent)
        for parent in view['original_parents']:
            derived=bound(s,parent['derived_plan']);equivalent(context['plans'][parent['stage_index']],derived,parent['selected_run_ids'],
                Path(parent['registry']['path']) if parent['registry'] else None)
            for rid in parent['selected_run_ids']:
                original=Path(parent['campaign'])/rid;link=Path(parent['derived_campaign'])/rid
                need(not original.exists() or link.is_symlink() and os.readlink(link)==str(original),'Whole-directory original link changed')
        argv=[request['python'],'-B',request['evaluator']['path']]
        for parent in view['original_parents']:
            if parent['selected_run_ids']:argv += ['--campaign',parent['derived_campaign']]
        for source in request['scalar_sources']:
            literal=source['file']['path'];need(not any(c in literal for c in '*?[]'),'Exact scalar filenames, no expansive glob substitution')
            argv += ['--oracle-glob',literal]
        literal=request['native_reference']['path'];need(not any(c in literal for c in '*?[]'),'Exact native export filename required')
        argv += ['--feasible-reference-glob',literal,'--donor-lineage-config',request['donor_lineage']['path'],
                 '--reference-generation',request['reference_generation'],'--delivery-k',request['delivery_k'],'--out',str(p['out'])]
        s.write_doc(intent,{'schema':'sg-runtime8-unchanged-v4-intent-v1','argv':argv,'cwd':request['cwd'],
            'view_inputs':ident(s,p['inputs']),'no_retry_after_intent':True})
        log=p['base']/'EVALUATION.log';fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
        # V4 does not acquire campaign.lock; keep this lock for its whole process.
        with os.fdopen(fd,'wb') as file:
            outcome=subprocess.run(argv,cwd=request['cwd'],stdout=file,stderr=subprocess.STDOUT,check=False)
        result={'schema':'sg-runtime8-v4-terminal-v1','returncode':outcome.returncode,'argv':argv,'log':ident(s,log)}
        s.write_doc(p['base']/'EVALUATION_OUTCOME.json',result)
        need(outcome.returncode==0,'Unchanged V4 failed: preserve outputs, no retry/acceptance/retirement')
        return result


def check(s,request,request_ref,window):
    with s.quiet():
        context=load_inputs(s,request,request_ref);check_admitted(s,request,context);p=paths(request,window)
        terminal=s.read_doc(p['base']/'EVALUATION_OUTCOME.json')[0];need(terminal['returncode']==0,'V4 not terminal success')
        view=s.read_doc(p['inputs'])[0];group=context['groups'][window];expected=[r['id'] for r in group['runs']]
        rows=s.read_doc(p['rows'])[0];need(rows['rows']==group['rows'],'168 observational rows changed')
        metrics=[]
        for metric in iter_array(p['out']/'METRICS_BY_RUN.json'):
            need(metric['dataset_sha256']==view['dataset_sha256'] and metric['window']==window and metric['offered']==60,'Metric denominator/key changed')
            need(sum(metric['statuses'].values())==60,'Metric failure/unknown statuses lost')
            metrics.append({'id':metric['id'],'campaign':metric['campaign']})
        need([r['id'] for r in metrics]==expected,'Metrics lost/added/reordered runtime contributors')
        campaigns={r['id']:str(p['views']/('stage-%d'%r['stage_index'])) for r in group['runs']}
        need(all(row['campaign']==campaigns[row['id']] for row in metrics),'Lexical view campaign identity changed')
        report=s.read_doc(p['out']/'REPORT.json')[0]
        need(report['runs']==160 and report['offered_run_rows']==9600,'V4 offered serving denominator changed')
        need(report['reference_generation']==request['reference_generation'] and report['delivery_mode']==
             (request['delivery_k'] if request['delivery_k']=='per-run' else int(request['delivery_k'])),
             'V4 delivery/reference-generation changed')
        for name in ('evaluator','preference_seal','preference_exposure_ledger','heldout_config','scalar_config','donor_lineage'):
            ref=request[name];need(report['inputs'].get(ref['path'])==ref['sha256'],'V4 did not bind frozen input '+name)
        for parent in view['original_parents']:
            if parent['selected_run_ids']:
                ref=parent['derived_plan'];need(report['inputs'].get(ref['path'])==ref['sha256'],'V4 plan identity differs from derived view')

        check_scalar_output(s.read_doc(p['out']/'INDEPENDENT_ORACLE_SLOTS.json')[0],context['scalar_parts'][window],context['scalar']['headers'],context['weights'])
        native=s.read_doc(p['out']/'FEASIBLE_REFERENCE_IMPORT.json')[0];check_native_import(native,context['native'],view['dataset_sha256'])
        outputs={name:ident(s,p['out']/name) for name in OUTPUT_NAMES}
        result={'schema':'sg-runtime8-window-consumer-check-v1','status':'CONSUMER_CHECK_PASS_NOT_ACCEPTANCE',
            'window':window,'dataset_sha256':view['dataset_sha256'],'ready_receipt':request['ready_receipt'],
            'evaluator':request['evaluator'],'view_inputs':ident(s,p['inputs']),'state_rows':ident(s,p['rows']),
            'outputs':outputs,'closure':{'all_stage_indexes':list(range(8)),'runtime_run_ids':expected,'contributor_run_ids':expected,
                'scalar432_bound':True,'native_references_bound':True,'donor_ancestry_bound':True,'no_algorithm_success_filter':True,
                'state_ledger_refs':[r['offered_ledger'] for r in context['stage_reports']]},
            'scalar_slots_checked':len(context['scalar_parts'][window]),'native_global_offered_denominator':960,
            'native_denominator_not_summed_across_windows':True,'runtime_state_rows':group['rows'],
            'reference_provenance':{'runtime_storage_composition':request['runtime_storage_composition'],
                'original_scalar432_census':ident(s,scalar_census_path(request)),
                'original_native960_ledger':request['native_offered_ledger'],'native_reference':request['native_reference'],
                'native_companions':request['native_companions'],'donor_ancestry':request['donor_lineage'],
                'FEASIBLE_REFERENCE_IMPORT.json':outputs['FEASIBLE_REFERENCE_IMPORT.json'],
                'FEASIBLE_REFERENCE_PROVENANCE.json':outputs['FEASIBLE_REFERENCE_PROVENANCE.json'],
                'INDEPENDENT_ORACLE_SLOTS.json':outputs['INDEPENDENT_ORACLE_SLOTS.json']},
            'quality_authority':'UNCHANGED_FINALV4_OUTPUTS_ONLY','independent_acceptance':'PENDING'}
        s.write_doc(p['check'],result);return result


def accepted_window(s,request,request_ref,window,acceptance_ref):
    context=load_inputs(s,request,request_ref);check_admitted(s,request,context);p=paths(request,window)
    accepted=bound(s,acceptance_ref);checked=s.read_doc(p['check'])[0]
    need(accepted.get('consumer_check')==ident(s,p['check']),'Independent acceptance must bind full11-output consumer check')
    need(checked.get('status')=='CONSUMER_CHECK_PASS_NOT_ACCEPTANCE' and checked['window']==window
         and checked['dataset_sha256']==context['windows'][window]['dataset']['sha256']
         and checked['ready_receipt']==request['ready_receipt'] and checked['evaluator']==request['evaluator']
         and checked['runtime_state_rows']==context['groups'][window]['rows']
         and checked['closure']['runtime_run_ids']==[r['id'] for r in context['groups'][window]['runs']]
         and checked['closure']['contributor_run_ids']==[r['id'] for r in context['groups'][window]['runs']],
         'Consumer check differs from original ALL8/window authority')
    need(Path(acceptance_ref['path'])==p['acceptance'],'Wrong prospectively named independent acceptance path')
    need(accepted.get('schema')=='sg-runtime8-window-acceptance-v1' and accepted.get('status')=='INDEPENDENTLY_ACCEPTED',
         'Independent window acceptance required; consumer cannot self-accept')
    for key in ('window','dataset_sha256','ready_receipt','evaluator','runtime_state_rows','closure'):
        need(accepted.get(key)==checked[key],'Independent acceptance altered exact consumer closure '+key)
    for name in DOWNSTREAM:need(accepted['outputs'][name]==checked['outputs'][name],'Independent acceptance output changed')
    need(accepted.get('reference_provenance')==checked['reference_provenance'],
         'Independent acceptance omitted/changed global432/native960 additive provenance')
    for name in ('FEASIBLE_REFERENCE_IMPORT.json','FEASIBLE_REFERENCE_PROVENANCE.json','INDEPENDENT_ORACLE_SLOTS.json'):
        need(ident(s,Path(checked['outputs'][name]['path']))==checked['outputs'][name],'Reference output changed after check')
    return context,accepted,checked


def project(s,request,request_ref,window,acceptance_ref):
    with s.quiet():
        context,accepted,checked=accepted_window(s,request,request_ref,window,acceptance_ref);p=paths(request,window)
        s.absent(p['projection']);intent=p['base']/'PROJECTION_INTENT.json';s.absent(intent)
        argv=[request['python'],'-B',request['projection_helper']['path'],'--quiet-window-open','--mode','window',
            '--binding',acceptance_ref['path'],'--binding-sha256',acceptance_ref['sha256'],'--out-dir',str(p['projection'])]
        s.write_doc(intent,{'argv':argv,'acceptance':acceptance_ref,'no_retry_after_intent':True})
        fd=os.open(p['base']/'PROJECTION.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    # The separately qualified compact helper owns its own campaign lock.
    with os.fdopen(fd,'wb') as file:outcome=subprocess.run(argv,cwd=request['cwd'],stdout=file,stderr=subprocess.STDOUT,check=False)
    need(outcome.returncode==0,'Compact projection failed: preserve and stop; no METRICS retirement')
    with s.quiet():
        result={'schema':'sg-runtime8-projection-terminal-v1','returncode':outcome.returncode,
            'projection':ident(s,p['projection']/'WINDOW_PROJECTION.json'),'window_acceptance':acceptance_ref}
        s.write_doc(p['base']/'PROJECTION_OUTCOME.json',result);return result


def validate_compact_retention(s,projection_ref,acceptance_ref,checked,window,require_metrics=True):
    projection=bound(s,projection_ref)
    need(projection.get('schema')=='sg-runtime8-window-projection-v1' and projection['window']==window
         and projection['dataset_sha256']==checked['dataset_sha256'] and projection['acceptance_manifest']==acceptance_ref,
         'Compact projection/independent acceptance ancestry changed')
    ordinary=projection['ordinary_rows']
    need(ident(s,Path(ordinary['path']))==ordinary,'Retained compact ordinary rows missing/changed')
    expected={r['id'] for r in checked['runtime_state_rows']}
    need(len(projection['processes'])==168 and {p['id'] for p in projection['processes']}==expected,
         'Compact process denominator changed')
    slots=collections.defaultdict(set)
    with s.regular_reader(Path(ordinary['path'])) as (file,_):
        for line in file:
            row=json.loads(line);rid=row['run'];qid=row['query_id']
            need(rid in expected and qid not in slots[rid],'Compact ordinary process/query membership duplicated')
            slots[rid].add(qid)
    need(set(slots)==expected and sum(len(v) for v in slots.values())==10080 and all(len(v)==60 for v in slots.values()),
         'Compact failure-preserving10080 ordinary offer denominator changed')
    for field,name in (('authoritative_quality_aggregate','QUALITY_AGGREGATE.json'),
                       ('authoritative_scalar_comparisons','ORACLE_COMPARISONS.json')):
        need(projection[field]==checked['outputs'][name] and ident(s,Path(projection[field]['path']))==projection[field],
             'Retained authoritative quality/scalar source missing/changed')
    names=DOWNSTREAM if require_metrics else tuple(n for n in DOWNSTREAM if n!='METRICS_BY_RUN.json')
    for name in names:
        source=checked['outputs'][name]
        need(ident(s,Path(source['path']))==source,'Authoritative output changed before retention '+name)
    return projection


def retire(s,request,request_ref,window,acceptance_ref,projection_check_ref):
    with s.quiet():
        context,accepted,checked=accepted_window(s,request,request_ref,window,acceptance_ref);p=paths(request,window)
        projection_check=bound(s,projection_check_ref);terminal=s.read_doc(p['base']/'PROJECTION_OUTCOME.json')[0]
        need(Path(projection_check_ref['path'])==p['projection_check'],'Wrong independently checked projection-retention receipt')
        need(projection_check.get('schema')=='sg-runtime8-projection-retention-acceptance-v1'
             and projection_check.get('status')=='INDEPENDENTLY_ACCEPTED','Independent compact failure/quality/resource retention check required')
        validate_compact_retention(s,terminal['projection'],acceptance_ref,checked,window)
        need(projection_check.get('window_acceptance')==acceptance_ref and projection_check.get('projection')==terminal['projection']
             and projection_check.get('metrics_source')==checked['outputs']['METRICS_BY_RUN.json'],'Projection check source ancestry mismatch')
        need(projection_check.get('all168_process_positions_preserved')is True
             and projection_check.get('all10080_ordinary_offer_slots_preserved')is True
             and projection_check.get('failure_unknown_null_states_preserved')is True
             and projection_check.get('quality_resource_projections_checked')is True
             and projection_check.get('global432_native960_reference_provenance_preserved')is True
             and projection_check.get('reference_provenance')==checked['reference_provenance'],
             'Compact projection retention obligations incomplete')
        adm,admission=check_admitted(s,request,context)
        matches=[e for e in admission['request']['outputs'] if e['window']==window];need(len(matches)==1,'Exact future METRICS admission missing')
        entry=matches[0];raw=Path(entry['raw_path']);source=checked['outputs']['METRICS_BY_RUN.json']
        need(ident(s,raw)==source,'METRICS changed before storage acceptance')
        acceptance={'schema':s.SCHEMA,'kind':'post-measurement-acceptance','campaign_id':admission['campaign_id'],
            'admission_sha256':ident(s,adm)['sha256'],'raw_path':str(raw),'raw_sha256':source['sha256'],'raw_bytes':source['bytes'],
            'measurement_complete':True,'outside_headline_measurement':True,'storage_integrity_accepted':True,
            'content_outcome_state':'UNCHANGED_V4_TERMINAL_OUTPUT_NOT_QUALITY_SUCCESS_CLAIM',
            'all_offered_statuses_preserved':True,'quality_resource_projections_checked':True,
            'bindings':dict(entry['frozen_bindings'],run_manifest_sha256=ident(s,p['check'])['sha256'],
                offered_ledger_sha256=ident(s,p['rows'])['sha256'],projection_manifest_sha256=projection_check_ref['sha256']),
            'window_acceptance':acceptance_ref,'projection_retention_acceptance':projection_check_ref}
        s.write_doc(Path(entry['acceptance_path']),acceptance)
    s.archive(adm,Path(entry['acceptance_path']),raw)
    with s.quiet():s.verified_manifest(adm,raw,s.CAMPAIGN_LOCK)
    s.retire(adm,raw,Path(entry['retire_receipt_paths'][0]),explicitly_requested=True)
    # Only the original exact future summaries restored for THIS closure are
    # re-retired with their separately prospectively admitted second receipt.
    for run in context['groups'][window]['runs']:
        summary=run['summary_entry'];path=Path(summary['raw_path'])
        with s.quiet():present=s.exists(path)
        if present:
            need(len(summary['retire_receipt_paths'])>=2,'No admitted post-evaluation summary retirement receipt')
            original_adm=Path(context['ready']['stages'][run['stage_index']]['admission_path'])
            s.retire(original_adm,path,Path(summary['retire_receipt_paths'][1]),explicitly_requested=True)
    with s.quiet():
        result={'schema':'sg-runtime8-window-retention-complete-v1','window':window,'metrics_archive_manifest':ident(s,Path(entry['manifest_path'])),
            'metrics_retirement_receipt':ident(s,Path(entry['retire_receipt_paths'][0])),'projection_retention_acceptance':projection_check_ref}
        s.write_doc(p['base']/'RETENTION_COMPLETE.json',result);return result


def combine_check(s,request,request_ref,acceptance_refs):
    with s.quiet():
        need(len(acceptance_refs)==4,'Four independent window acceptances required')
        rows=[];ids=[];scalar_keys=[];native_ids=set();context=load_inputs(s,request,request_ref)
        for window,ref in zip(WINDOWS,acceptance_refs):
            _,accepted,checked=accepted_window(s,request,request_ref,window,ref)
            rows+=accepted['runtime_state_rows'];ids+=accepted['closure']['runtime_run_ids']
            scalar_keys += [tuple(slot['key']) for slot in context['scalar_parts'][window]]
            need(accepted['reference_provenance']['original_native960_ledger']==request['native_offered_ledger'],
                 'Four-view native reference authority differs')
            native_ids.add(semantic(accepted['reference_provenance']['original_native960_ledger']))
        need(len(rows)==672 and len({r['id'] for r in rows})==672 and len(ids)==len(set(ids))==640,'Four-view global672/640 composition failed')
        need(sorted(r['global_position'] for r in rows)==list(range(672)),'Four-view positions do not partition global672')
        need(len(scalar_keys)==len(set(scalar_keys))==432 and len(native_ids)==1,'Scalar432 partition/native960 identity deduplication failed')
        result={'schema':'sg-runtime8-four-window-composition-check-v1','status':'COMPOSITION_CHECK_PASS_NOT_QUALITY_ACCEPTANCE',
            'owner_request':request_ref,'ready_receipt':request['ready_receipt'],'window_acceptances':acceptance_refs,
            'process_positions':672,'consuming_run_ids':640,'forecast_refusals':32,'original_scalar_slots':432,
            'unique_original_native_offered_rows':960,'native_reference_input':request['native_offered_ledger']}
        s.write_doc(Path(request['bundle_root'])/'GLOBAL_COMPOSITION_CHECK.json',result);return result


def combine(s,request,request_ref,acceptance_refs):
    with s.quiet():
        need(len(acceptance_refs)==4,'Four independent window acceptances required')
        global_check=s.read_doc(Path(request['bundle_root'])/'GLOBAL_COMPOSITION_CHECK.json')[0]
        need(global_check['owner_request']==request_ref and global_check['window_acceptances']==acceptance_refs,
             'Exact global672/432/native960 composition check required')
        output=Path(request['bundle_root'])/'combined-projection';s.absent(output)
        argv=[request['python'],'-B',request['projection_helper']['path'],'--quiet-window-open','--mode','combine']
        for window,ref in zip(WINDOWS,acceptance_refs):
            _,accepted,checked=accepted_window(s,request,request_ref,window,ref)
            terminal=s.read_doc(paths(request,window)['base']/'PROJECTION_OUTCOME.json')[0]
            projection=terminal['projection'];validate_compact_retention(s,projection,ref,checked,window,require_metrics=False)
            argv += ['--binding',projection['path'],'--binding-sha256',projection['sha256']]
        argv += ['--out-dir',str(output)]
        intent=Path(request['bundle_root'])/'COMBINE_INTENT.json';s.absent(intent)
        s.write_doc(intent,{'argv':argv,'global_composition_check':ident(s,Path(request['bundle_root'])/'GLOBAL_COMPOSITION_CHECK.json'),
                          'no_retry_after_intent':True})
        fd=os.open(Path(request['bundle_root'])/'COMBINE.log',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    with os.fdopen(fd,'wb') as file:outcome=subprocess.run(argv,cwd=request['cwd'],stdout=file,stderr=subprocess.STDOUT,check=False)
    need(outcome.returncode==0,'Combined descriptive projection failed; no retry or source/runtime selection')
    with s.quiet():
        result={'schema':'sg-runtime8-combine-terminal-v1','returncode':outcome.returncode,
                'frontier':ident(s,output/'RUNTIME8_FRONTIER.json'),'no_selection_or_promotion':True}
        s.write_doc(Path(request['bundle_root'])/'COMBINE_OUTCOME.json',result);return result


def qualification(s,ref):
    receipt=bound(s,ref)
    need(receipt.get('schema')=='sg-runtime8-consumer-qualification-v1' and receipt.get('status')=='INDEPENDENTLY_ACCEPTED',
         'DRAFT: later independently accepted synthetic + real input-only consumer qualification required')
    for name in ('consumer.py','test_consumer.py'):
        need(ident(s,Path(__file__).with_name(name))==receipt['files'][name],'Qualified consumer source changed')
    need(receipt.get('unchanged_v4_reader_equivalence_checked')is True
         and receipt.get('native_global960_and_scalar_global432_partition_checked')is True,'Reader/loader equivalence not independently qualified')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase',choices=['admit','build','evaluate','check','project','retire','combine-check','combine'],required=True)
    p.add_argument('--request',required=True);p.add_argument('--request-sha256',required=True)
    p.add_argument('--qualification',required=True);p.add_argument('--qualification-sha256',required=True)
    p.add_argument('--quiet-window-open',action='store_true');p.add_argument('--window',choices=WINDOWS)
    p.add_argument('--binding',action='append',default=[]);p.add_argument('--binding-sha256',action='append',default=[])
    p.add_argument('--projection-check');p.add_argument('--projection-check-sha256')
    args=p.parse_args();need(args.quiet_window_open,'Owner must explicitly allocate post-conductor quiet analysis/storage slot')
    s=load_storage()
    with s.quiet():
        qref=ident(s,Path(args.qualification));need(qref['sha256']==args.qualification_sha256,'Independent qualification changed');qualification(s,qref)
        request_ref=ident(s,Path(args.request));need(request_ref['sha256']==args.request_sha256,'Owner request changed');request=bound(s,request_ref)
        need(request.get('schema')=='sg-runtime8-consumer-owner-request-v1'
             and request.get('execution_authorization')is True,'Exact explicitly authorized owner request required; input-only checker bindings cannot execute')
        need(request.get('minimum_free_bytes',0)>=1_000_000_000,'Original reserve floor required')
        need(len(args.binding)==len(args.binding_sha256),'Acceptance path/hash pairs differ')
        refs=[]
        for path,sha in zip(args.binding,args.binding_sha256):
            ref=ident(s,Path(path));need(ref['sha256']==sha,'Independent acceptance identity changed');refs.append(ref)
        projection_ref=None
        if args.projection_check:
            projection_ref=ident(s,Path(args.projection_check));need(projection_ref['sha256']==args.projection_check_sha256,'Projection check changed')
    if args.phase=='combine-check':result=combine_check(s,request,request_ref,refs)
    elif args.phase=='combine':result=combine(s,request,request_ref,refs)
    elif args.phase=='admit':result=admit(s,request,request_ref)
    else:
        need(args.window is not None,'Exact original window required')
        if args.phase=='build':result=build(s,request,request_ref,args.window)
        elif args.phase=='evaluate':result=evaluate(s,request,request_ref,args.window)
        elif args.phase=='check':result=check(s,request,request_ref,args.window)
        elif args.phase=='project':need(len(refs)==1,'One independent acceptance required');result=project(s,request,request_ref,args.window,refs[0])
        else:
            need(len(refs)==1 and projection_ref is not None,'Window and compact retention independent acceptances required')
            result=retire(s,request,request_ref,args.window,refs[0],projection_ref)
    print(json.dumps({'phase':args.phase,'status':'PHASE_COMPLETE_NOT_QUALITY_ACCEPTANCE'},sort_keys=True),flush=True)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        print(json.dumps({'status':'STOP_INSPECT_DO_NOT_RETRY','error_type':type(exc).__name__,'error':str(exc)}),file=sys.stderr,flush=True)
        sys.exit(2)
