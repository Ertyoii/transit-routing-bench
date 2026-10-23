"""Focused synthetic tests only. No real campaign/model/evaluator execution."""
import fcntl
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

w = module('post_stage_test_subject', HERE / 'post_stage.py')
s = module('unchanged_storage_test_subject', HERE.parent / 'storage.py')

class Fixture:
    def __init__(self, base, *, outcome='completed', missing=False, malformed=False):
        self.base = base
        self.lock = base / 'campaign.lock'
        self.lock.write_text('synthetic lock\n')
        self.experiments = base / 'experiments'
        self.experiments.mkdir()
        self.future = self.experiments / 'b0-s0-run'
        self.storage = self.experiments / 'storage'
        self.storage.mkdir()
        self.work = base / 'workflow'
        self.work.mkdir()
        self.ids = ['b0-runtime-ultra-subset-local-walk-ties-synthetic', 'b0-runtime-old-native-ultra-subset-control-synthetic']
        rows = [{'id': rid, 'state':'PLANNED_UNSTARTED'} for rid in self.ids]
        rows += [{'id':'refused-%d' % i, 'state':'NOT_OFFERED_MEMORY_FORECAST', 'reason':'synthetic refusal',
                  'evidence':{'path':'synthetic-only', 'sha256':'e'*64}} for i in range(82)]
        plan = {'runtime_stage':{'all84_state_rows':rows, 'global_start_position':0, 'block':0, 'segment':0},
                'runs':[{'id':rid, 'synthetic':True} for rid in self.ids],
                'memory_admission':{'synthetic':'qualified-wrapper-binding'}}
        self.plan = base / 'frozen-plan.json'
        self.write(self.plan,plan)
        planref = self.ref(self.plan)
        outputs=[]
        for rid in self.ids:
            names=['summary'] + (['sparse-full-preparation'] if rid == self.ids[0] else [])
            for name in names:
                prefix=self.future/rid/'artifact'/name
                outputs.append({'run_id':rid, 'role':'proof-summary' if name=='summary' else 'proof-sidecar',
                    'raw_path':str(prefix)+'.json','archive_path':str(prefix)+'.json.gz',
                    'manifest_path':str(prefix)+'.archive-manifest.json','acceptance_path':str(prefix)+'.storage-acceptance.json',
                    'allow_raw_retirement':True,'retire_receipt_paths':[str(prefix)+'.retirement-after-stage.json'],
                    'restore_receipt_paths':[str(prefix)+'.restoration-for-evaluation.json'],
                    'frozen_bindings':{'plan_sha256':planref['sha256'],'source_sha256':'a'*64,
                                       'input_sha256':'b'*64,'dataset_sha256':'c'*64}})
        self.request=self.storage/'request.json'
        self.admission=self.storage/'admission.json'
        self.inventory=self.storage/'inventory.json'
        self.write(self.request,{'schema':s.SCHEMA,'owner':'synthetic-owner','campaign_id':'synthetic-b0-s0',
            'campaign_root':str(self.experiments),'minimum_free_bytes':0,
            'future_serving_root_must_remain_absent_until_admitted':str(self.future),'outputs':outputs})
        s.freeze(self.request,self.admission,self.inventory,lock_path=self.lock)
        dummy=base/'frozen-evidence.json'
        self.write(dummy,{'synthetic':True})
        stage={'block':0,'segment':0,'future_serving_root':str(self.future),'plan':planref,
               'offered_runs':2,'unoffered_runs':82,'raw_summary_paths':2,'raw_full_proof_sidecar_paths':1,
               'storage_admission':self.ref(self.admission),'admission_path':str(self.admission),
               'storage_inventory':self.ref(self.inventory),'inventory_path':str(self.inventory),
               'request':self.ref(self.request),'freeze':self.ref(dummy),'prospective_specs':self.ref(dummy)}
        globalrows=rows+[{'id':'future-%d'%i,'state':'PLANNED_UNSTARTED'} for i in range(588)]
        self.ready=base/'READY.json'
        self.write(self.ready,{'runtime_slots':672,'all672_state_rows':globalrows,'stages':[stage]*8})
        self.ready_sha=self.ref(self.ready)['sha256']
        self.outputs=outputs
        self.future.mkdir()
        (self.future/'plan.json').write_bytes(self.plan.read_bytes())
        completed=[]
        self.rawbytes={}
        for rid in self.ids:
            rd=self.future/rid
            (rd/'artifact').mkdir(parents=True)
            self.write(rd/'command.json',{'id':rid,'argv':['synthetic-only-no-execution'],
                       'pid':99999998,'pgid':99999998,'process_start_ticks':'1'})
            result={'id':rid,'ok':outcome=='completed','returncode':0 if outcome=='completed' else 1,
                    'timed_out':False,'elapsed_wall_s':None,'outcome':'synthetic-'+outcome}
            self.write(rd/'result.json',result)
            mem={'schema':'observed-memory-admission-record-v1','run_id':rid,'offer_index':self.ids.index(rid),
                 'decision':'admitted','plan':planref,'offered_spec_sha256':w.canonical_hash(plan['runs'][self.ids.index(rid)]),
                 'binding':plan['memory_admission']}
            mem['record_sha256']=w.canonical_hash(mem)
            self.write(rd/'memory-admission.json',mem)
            completed.append({'id':rid,'ok':result['ok'],'returncode':result['returncode'],
                              'timed_out':False,'elapsed_wall_s':None,'result':str(rd/'result.json')})
        for i,entry in enumerate(outputs):
            if missing and i==0:
                continue
            data=(b'not even JSON\x00\xff\n' if malformed else b'{"proof":"synthetic byte exact\\n"}\n')*4
            Path(entry['raw_path']).write_bytes(data)
            self.rawbytes[entry['raw_path']]=data
        self.status={'state':outcome,'ok':outcome=='completed','runner_pid':99999999,'runner_start_ticks':'1',
                     'plan_sha256':planref['sha256'],'out_dir':str(self.future),'total_runs':2,'completed_runs':completed}
        self.write(self.future/'status.json',self.status)
    @staticmethod
    def write(path,doc):
        path.write_text(json.dumps(doc,sort_keys=True,indent=2)+'\n')
    @staticmethod
    def ref(path):
        data=path.read_bytes()
        return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    def run(self):
        return w.preserve(s,0,self.ready,self.ready_sha,self.work,self.lock)

class PostStageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='post-stage-synthetic-')
        self.base=Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def fixture(self,**kwargs):
        return Fixture(self.base,**kwargs)
    def test_complete_archive_independent_verify_retire_restore_exact_bytes(self):
        f=self.fixture(malformed=True)
        report=f.run()
        self.assertTrue(report['terminal_stage_success'])
        self.assertEqual(report['present_artifacts_preserved'],3)
        ledger=json.loads((f.work/'b0-s0/OFFERED_LEDGER.json').read_text())
        self.assertEqual(len(ledger['rows']),84)
        self.assertEqual(sum(r['state']=='NOT_OFFERED_MEMORY_FORECAST' for r in ledger['rows']),82)
        globaldoc=json.loads((f.work/'b0-s0/GLOBAL_LEDGER_SNAPSHOT.json').read_text())
        self.assertEqual(len(globaldoc['rows']),672)
        for entry in f.outputs:
            raw=Path(entry['raw_path'])
            self.assertFalse(raw.exists())
            with s.quiet(f.lock):
                _,_,_,manifest,_=s.verified_manifest(f.admission,raw,f.lock)
            self.assertEqual(manifest['raw_sha256'],hashlib.sha256(f.rawbytes[str(raw)]).hexdigest())
            s.restore(f.admission,raw,Path(entry['restore_receipt_paths'][0]),lock_path=f.lock)
            self.assertEqual(raw.read_bytes(),f.rawbytes[str(raw)])
    def test_failed_and_missing_preserved_without_fake_raw(self):
        f=self.fixture(outcome='stopped_on_failure',missing=True)
        report=f.run()
        self.assertFalse(report['terminal_stage_success'])
        self.assertEqual(len(report['missing_artifacts']),1)
        missing=f.outputs[0]
        self.assertFalse(Path(missing['raw_path']).exists())
        self.assertFalse(Path(missing['archive_path']).exists())
        self.assertFalse(Path(missing['acceptance_path']).exists())
        self.assertEqual(report['present_artifacts_preserved'],2)
        accepted=json.loads(Path(f.outputs[1]['acceptance_path']).read_text())
        self.assertFalse(accepted['actual_result_fields']['ok'])
        self.assertTrue(accepted['storage_acceptance_is_not_native_or_quality_acceptance'])
    def test_running_status_refused_before_raw_digest(self):
        f=self.fixture(outcome='running')
        original=s.digest_file
        def no_raw(path):
            self.assertNotIn(str(path),f.rawbytes,'Must establish terminal writer before raw hashing')
            return original(path)
        s.digest_file=no_raw
        try:
            with self.assertRaisesRegex(RuntimeError,'not terminal'):
                f.run()
        finally:
            s.digest_file=original
        self.assertFalse((f.work/'b0-s0').exists())
    def test_live_original_runner_refused(self):
        f=self.fixture()
        f.status.update(runner_pid=os.getpid(),runner_start_ticks=str(w.pid_start(os.getpid())))
        f.write(f.future/'status.json',f.status)
        with self.assertRaisesRegex(RuntimeError,'still alive'):
            f.run()
    def test_live_recorded_command_group_refused(self):
        f=self.fixture()
        f.write(f.future/f.ids[0]/'command.json',{'pid':os.getpgrp(),'pgid':os.getpgrp(),'process_start_ticks':'1'})
        with self.assertRaisesRegex(RuntimeError,'group still exists'):
            f.run()
    def test_authoritative_lock_blocks_before_stage_work(self):
        f=self.fixture()
        with open(f.lock,'r') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(s.Refusal):
                f.run()
        self.assertFalse((f.work/'b0-s0').exists())
    def test_ready_change_refuses(self):
        f=self.fixture()
        f.ready.write_text(f.ready.read_text()+' ')
        with self.assertRaisesRegex(RuntimeError,'READY receipt changed'):
            f.run()
    def test_plan_change_refuses(self):
        f=self.fixture()
        f.plan.write_text(f.plan.read_text()+' ')
        with self.assertRaisesRegex(RuntimeError,'Changed frozen reference'):
            f.run()
    def test_actual_runner_plan_change_refuses(self):
        f=self.fixture()
        (f.future/'plan.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'Actual runner plan'):
            f.run()
    def test_refused_run_output_refuses(self):
        f=self.fixture()
        (f.future/'refused-0').mkdir()
        with self.assertRaisesRegex(RuntimeError,'Forecast-refused'):
            f.run()
    def test_existing_retirement_intent_refuses_without_any_mutation(self):
        f=self.fixture()
        path=Path(f.outputs[0]['retire_receipt_paths'][0]+'.intent.json')
        path.write_text('uncertain existing intent')
        with self.assertRaises(s.Refusal):
            f.run()
        self.assertEqual(path.read_text(),'uncertain existing intent')
        self.assertFalse((f.work/'b0-s0').exists())
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))
    def test_repeat_is_refused_does_not_modify_prior_report(self):
        f=self.fixture()
        f.run()
        p=f.work/'b0-s0/STAGE_STORAGE_REPORT.json'
        before=p.read_bytes()
        with self.assertRaises(s.Refusal):
            f.run()
        self.assertEqual(before,p.read_bytes())
        self.assertFalse((f.work/'b0-s0/STOP_INSPECT_DO_NOT_RETRY.json').exists())
    def test_nonallowlisted_raw_and_historical_evidence_untouched(self):
        f=self.fixture()
        old=f.experiments/'historical-summary.json'
        old.write_bytes(b'old untouched')
        other=f.future/f.ids[0]/'artifact/other.json'
        other.write_bytes(b'not admitted')
        f.run()
        self.assertEqual(old.read_bytes(),b'old untouched')
        self.assertEqual(other.read_bytes(),b'not admitted')
    def test_partial_archive_failure_stops_no_retirement_or_retry(self):
        f=self.fixture()
        original=s.archive
        calls=[]
        def fail(*args,**kwargs):
            calls.append(args)
            raise OSError('synthetic disk full')
        s.archive=fail
        try:
            with self.assertRaisesRegex(OSError,'disk full'):
                f.run()
        finally:
            s.archive=original
        self.assertEqual(len(calls),1)
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))
        self.assertTrue((f.work/'b0-s0/STOP_INSPECT_DO_NOT_RETRY.json').exists())
        self.assertFalse((f.work/'b0-s0/STAGE_STORAGE_REPORT.json').exists())

    def test_missing_or_unparseable_result_never_qualifies_terminal_success(self):
        f=self.fixture()
        (f.future/f.ids[0]/'result.json').unlink()
        report=f.run()
        self.assertFalse(report['terminal_stage_success'])
        self.assertEqual(report['present_artifacts_preserved'],3)
    def test_unparseable_result_preserved_unknown_never_advances(self):
        f=self.fixture()
        (f.future/f.ids[0]/'result.json').write_bytes(b'{broken result')
        report=f.run()
        self.assertFalse(report['terminal_stage_success'])
        ledger=json.loads((f.work/'b0-s0/OFFERED_LEDGER.json').read_text())
        self.assertEqual(ledger['rows'][0]['state'],'UNKNOWN_UNPARSEABLE_RESULT')
    def test_root_success_cannot_override_failed_result_status(self):
        f=self.fixture()
        p=f.future/f.ids[0]/'result.json'
        result=json.loads(p.read_text())
        result.update(ok=False,returncode=1,timed_out=True)
        f.write(p,result)
        self.assertFalse(f.run()['terminal_stage_success'])
    def test_bool_returncode_is_not_successful_typed_process_exit(self):
        f=self.fixture()
        p=f.future/f.ids[0]/'result.json'
        result=json.loads(p.read_text());result['returncode']=False;f.write(p,result)
        self.assertFalse(f.run()['terminal_stage_success'])
    def test_missing_completed_offer_cannot_advance(self):
        f=self.fixture();f.status['completed_runs']=f.status['completed_runs'][:1]
        f.write(f.future/'status.json',f.status)
        self.assertFalse(f.run()['terminal_stage_success'])
    def test_completed_order_must_match_frozen_offer_order(self):
        f=self.fixture();f.status['completed_runs'].reverse();f.write(f.future/'status.json',f.status)
        self.assertFalse(f.run()['terminal_stage_success'])
    def test_duplicate_completed_ids_refused(self):
        f=self.fixture();f.status['completed_runs']=[f.status['completed_runs'][0]]*2
        f.write(f.future/'status.json',f.status)
        with self.assertRaisesRegex(RuntimeError,'Bad completed ledger'):
            f.run()
    def test_empty_command_cannot_skip_terminality_before_raw_digest(self):
        f=self.fixture();f.write(f.future/f.ids[0]/'command.json',{})
        with self.assertRaisesRegex(RuntimeError,'typed full command'):
            f.run()
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))
        self.assertFalse((f.work/'b0-s0').exists())
    def test_missing_command_with_raw_is_uncertain_not_retirement_permission(self):
        f=self.fixture();(f.future/f.ids[0]/'command.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'missing/unparseable required command'):
            f.run()
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))
    def test_unparseable_command_with_raw_is_refused(self):
        f=self.fixture();(f.future/f.ids[0]/'command.json').write_bytes(b'{broken command')
        with self.assertRaisesRegex(RuntimeError,'missing/unparseable required command'):
            f.run()
    def test_string_or_bool_command_pid_cannot_qualify(self):
        f=self.fixture();p=f.future/f.ids[0]/'command.json';doc=json.loads(p.read_text());doc['pid']=True;f.write(p,doc)
        with self.assertRaisesRegex(RuntimeError,'typed full command'):
            f.run()
    def test_missing_admission_cannot_qualify_started_run(self):
        f=self.fixture();(f.future/f.ids[0]/'memory-admission.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'required memory admission'):
            f.run()
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))
    def test_admission_spec_tamper_refused(self):
        f=self.fixture();p=f.future/f.ids[0]/'memory-admission.json';doc=json.loads(p.read_text())
        doc['offered_spec_sha256']='f'*64;doc.pop('record_sha256');doc['record_sha256']=w.canonical_hash(doc);f.write(p,doc)
        with self.assertRaisesRegex(RuntimeError,'plan/spec binding'):
            f.run()
    def test_complete_result_status_fields_must_match(self):
        f=self.fixture();f.status['completed_runs'][0]['returncode']=1;f.write(f.future/'status.json',f.status)
        self.assertFalse(f.run()['terminal_stage_success'])

    def test_actual_harness_tick_string_schema_used_by_fixture(self):
        f=self.fixture()
        self.assertIs(type(f.status['runner_start_ticks']),str)
        self.assertTrue(f.run()['terminal_stage_success'])
    def test_strict_tick_parser_rejects_noncanonical_and_nonstrings(self):
        invalid=[None,True,False,1,1.0,-1,0,'','0','00','01','+1','-1',' 1','1 ','1.0','1e1','１','١','1\n',
                 '18446744073709551616','1'*21]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError,'ticks'):
                    w.positive_tick_string(value)
        self.assertEqual(w.positive_tick_string('31329008'),31329008)
    def test_noncanonical_runner_ticks_stop_before_raw_archive(self):
        f=self.fixture();f.status['runner_start_ticks']='01';f.write(f.future/'status.json',f.status)
        with self.assertRaisesRegex(RuntimeError,'canonical positive'):
            f.run()
        self.assertFalse((f.work/'b0-s0').exists())
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))
    def test_noncanonical_command_ticks_stop_before_raw_archive(self):
        f=self.fixture();p=f.future/f.ids[0]/'command.json';doc=json.loads(p.read_text());doc['process_start_ticks']=' 1';f.write(p,doc)
        with self.assertRaisesRegex(RuntimeError,'canonical positive'):
            f.run()
        self.assertFalse((f.work/'b0-s0').exists())
        self.assertTrue(all(Path(e['raw_path']).exists() for e in f.outputs))

class PriorAncestryTests(unittest.TestCase):
    def setUp(self):
        self.readyref={'path':'READY','sha256':'ready','bytes':1}
        initial=[{'id':'id-%d'%i,'state':'PLANNED_UNSTARTED'} for i in range(672)]
        self.ready={'all672_state_rows':initial,'stages':[{'plan':{'sha256':'plan'},'storage_admission':{'sha256':'admission'}}]*8}
        self.rows=[{'id':r['id'],'global_position':i,'initial_state_row':r,'state':'RESULT_RECORDED'} for i,r in enumerate(initial[:84])]
        self.report={'status':'ALL_PRESENT_ADMITTED_RAW_VERIFIED_AND_RETIRED','terminal_stage_success':True,
            'stage_index':0,'ready_receipt':self.readyref,'plan':{'sha256':'plan'},'admission':{'sha256':'admission'}}
        self.ledger={'ready_receipt':self.readyref,'plan':{'sha256':'plan'},'stage_index':0,'rows':self.rows}
        self.globaldoc={'ready_receipt':self.readyref,'through_stage_index':0,'rows':self.rows+[
            {'id':r['id'],'global_position':i+84,'initial_state_row':r,'state':r['state']} for i,r in enumerate(initial[84:])]}
    def check(self):
        return w.validate_prior_ancestry(self.report,self.ledger,self.globaldoc,0,self.ready,self.readyref)
    def test_exact_prior_ancestry_passes(self):
        self.check()
    def test_failed_prior_generic_storage_status_never_resumes(self):
        self.report['terminal_stage_success']=False
        with self.assertRaisesRegex(RuntimeError,'terminal success'):
            self.check()
    def test_prior_other_ready_receipt_refused(self):
        self.report['ready_receipt']={'sha256':'other'}
        with self.assertRaisesRegex(RuntimeError,'ancestry mismatch'):
            self.check()
    def test_prior_other_plan_refused(self):
        self.report['plan']={'sha256':'other'}
        with self.assertRaisesRegex(RuntimeError,'ancestry mismatch'):
            self.check()
    def test_prior_wrong_position_refused(self):
        self.ledger=copy.deepcopy(self.ledger);self.ledger['rows'][0]['global_position']=1
        with self.assertRaisesRegex(RuntimeError,'global-position'):
            self.check()
    def test_prior_changed_initial_refusal_or_offer_refused(self):
        self.ledger=copy.deepcopy(self.ledger);self.ledger['rows'][0]['initial_state_row']['state']='CHANGED'
        with self.assertRaisesRegex(RuntimeError,'global-position'):
            self.check()
    def test_prior_global_snapshot_missing_position_refused(self):
        self.globaldoc['rows']=self.globaldoc['rows'][:-1]
        with self.assertRaisesRegex(RuntimeError,'global672'):
            self.check()

if __name__=='__main__':
    unittest.main(verbosity=2)
