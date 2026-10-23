"""Pure provenance join, not an evaluator, reader, router or orchestration layer.

The consuming caller must verify the exact input refs and independently accepted
old960/parity chains before calling. No payload/model/helper IO occurs here.
Without a separately verified independent JOIN-chain acceptance ref, properties
remain promotion_accepted=False and MUST NOT qualify the native clock gate.
All proofs concern saved-witness/materialization integrity only. No witness,
reference occurrence, scalar slot, objective value or timing is minted/changed.
"""
import hashlib
import json
from collections import Counter,defaultdict

COMPLETE='feasible_materialization_integrity_complete_native_row'
UNAVAILABLE='unavailable_native_row_or_binding'
KINDS={'range_profile','tad','bare_tb'}
CELLS={(gc,heap) for gc in ('50','100','200') for heap in ('4GiB','7GiB')}
REQUIRED_REFS={'original960_report','original960_offers','original960_export',
    'old_independent_acceptance','original18_projections','native216_projections',
    'exact_parity_pairs','parity_independent_acceptance'}


def need(value,message):
    if not value:raise ValueError(message)


def sig(value):
    # Exactly the existing native projection's field-identity serializer.
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()


def checked_ref(ref):
    need(isinstance(ref,dict) and isinstance(ref.get('path'),str) and ref['path'].startswith('/'),
         'absolute bound provenance ref required')
    sha=ref.get('sha256');need(isinstance(sha,str) and len(sha)==64 and
        all(c in '0123456789abcdef' for c in sha),'invalid provenance digest')
    need(type(ref.get('bytes'))is int and ref['bytes']>0,'exact positive provenance byte count required')


def unique(records,key,label):
    answer={}
    for record in records:
        item=key(record);need(item not in answer,'duplicate '+label);answer[item]=record
    return answer


def checked_run(run):
    need(run.get('binding_error')is None and run.get('run_complete')is True,'incomplete or unbound run')
    expected=[str(item) for item in run['expected_locators']]
    need(len(expected)==len(set(expected))==run['offered'] and set(expected)==set(run['rows']),
         'missing/duplicate offered locator')
    for key,row in run['rows'].items():
        need(str(row['offered_locator'])==key and row.get('native_complete')is True,'incomplete native row')
        need(not any(row['flags'].get(name) for name in ('error','unsupported','timed_out')),
             'contradictory native completion flag')
        need(isinstance(row.get('signature'),dict) and row['signature'].get('exact'),
             'full saved-output signature missing')


def derive_properties(old960,original18,new216,pairs,verified_refs,join_chain_acceptance_ref=None):
    """Consume unchanged accepted records; emit a small derived property map.

    refs/acceptance-ref are byte-verified by the consuming caller, not authority
    inferred from filenames. Passing an acceptance ref is permitted only after
    its independently reviewed scope binds these exact refs and this join.
    No generic/smaller campaign mode exists. Missing/contradictory data aborts.
    """
    need(REQUIRED_REFS<=set(verified_refs),'missing exact original/parity provenance refs')
    for ref in verified_refs.values():checked_ref(ref)
    if join_chain_acceptance_ref is not None:checked_ref(join_chain_acceptance_ref)
    old960=list(old960)
    need(len(old960)==960,'original960 denominator changed')
    unique(old960,lambda row:(row['campaign'],row['run_id'],sig(row['query'])),'original960 offer')
    statuses=Counter(row['status'] for row in old960)
    need(statuses==Counter({COMPLETE:780,UNAVAILABLE:180}),'original960 accepted status census differs')
    originals=unique(original18,lambda run:run['id'],'original contract')
    candidates=unique(new216,lambda run:run['id'],'new process')
    links=unique(pairs,lambda pair:pair['candidate'],'original/new parity link')
    need(len(originals)==18 and len(candidates)==216 and set(candidates)==set(links),
         'original18/new216/full-link closure differs')
    for run in list(originals.values())+list(candidates.values()):checked_run(run)
    old_complete=defaultdict(list)
    for row in old960:
        if row['status']==COMPLETE:
            need(row.get('native_complete')is True and row.get('independent_witness_integrity')is True,
                 'old integrity/completion contradiction')
            old_complete[(row['campaign'],row['run_id'])].append(row)
    need(len(old_complete)==13,'accepted original13 contract closure differs')
    original_proofs={};quality={}
    for (campaign,oid),rows in old_complete.items():
        need(oid in originals,'accepted old contract absent from original18')
        original=originals[oid]
        need(original['campaign']==campaign and original['kind'] in KINDS,'old campaign/kind differs')
        need(len(rows)==60 and original['offered']==60,'old accepted per-contract60 differs')
        descriptor=original['selected_pass_descriptor']
        pass_sha=descriptor['sha256'];by_locator={}
        pins=('native_source_sha256','native_routing_sha256','native_binary_sha256',
              'command_sha256','result_sha256','frozen_plan_sha256','native_manifest_sha256')
        need(all(len({row.get(pin) for row in rows})==1 and rows[0].get(pin) for pin in pins),
             'old source/command/manifest pin set is inconsistent')
        for row in rows:
            need(row['dataset_sha256']==original['dataset_sha256'] and
                row['workload_sha256']==original['workload_sha256'] and
                row['native_driver']==original['driver'],'old model/workload/driver binding differs')
            need(row['native_pass_sha256']==pass_sha and row['native_pass_file']==descriptor['file'] and
                row['native_repetition']==0 and row['native_warmup']is False and
                descriptor.get('repetition')==0 and descriptor.get('warmup')is False and not descriptor.get('forced'),
                'old audited pass is not the exact original projection ordinary pass')
            native_query=row['offered_native_query'];base=native_query.get('base',native_query)
            need(base==row['query'],'old full query/constraints differ')
            locator=str(row['query']['id']);need(locator not in by_locator,'duplicate old locator')
            by_locator[locator]=dict(query=row['query'],offered_native_query=native_query,stratum=row['stratum'],
                full_output_signature=original['rows'][locator]['signature']['exact'],
                independent_witness_integrity=True,native_complete=True,accepted_old_status=COMPLETE)
        need(set(by_locator)==set(original['rows']),'old accepted query/constraint cohort differs')
        original_proofs[oid]=dict(campaign=campaign,run_id=oid,native_pass_sha256=pass_sha,
            native_pass_file=descriptor['file'],dataset_sha256=original['dataset_sha256'],
            workload_sha256=original['workload_sha256'],**{pin:rows[0][pin] for pin in pins})
        quality[oid]=dict(quality_comparison_key=sig({key:original[key] for key in
            ('kind','dataset_sha256','workload_sha256','logical_call_sha256')}),
            quality_signature_sha256=sig(by_locator))
    need(Counter(originals[oid]['kind'] for oid in quality)==Counter(range_profile=8,tad=4,bare_tb=1),
         'accepted8range/4TAD/1bareTB closure differs')
    cohort=defaultdict(set);properties={};unqualified=[];new_rows=0
    for rid,run in candidates.items():
        oid=run['original_native_contract_id'];need(oid in originals,'unknown original contract')
        original=originals[oid];pair=links[rid]
        need(pair['baseline']==oid and pair['status']=='exact' and pair['complete_offered_pair']is True and
            pair['control_output_exact']is True,'full original/new parity is not exact')
        for field in ('kind','driver','window','dataset_sha256','workload_sha256','logical_call_sha256','exact_signature_sha256'):
            need(run[field]==original[field],'original/new model/query/constraint/output binding differs: '+field)
        need(run['expected_locators']==original['expected_locators'],'offered query order/identity differs')
        checks=unique(pair['rows'],lambda row:str(row['offered_locator']),'parity row')
        need(set(checks)==set(run['rows']),'parity row coverage differs')
        for locator,row in run['rows'].items():
            check=checks[locator];before=original['rows'][locator]
            need(check['status']=='complete_pair' and check['exact']is True and check['objective']is True and
                row['signature']==before['signature'] and row['flags']==before['flags'] and
                check['baseline_flags']==before['flags'] and check['candidate_flags']==row['flags'],
                'witness/materialization/status signature mismatch')
        cell=(str(run['runtime']['GOGC']),run['runtime']['GOMEMLIMIT']);block=run['block']
        need(cell in CELLS and type(block)is int and block in (0,1),'runtime cell/block differs')
        need((block,cell)not in cohort[oid],'duplicate original/runtime/block')
        cohort[oid].add((block,cell))
        if oid in quality:
            properties[rid]=dict(run_id=rid,kind=run['kind'],original_native_contract_id=oid,
                promotion_accepted=join_chain_acceptance_ref is not None,
                exact_signature_sha256=run['exact_signature_sha256'],
                independently_feasible_complete_rows=run['offered'],**quality[oid],
                scope='Transferred accepted saved-witness/materialization integrity only; no search/global/profile completeness or new scalar proof.')
            new_rows+=run['offered']
        else:
            need(run['kind'] in {'scoped_tp','corech_graph'},'unexpected unqualified native kind')
            unqualified.append(dict(run_id=rid,kind=run['kind'],offered=run['offered'],
                reason='Outside accepted original960 independent transit-integrity proof; parity is not feasibility.'))
    need(set(cohort)==set(originals) and all(len(cells)==12 for cells in cohort.values()),'18x6x2 closure differs')
    need(len(properties)==156 and new_rows==9360 and
        Counter(row['kind'] for row in unqualified)==Counter(scoped_tp=12,corech_graph=48),
        'qualified156/9360 or unqualified12TP/48graph closure differs')
    return dict(schema='native216-accepted-feasibility-provenance-join-v1',quality_evidence=properties,
        exact_input_refs=verified_refs,join_chain_acceptance_ref=join_chain_acceptance_ref,
        independent_join_chain_acceptance_required_before_gate=join_chain_acceptance_ref is None,
        original960_status_census=dict(statuses),original_pass_bindings=original_proofs,
        transferred_processes=156,transferred_typed_rows=9360,unqualified_processes=unqualified,
        original_scalar432_unchanged=True,original_native960_unchanged=True,
        new_witnesses=0,new_reference_occurrences=0,new_scalar_slots=0,model_loads=0,
        scoring_or_clock_computation_performed=False)
