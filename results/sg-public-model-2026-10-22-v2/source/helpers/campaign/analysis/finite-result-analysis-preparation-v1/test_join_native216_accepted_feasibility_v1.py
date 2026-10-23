"""Synthetic SOURCE fixtures only; never imports scientific helpers or models."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('native_property_join_candidate',
    Path(__file__).with_name('join_native216_accepted_feasibility_v1.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture():
    ledger=[];originals=[];new=[];pairs=[]
    for index in range(18):
        kind='range_profile' if index<8 else 'tad' if index<12 else 'bare_tb' if index==12 else 'scoped_tp' if index==13 else 'corech_graph'
        count=60 if index<14 else 107 if index==14 else 106
        oid='original-'+str(index);campaign='/tmp/synthetic-original';pass_sha=m.sig(['old-pass',oid])
        driver={'range_profile':'profilebench','tad':'tadbench','bare_tb':'familybench',
                'scoped_tp':'familybench','corech_graph':'corechgraphbench'}[kind]
        rows={}
        for q in range(count):
            locator='q'+str(q);query=dict(id=locator,source='a',target='b',ready_time=100,max_boardings=2)
            native=dict(base=query,last_ready_time=160) if kind=='range_profile' else query
            flags=dict(complete=True,completed=True,error=None,timed_out=False,unsupported=False)
            rows[locator]=dict(offered_locator=locator,native_complete=True,flags=flags,
                signature={key:m.sig([oid,locator,key]) for key in ('exact','objective','flags')})
            if index<13:
                ledger.append(dict(campaign=campaign,run_id=oid,status=m.COMPLETE,query=query,
                    offered_native_query=native,stratum='synthetic',native_complete=True,independent_witness_integrity=True,
                    dataset_sha256=m.sig('model'),workload_sha256=m.sig('workload'),native_driver=driver,
                    native_pass_sha256=pass_sha,native_pass_file='pass.json',native_repetition=0,native_warmup=False,
                    **{key:m.sig([oid,key]) for key in ('native_source_sha256','native_routing_sha256','native_binary_sha256',
                        'command_sha256','result_sha256','frozen_plan_sha256','native_manifest_sha256')}))
        original=dict(id=oid,campaign=campaign,kind=kind,driver=driver,window='synthetic-window',
            binding_error=None,run_complete=True,offered=count,expected_locators=list(rows),rows=rows,
            dataset_sha256=m.sig('model'),workload_sha256=m.sig('workload'),logical_call_sha256=m.sig([kind,'call']),
            exact_signature_sha256=m.sig([oid,'all-output']),selected_pass_descriptor=dict(
                file='pass.json',sha256=pass_sha,repetition=0,warmup=False))
        originals.append(original)
        for block in (0,1):
            for gc,heap in sorted(m.CELLS):
                run=copy.deepcopy(original);rid=oid+'-'+str(block)+'-'+gc+'-'+heap
                run.update(id=rid,campaign='/tmp/synthetic-new',original_native_contract_id=oid,
                    block=block,runtime=dict(GOGC=gc,GOMEMLIMIT=heap))
                new.append(run)
                pairs.append(dict(baseline=oid,candidate=rid,status='exact',complete_offered_pair=True,
                    control_output_exact=True,rows=[dict(offered_locator=key,status='complete_pair',exact=True,
                        objective=True,baseline_flags=row['flags'],candidate_flags=row['flags']) for key,row in run['rows'].items()]))
    for index in range(3):
        for q in range(60):ledger.append(dict(campaign='/tmp/synthetic-old-unavailable',run_id='unavailable-'+str(index),
            query=dict(id='q'+str(q)),status=m.UNAVAILABLE,native_complete=False,independent_witness_integrity=False))
    refs={name:dict(path='/tmp/'+name,sha256=m.sig(name),bytes=1) for name in m.REQUIRED_REFS}
    return ledger,originals,new,pairs,refs


class ProvenanceJoinTests(unittest.TestCase):
    def test_exact_frozen_closure_stays_pending_without_join_acceptance(self):
        result=m.derive_properties(*fixture())
        self.assertEqual((result['transferred_processes'],result['transferred_typed_rows']),(156,9360))
        self.assertEqual(len(result['unqualified_processes']),60)
        self.assertTrue(result['independent_join_chain_acceptance_required_before_gate'])
        self.assertTrue(all(not row['promotion_accepted'] for row in result['quality_evidence'].values()))
        self.assertEqual(result['new_witnesses'],0)

    def test_same_properties_only_after_explicit_verified_join_chain_ref(self):
        result=m.derive_properties(*fixture(),join_chain_acceptance_ref=dict(
            path='/tmp/synthetic-independent-join-acceptance',sha256='a'*64,bytes=1))
        self.assertTrue(all(row['promotion_accepted'] for row in result['quality_evidence'].values()))
        self.assertEqual(result['original960_status_census'][m.UNAVAILABLE],180)

    def test_old_pass_sha_mismatch_is_not_repaired_by_new_parity(self):
        data=fixture();data[0][0]['native_pass_sha256']='f'*64
        with self.assertRaises(ValueError):m.derive_properties(*data)

    def test_full_query_constraint_mismatch_rejected(self):
        data=fixture();data[0][0]['offered_native_query']=dict(base=dict(id='q0',max_boardings=999))
        with self.assertRaises(ValueError):m.derive_properties(*data)

    def test_timed_out_contradiction_rejected(self):
        data=fixture();data[2][0]['rows']['q0']['flags']['timed_out']=True
        with self.assertRaises(ValueError):m.derive_properties(*data)

    def test_missing_parity_link_rejected(self):
        data=fixture();data[3].pop()
        with self.assertRaises(ValueError):m.derive_properties(*data)

    def test_duplicate_old_offer_rejected(self):
        data=fixture();data[0][1]=copy.deepcopy(data[0][0])
        with self.assertRaises(ValueError):m.derive_properties(*data)

    def test_logical_call_model_query_constraint_binding_rejected(self):
        data=fixture();data[2][0]['logical_call_sha256']='f'*64
        with self.assertRaises(ValueError):m.derive_properties(*data)
