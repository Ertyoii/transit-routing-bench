#!/usr/bin/env python3
"""Synthetic only. All data/outputs are owned /tmp fixtures; no campaign payload."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).absolute().parent
spec = importlib.util.spec_from_file_location('compact_retention_fixture', HERE/'compact_retention.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


class RetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='sg-cap-compact-fixtures-', dir='/tmp')
        cls.base = Path(cls.temp.name); cls.out_count = 0
        def write(path, obj, lines=False):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b''.join(c.encoded(x) for x in obj) if lines else c.encoded(obj))
            return c.reference(path)
        cls.write = staticmethod(write)
        window = 'weekday-evening-20261020'; rows=[]; accepted=[]; metrics=[]; quality=[]; inputs={}
        for i in range(50):
            rid='original-run-%02d'%i; campaign=cls.base/'original'; alias=cls.base/'view'
            role='cap_target' if i<24 else 'initial_control' if i<46 else 'source_B_control' if i<48 else 'methodology_control'
            k=5 if i==49 else 3
            records=[]
            for qid in range(60):
                clocks={name:100000*i+100*qid+j for j,name in enumerate(c.CLOCKS)}
                # Missing measurements remain null, never synthetic zero.
                if qid==59:clocks.pop('core_ns')
                records.append(dict(query={'id':qid}, attempted=True,completed=qid!=0,
                    transit=qid!=0, valid_empty=False, **clocks))
                for stage in ('raw','final','display'):
                    quality.append(dict(run=rid,query_id=qid,stage=stage,delivery_k=k,
                        complete=qid!=0,status='unresolved' if qid==0 else 'ok',
                        common_pool_cohort='pool_has_transit'))
            pref=write(campaign/rid/'artifact/pass.json', {'records':records})
            # Proves warmup/forced files are not touched, even when absent.
            summary={'passes':[dict(file='pass.json',sha256=pref['sha256']),
                dict(file='absent-warmup.json',sha256='a'*64,warmup=True),
                dict(file='absent-forced.json',sha256='b'*64,forced=True)]}
            sref=write(campaign/rid/'artifact/summary.json',summary)
            inputs[str(alias/rid/'artifact/summary.json')]=sref['sha256']
            inputs[str(alias/rid/'artifact/pass.json')]=pref['sha256']
            rows.append(dict(id=rid,role=role,window=window,original_campaign=str(campaign),
                offered=60,original_summary_state={'summary':sref,'absence_reason':None}))
            accepted.append(dict(run_id=rid,role=role,ordinary_offers=60,delivery_k=k,
                original=str(campaign/rid),view=str(alias/rid),summary=sref))
            metrics.append(dict(id=rid,campaign=str(alias),window=window,delivery_k=k,offered=60,
                completed=59,statuses={'ok':59,'unresolved':1},preparation=dict(complete=True,
                    elapsed_ns=123,allocated_bytes=456,large_omitted=['\\\"'+'x'*70000]),
                checker_preparation=None,quality_preparation=dict(complete=False,error='failed',reason='unknown'),
                first_offered_independent_status='unresolved',first_marker_matches_first_offered_query=False,
                first_published_native_row_accepted=False,accepted_native_launch_to_first_available_answer_ns=None,
                sampled_peak_rss_bytes=12345,all_attempted_response_ns={'p50':123,'p95':456},
                unexpected_future_field={'keep':'verbatim ∆','nested':[False,None,4]}))
        cls.original_metrics=copy.deepcopy(metrics)
        outputs={name:write(cls.base/'v4'/name,[]) for name in c.V4_FILES}
        outputs['METRICS_BY_RUN.json']=write(cls.base/'v4/METRICS_BY_RUN.json',metrics)
        outputs['QUALITY_ROWS.jsonl']=write(cls.base/'v4/QUALITY_ROWS.jsonl',quality,True)
        outputs['REPORT.json']=write(cls.base/'v4/REPORT.json',dict(schema='sg-independent-v2-feasible-safe-fill-v4',
            runs=50,offered_run_rows=3000,serving_cohort_offered={'3':2940,'5':60},inputs=inputs))
        metadata={name:write(cls.base/'meta'/(name+'.json'),{}) for name in c.METADATA}
        metadata['run_roles']=write(cls.base/'meta/run_roles.json',dict(rows=rows,all_metric_processes=50,all_metric_offers=3000))
        metadata['input_reader_acceptance']=write(cls.base/'meta/input_reader_acceptance.json',dict(
            status='INDEPENDENTLY_ACCEPTED_INPUT_READER_ONLY',window=window,all_processes=50,
            ordinary_offers=3000,runs=accepted))
        metadata['accepted_binding']=write(cls.base/'meta/accepted_binding.json',dict(
            resource_request={'path':'/never-open/native-model.json','sha256':'0'*64,'bytes':1},
            references=[{'path':'/never-open/native960.json','sha256':'1'*64,'bytes':2}]))
        cls.request=dict(schema='sg-cap-compact-retention-request-v1',window=window,outputs=outputs,metadata=metadata)
        cls.request_ref=write(cls.base/'request.json',cls.request)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_build(self, request=None):
        type(self).out_count += 1
        number=type(self).out_count; out=self.base/('output-%02d'%number)
        ref=self.request_ref if request is None else self.write(self.base/('request-%02d.json'%number),request)
        return c.build(ref,out),out

    def test_full_synthetic_equivalence_50x60_and_null_clocks(self):
        before={p:c.reference(p) for p in self.base.glob('original/*/artifact/*.json')}
        result,out=self.run_build()
        self.assertLessEqual(result['total_bytes'],5_000_000)
        self.assertEqual(result['serving_cohort_offered'],{'3':2940,'5':60})
        metrics=json.loads((out/'COMPACT_METRICS_BY_RUN.json').read_text())
        self.assertEqual([r['id'] for r in metrics],[r['id'] for r in self.original_metrics])
        for original,compact in zip(self.original_metrics,metrics):
            self.assertEqual({k:v for k,v in compact.items() if k not in (*c.PHASES,'_source_metrics')},
                             {k:v for k,v in original.items() if k not in c.PHASES})
            for phase in c.PHASES:
                if original[phase] is None:self.assertIsNone(compact[phase])
                else:
                    self.assertEqual({k:compact[phase][k] for k in c.PHASE_FIELDS},
                                     {k:original[phase].get(k) for k in c.PHASE_FIELDS})
                    self.assertEqual(compact[phase]['_source_metrics']['run_id'],original['id'])
        ordinary=[json.loads(x) for x in (out/'ORDINARY_ACTUAL_ROWS.jsonl').read_text().splitlines()]
        self.assertEqual(len(ordinary),3000)
        self.assertEqual(len({(r['run'],r['query_id']) for r in ordinary}),3000)
        self.assertEqual(sum(not r['independently_complete'] for r in ordinary),50)
        self.assertEqual(sum(r['core_ns'] is None for r in ordinary),50)
        self.assertEqual(ordinary[1]['response_ns'],100)
        self.assertEqual(ordinary[1]['published_response_ns'],101)
        self.assertEqual(before,{p:c.reference(p) for p in before})

    def changed_metrics(self, rows):
        request=copy.deepcopy(self.request)
        type(self).out_count += 1
        request['outputs']['METRICS_BY_RUN.json']=self.write(
            self.base/('mutated-%d'%self.out_count)/'METRICS_BY_RUN.json',rows)
        return request

    def test_duplicate_metric_id_rejected(self):
        rows=copy.deepcopy(self.original_metrics);rows[1]=copy.deepcopy(rows[0])
        with self.assertRaisesRegex(c.Stop,'Duplicate V4 metric id'):
            self.run_build(self.changed_metrics(rows))

    def test_missing_metric_field_rejected(self):
        rows=copy.deepcopy(self.original_metrics);del rows[0]['preparation']
        with self.assertRaisesRegex(c.Stop,'Missing required metric field'):
            self.run_build(self.changed_metrics(rows))

    def test_changed_reference_rejected(self):
        request=copy.deepcopy(self.request);request['outputs']['VALIDATION_ERRORS.json']['sha256']='0'*64
        with self.assertRaisesRegex(c.Stop,'Changed bound input'):
            self.run_build(request)

    def test_missing_companion_reference_rejected(self):
        request=copy.deepcopy(self.request);del request['outputs']['ORACLE_COMPARISONS.json']
        with self.assertRaisesRegex(c.Stop,'all eleven'):
            self.run_build(request)

    def test_create_only_and_precounter_guard(self):
        _,out=self.run_build()
        with self.assertRaisesRegex(c.Stop,'Create-only'):
            c.build(self.request_ref,out)
        with patch.object(c,'MAX_OUTPUT_BYTES',100):
            with self.assertRaisesRegex(c.Stop,'Exact prospective compact output needs'):
                self.run_build()

    def test_linear_reader_ast_exact_accepted_source(self):
        source=Path('/workspace/shared/sg-coldstart/campaign-v2-20261021/analysis/lossless-storage-v1/runtime-window-consumer-v2/consumer.py')
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),c.READER_SOURCE_SHA256)
        def node(path):
            return next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='iter_array')
        self.assertEqual(ast.dump(node(source)),ast.dump(node(HERE/'compact_retention.py')))

    def test_linear_reader_boundary_escaping_and_negatives(self):
        path=self.base/'linear-reader-fixture.json'
        raw='[{"id":"old","id":"last","nested":[{"text":'+json.dumps('a'*65525+'\\\"{}[] ∆')+'}]}]'
        path.write_text(raw)
        self.assertEqual(list(c.iter_array(path)),json.loads(raw))
        for bad in ('[{"id":1},]','[{"id":1}] false','[{"id":1}','[1]'):
            path.write_text(bad)
            with self.assertRaises(c.Stop):list(c.iter_array(path))

if __name__=='__main__':unittest.main(verbosity=2)
