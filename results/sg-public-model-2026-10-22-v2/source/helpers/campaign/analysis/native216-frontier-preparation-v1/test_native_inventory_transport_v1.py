"""Synthetic API-wire tests only; no actual canonical path is accessed."""
import copy
from pathlib import Path
import unittest

import native216_frontier_v1 as n
from native_inventory_transport_v1 import InventoryProxy
from test_native216_frontier_v1 import point


class ProxyWire(unittest.TestCase):
    def fixture(self):
        campaign=Path("/tmp/synthetic-native-new");rid="actual-new-id";root=campaign/rid
        workload="/tmp/synthetic-workload.json";dataset="/tmp/synthetic-model.json"
        descriptor={"file":"pass.json","sha256":"a"*64,"algorithm":"trip_based","repetition":0,"warmup":False}
        summary={"success":True,"preparation":{"elapsed_ns":10,"complete":True},"passes":[descriptor]}
        docs={str(root/"command.json"):{},str(root/"result.json"):{"ok":True},
            workload:{"dataset_sha256":"model","items":[{"query":point()["query"],"stratum":"s"}]},
            str(root/"artifact"/"summary.json"):summary,
            str(root/"artifact"/"pass.json"):{"algorithm":"trip_based","repetition":0,"warmup":False,"records":[point()]},
            str(root/"artifact"/"pass.json.io.json"):{"sha256":"a"*64,"serialization_ns":2,"write_ns":3,"bytes":4,"scope":n.IO_SCOPE}}
        class IO:
            def __init__(self):self.bindings={}
            def read_path(self,path,expected_sha=None):return copy.deepcopy(docs[path])
        class Inv:
            calls=0
            def validate_envelope(self,*args):
                return [],"familybench",{}, {workload:{"sha256":"workload"},dataset:{"sha256":"model"}}
            def flag(self,argv,key):return {"-queries":workload,"-dataset":dataset}[key]
            def expected_items(self,*args):return {"q":{}}
            def algorithm(self,*args):return "trip_based"
            def validate_manifest(self,*args):self.calls+=1
            def preparation_state(self,*args):return "complete"
            def preparation_diagnosis(self,*args):return {"classification":None}
            def validate_rows(self,*args):self.calls+=1
            def row_status(self,row,driver):return row["status"]
            def classify_failure(self,*args):return "native_artifacts_complete_not_independent_optimality"
        io,inv=IO(),Inv()
        return campaign,{"id":rid,"family":"trip_based","window":"window","variant_id":"variant"},docs,io,inv,InventoryProxy(inv,io,n)

    def test_inspect_uses_real_new_identity_and_shared_validators(self):
        campaign,spec,docs,io,inv,proxy=self.fixture()
        output,detail=proxy.inspect_run(campaign,spec,{},io.bindings)
        self.assertEqual(output["id"],"actual-new-id");self.assertEqual(output["native_complete"],1)
        self.assertEqual(inv.calls,2);self.assertIsNone(detail);self.assertIsNone(output["analysis_binding_error"])
        self.assertFalse(output["quality_acceptance"])

    def test_pass_api_preserves_legacy_return_shape_without_raw_reopen(self):
        campaign,spec,docs,io,inv,proxy=self.fixture();artifact=campaign/spec["id"]/"artifact"
        selected,controls,diagnostics=proxy.load_passes(docs[str(artifact/"summary.json")],artifact,{"q":{}},"familybench",[],"trip_based",io.bindings)
        self.assertEqual(selected[0]["algorithm"],"trip_based");self.assertEqual(selected[0]["records"][0]["query"]["id"],"q")
        self.assertEqual(controls,[]);self.assertEqual(diagnostics,[])

    def test_missing_transport_document_is_analysis_error_not_native_failure(self):
        campaign,spec,docs,io,inv,proxy=self.fixture();del docs[str(campaign/spec["id"]/"artifact"/"summary.json")]
        output,_=proxy.inspect_run(campaign,spec,{},io.bindings)
        self.assertEqual(output["status"],"analysis_binding_or_transport_error_not_native_family_failure")

    def test_separate_stale_binding_map_rejected(self):
        campaign,spec,docs,io,inv,proxy=self.fixture()
        with self.assertRaisesRegex(ValueError,"shared canonical IO"):proxy.inspect_run(campaign,spec,{}, {})


if __name__=="__main__":unittest.main()
