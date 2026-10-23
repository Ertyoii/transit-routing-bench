"""Synthetic test DRAFT. Not executed or qualified when this file was staged.

No campaign payload/model reads. The tiny stats fixture checks gate plumbing,
not quantile mathematics; actual use injects unchanged qualified distribution
and ratio from project_runtime8_frontier_v2.py.
"""
import copy
import unittest
from pathlib import Path

import native216_frontier_v1 as n


class StatsFixture:
    calls = []

    @classmethod
    def distribution(cls, values):
        cls.calls.append(list(values))
        # These tests use constant-valued timing groups, except the explicit
        # pooling spy. No claim to implement the production quantile helper.
        return {"count":len(values), "p95":max(values) if values else None}

    @staticmethod
    def ratio(a,b):
        return b/a if a is not None and b is not None and a > 0 else None


def point():
    return {"query":{"id":"q","max_boardings":2},"stratum":"s","raw":[{"route":"r"}],
        "final":[{"metrics":{"arrival":100,"boardings":1}}],"completed":True,"attempted":True,
        "valid_empty":False,"transit":True,"status":"complete","error":"","certificates":{"native":True}}


def profile():
    query = {"base":{"id":"q","departure":0,"latest_arrival":200,"max_boardings":2},
             "ready_window_end_inclusive":60}
    return {"query":query,"stratum":"s","complete":True,"error":"",
        "raw":{"query":query,"complete":True,"error":"",
               "transit_points":[{"latest_ready":59,"arrival":100,"boardings":1,"journey":{"r":"a"}}],
               "direct_walking":{"duration":150,"journey_at_window_start":{"r":"walk"}}},
        "final_points":[{"latest_ready":59,"validated":{"metrics":{"arrival":100,"boardings":1}}}],
        "final_direct":{"metrics":{"arrival":150,"boardings":0}},
        "every_integer_ready_time":[{"ready":i,"arrival_under_boarding_caps":[150,100,100]} for i in range(61)]}


def graph():
    paths = [{"target":"a","found":True,"duration":0,"journey":[]},
             {"target":"b","found":True,"duration":10,"journey":["a-b"]}]
    return {"requested_source":"a","requested_targets":["a","b"],"requested_maximum_duration":600,
        "complete":True,"request_shape_valid":True,"error":"",
        "raw":{"source":"a","maximum_duration":600,"paths":paths,"complete":True,"error":""},
        "final":copy.deepcopy(paths)}


def run(block=0, window=None, value=100, ident=None):
    ident = ident or "run-"+str(block)
    signature = n.typed_signature(point(),"bare_tb","familybench")
    record = {"offered_locator":"q","native_complete":True,"signature":signature,
              "flags":{"completed":True},"response_ns":value,"core_ns":value-1,
              "diagnostic_saved_output_sha256":"same",
              "published":{"published_response_ns":None}}
    out = {"id":ident,"kind":"bare_tb","driver":"familybench","product":"bare",
        "original_native_contract_id":"old","block":block,"window":window or n.WINDOWS[0],
        "runtime":{"GOGC":"50","GOMEMLIMIT":"4GiB"},"position":0,
        "source_contrast":None,"logical_call_sha256":"call","dataset_sha256":"dataset",
        "workload_sha256":"workload","expected_locators":["q"],"offered":1,
        "rows":{"q":record},"control_rows":{},"control_native_rows":{},"run_complete":True,
        "exact_signature_sha256":"answer","original_parity_status":"exact",
        "selected_router_preparation_ns":100,
        "supervisor":{"sampled_peak_process_group_rss_bytes":100},
        "measurement_envelope":{"rss_sample_interval_s":.1,"requested_cpu_affinity":"0-3","monitor_cpu_affinity":[8]}}
    return out


def all216():
    contracts = []
    for window in n.WINDOWS:
        for product,kind,contrast in (("range-candidate","range_profile",None),
                ("range-control","range_profile","frozen_native_range_control"),
                ("tad","tad",None),("corech","corech_graph",None)):
            contracts.append((product,kind,contrast,window))
    contracts += [("bare","bare_tb",None,n.WINDOWS[3]),("scoped","scoped_tp",None,n.WINDOWS[3])]
    runs,pairs = [],[]
    for index,(product,kind,contrast,window) in enumerate(contracts):
        for block in (0,1):
            for gc,heap in n.CELLS:
                ident = f"b{block}-native-old{index}-gc{gc}-{heap}"
                value = run(block,window,100,ident)
                value.update(product=product,kind=kind,source_contrast=contrast,
                    original_native_contract_id=f"old{index}",logical_call_sha256=window)
                value["runtime"]={"GOGC":gc,"GOMEMLIMIT":heap}
                runs.append(value)
                pairs.append({"baseline":f"old{index}","candidate":ident,"status":"exact"})
    return runs,pairs


class NativeContracts(unittest.TestCase):
    def test_profile_all61_grid_changes_detected(self):
        a,b=profile(),profile(); b["every_integer_ready_time"][60]["arrival_under_boarding_caps"][2]=101
        self.assertNotEqual(n.typed_signature(a,"range_profile","profilebench")["objective"],n.typed_signature(b,"range_profile","profilebench")["objective"])

    def test_profile_latest_ready_not_reduced_to_earliest_point(self):
        a,b=profile(),profile(); b["raw"]["transit_points"][0]["latest_ready"]=58
        self.assertNotEqual(n.typed_signature(a,"range_profile","profilebench")["objective"],n.typed_signature(b,"range_profile","profilebench")["objective"])

    def test_profile_direct_branch_not_omitted(self):
        a,b=profile(),profile(); b["raw"]["direct_walking"]["duration"]=151
        self.assertNotEqual(n.typed_signature(a,"range_profile","profilebench")["objective"],n.typed_signature(b,"range_profile","profilebench")["objective"])

    def test_profile_same_objective_different_witness_fails_exact(self):
        a,b=profile(),profile(); b["raw"]["transit_points"][0]["journey"]={"r":"b"}
        sa,sb=(n.typed_signature(x,"range_profile","profilebench") for x in (a,b))
        self.assertEqual(sa["objective"],sb["objective"]); self.assertNotEqual(sa["exact"],sb["exact"])

    def test_point_boarding_cap_objective(self):
        a,b=point(),point(); b["final"][0]["metrics"]["boardings"]=2
        self.assertNotEqual(n.typed_signature(a,"bare_tb","familybench")["objective"],n.typed_signature(b,"bare_tb","familybench")["objective"])

    def test_tad_two_witnesses_rejected(self):
        row=point(); row["complete"]=True; row["raw"]*=2
        with self.assertRaisesRegex(ValueError,"one EA"): n.typed_signature(row,"tad","tadbench")

    def test_graph_full_target_and_self_cells_bound(self):
        a,b=graph(),graph(); b["final"]=b["final"][1:]
        self.assertNotEqual(n.typed_signature(a,"corech_graph","corechgraphbench")["objective"],n.typed_signature(b,"corech_graph","corechgraphbench")["objective"])

    def test_graph_same_cells_different_witness_not_full_parity(self):
        a,b=graph(),graph(); b["raw"]["paths"][1]["journey"]=["a-c","c-b"]
        sa,sb=(n.typed_signature(x,"corech_graph","corechgraphbench") for x in (a,b))
        self.assertEqual(sa["objective"],sb["objective"]); self.assertNotEqual(sa["exact"],sb["exact"])

    def test_flags_certificate_change_fails(self):
        a,b=point(),point(); b["certificates"]["native"]=False
        self.assertNotEqual(n.typed_signature(a,"bare_tb","familybench")["exact"],n.typed_signature(b,"bare_tb","familybench")["exact"])

    def test_runtime_clocks_not_answer(self):
        a,b=point(),point(); a["response_ns"]=10; b["response_ns"]=20
        self.assertEqual(n.typed_signature(a,"bare_tb","familybench"),n.typed_signature(b,"bare_tb","familybench"))

    def test_even_false_unsupported_status_is_preserved(self):
        a,b=point(),point(); b["unsupported"]=False
        self.assertNotEqual(n.typed_signature(a,"bare_tb","familybench")["exact"],n.typed_signature(b,"bare_tb","familybench")["exact"])

    def test_emitted_display_change_not_ignored(self):
        a,b=point(),point(); a["display_options"]=[{"rank":1}]; b["display_options"]=[{"rank":2}]
        self.assertNotEqual(n.typed_signature(a,"scoped_tp","familybench")["exact"],n.typed_signature(b,"scoped_tp","familybench")["exact"])


class PassTransport(unittest.TestCase):
    def fixture(self):
        sha="a"*64
        payload={"algorithm":"range_raptor","repetition":0,"warmup":False,"records":[profile()]}
        descriptor={"algorithm":"range_raptor","repetition":0,"warmup":False,"file":"pass.json","sha256":sha}
        docs={"/artifact/pass.json":payload,"/artifact/pass.json.io.json":{
            "sha256":sha,"serialization_ns":2,"write_ns":3,"bytes":4,"scope":n.IO_SCOPE}}
        class IO:
            def read_path(self,path,expected_sha=None):
                if expected_sha is not None and expected_sha != sha:raise ValueError("wrong expected SHA")
                return copy.deepcopy(docs[path])
        class Inv:
            rejected=False
            calls=0
            def validate_rows(self,payload,expected,driver,argv):
                self.calls+=1
                if self.rejected:raise ValueError("synthetic offered row mismatch")
        return {"summaries":[descriptor]},docs,IO(),Inv()

    def call(self,summary,io,inv,observer=None):
        return n.load_passes(summary,Path("/artifact"),{"q":{}},"profilebench",[],"range_raptor",io,inv,observer)

    def test_unchanged_validator_is_called(self):
        summary,docs,io,inv=self.fixture(); result=self.call(summary,io,inv)
        self.assertEqual(inv.calls,1); self.assertEqual(result[3][0]["serialization_ns"],2)

    def test_bad_rows_remain_observed_before_failure(self):
        summary,docs,io,inv=self.fixture(); inv.rejected=True; seen=[]
        with self.assertRaisesRegex(ValueError,"offered row"):self.call(summary,io,inv,seen.append)
        self.assertEqual(len(seen),1)

    def test_io_sha_mismatch_rejected(self):
        summary,docs,io,inv=self.fixture(); docs["/artifact/pass.json.io.json"]["sha256"]="b"*64
        with self.assertRaisesRegex(ValueError,"sidecar pass hash"):self.call(summary,io,inv)

    def test_io_scope_mismatch_rejected(self):
        summary,docs,io,inv=self.fixture(); docs["/artifact/pass.json.io.json"]["scope"]="made up publication"
        with self.assertRaisesRegex(ValueError,"clock scope"):self.call(summary,io,inv)

    def test_duplicate_ordinary_pass_rejected(self):
        summary,docs,io,inv=self.fixture(); summary["summaries"]*=2
        with self.assertRaisesRegex(ValueError,"duplicate ordinary"):self.call(summary,io,inv)

    def test_unrequested_algorithm_rejected(self):
        summary,docs,io,inv=self.fixture(); docs["/artifact/pass.json"]["algorithm"]="csa"
        with self.assertRaisesRegex(ValueError,"algorithm differs"):self.call(summary,io,inv)

    def test_unsafe_pass_name_rejected(self):
        summary,docs,io,inv=self.fixture(); summary["summaries"][0]["file"]="../pass.json"
        with self.assertRaisesRegex(ValueError,"unsafe pass"):self.call(summary,io,inv)

    def test_missing_pass_is_not_zero_clock(self):
        summary,docs,io,inv=self.fixture(); summary["summaries"]=[]
        with self.assertRaisesRegex(ValueError,"missing/duplicate"):self.call(summary,io,inv)


class ParityAndClocks(unittest.TestCase):
    def test_complete_equal(self): self.assertEqual(n.compare(run(),run())["status"],"exact")

    def test_missing_row_not_parity(self):
        a,b=run(),run(); b["rows"]={}; b["run_complete"]=False
        self.assertEqual(n.compare(a,b)["status"],"unknown")

    def test_partial_equal_not_parity(self):
        a,b=run(),run()
        for x in (a,b): x["rows"]["q"]["native_complete"]=False; x["run_complete"]=False
        self.assertEqual(n.compare(a,b)["status"],"unknown")

    def test_partial_difference_retained(self):
        a,b=run(),run()
        for x in (a,b): x["rows"]["q"]["native_complete"]=False; x["run_complete"]=False
        b["rows"]["q"]["diagnostic_saved_output_sha256"]="different"
        self.assertTrue(n.compare(a,b)["rows"][0]["incomplete_outcome_difference"])

    def test_tp_not_bare_point(self):
        a,b=run(),run(); b["kind"]="scoped_tp"
        self.assertNotEqual(n.compare(a,b)["status"],"exact")

    def test_no_cross_workload_parity(self):
        a,b=run(),run(); b["workload_sha256"]="other"
        self.assertNotEqual(n.compare(a,b)["status"],"exact")

    def test_nonstreaming_has_no_publication(self):
        value=n.publication({"response_ns":5},"profilebench",{})
        self.assertIsNone(value["published_response_ns"]); self.assertIsNone(value["launch_to_first_available_answer_ns"])

    def test_nonstreaming_fake_publication_fails(self):
        with self.assertRaisesRegex(ValueError,"nonstreaming"): n.publication({"published_response_ns":5},"tadbench",{})

    def test_family_marker_unaccepted_without_receipt(self):
        self.assertIsNone(n.publication({"published_response_ns":5},"familybench",{})["published_response_ns"])

    def test_family_real_marker_is_not_independent_acceptance(self):
        value=n.publication({"response_ns":4,"published_response_ns":5,"serialization_ns":1},"familybench",{"publication_receipt":{"enabled":True,"valid":True},"launch_to_first_available_answer_ns":8})
        self.assertEqual(value["published_response_ns"],5); self.assertIn("not_independent",value["publication_contract"])

    def test_later_row_bad_publication_not_rescued_by_first_receipt(self):
        receipt={"publication_receipt":{"enabled":True,"valid":True}}
        n.publication({"response_ns":4,"published_response_ns":5,"serialization_ns":1},"familybench",receipt)
        with self.assertRaisesRegex(ValueError,"precedes native response"):
            n.publication({"response_ns":6,"published_response_ns":5,"serialization_ns":0},"familybench",receipt)

    def test_later_row_bad_serialization_not_rescued(self):
        with self.assertRaisesRegex(ValueError,"exceeds publication-response"):
            n.publication({"response_ns":4,"published_response_ns":5,"serialization_ns":2},"familybench",{"publication_receipt":{"enabled":True,"valid":True}})

    def test_preparation_missing_stays_unknown(self):
        self.assertIsNone(n.preparation({},"profilebench")["selected_router_preparation_ns"])

    def test_router_checker_audit_separate(self):
        value=n.preparation({"preparation":{"core_ch":{"elapsed_ns":10},"identity":{"elapsed_ns":20}},"independent_audit_ns":30},"corechgraphbench")
        self.assertEqual(value["selected_router_preparation_ns"],10); self.assertEqual(value["independent_graph_audit_ns"],30)

    def test_logical_source_call_only_ignores_binary_and_outdir(self):
        self.assertEqual(n.logical_call(["a","-timeout","3s","-out-dir","x"]),n.logical_call(["b","-timeout","3s","-out-dir","y"]))
        self.assertNotEqual(n.logical_call(["a","-timeout","3s"]),n.logical_call(["b","-timeout","4s"]))


class FrontierGates(unittest.TestCase):
    def contrast(self,left=None,right=None,evidence=None):
        left=left or [run(b,value=100,ident="a"+str(b)) for b in (0,1)]
        right=right or [run(b,value=90,ident="b"+str(b)) for b in (0,1)]
        return n.frontier_contrast(left,right,StatsFixture,evidence or {},"test")

    def test_native_gate_is_not_quality_gate(self):
        value=self.contrast(); self.assertTrue(value["native_exact_clock_gate"]); self.assertFalse(value["passes_frozen_native_response_same_cost_gate"])
        self.assertFalse(value["publication_same_cost_gate_performed"]); self.assertFalse(value["headline_publication_speedup_claim"])

    def test_original_parity_required(self):
        right=[run(b,value=90,ident="b"+str(b)) for b in (0,1)]; right[0]["original_parity_status"]="unknown"
        self.assertFalse(self.contrast(right=right)["native_exact_clock_gate"])

    def test_both_blocks_improve(self):
        right=[run(0,value=90,ident="b0"),run(1,value=99,ident="b1")]
        self.assertFalse(self.contrast(right=right)["native_exact_clock_gate"])

    def test_native_point2_deviation_rejected(self):
        right=[run(b,value=90,ident="b"+str(b)) for b in (0,1)]; right[0]["measurement_envelope"]["rss_sample_interval_s"]=.2
        self.assertFalse(self.contrast(right=right)["native_exact_clock_gate"])

    def test_rss_guard(self):
        right=[run(b,value=90,ident="b"+str(b)) for b in (0,1)]; right[1]["supervisor"]["sampled_peak_process_group_rss_bytes"]=106
        self.assertFalse(self.contrast(right=right)["native_exact_clock_gate"])

    def test_preparation_guard(self):
        right=[run(b,value=90,ident="b"+str(b)) for b in (0,1)]
        for x in right:x["selected_router_preparation_ns"]=106
        self.assertFalse(self.contrast(right=right)["native_exact_clock_gate"])

    def test_missing_rss_not_zero(self):
        right=[run(b,value=90,ident="b"+str(b)) for b in (0,1)]; right[0]["supervisor"]={}
        value=self.contrast(right=right); self.assertIsNone(value["max_whole_process_sampled_rss_ratio"]); self.assertFalse(value["native_exact_clock_gate"])

    def test_pools_raw_rows_not_window_quantiles(self):
        StatsFixture.calls=[]
        left=[run(b,w,100+i,ident=f"a{b}-{i}") for b in (0,1) for i,w in enumerate(n.WINDOWS)]
        right=[run(b,w,90+i,ident=f"b{b}-{i}") for b in (0,1) for i,w in enumerate(n.WINDOWS)]
        self.contrast(left,right)
        self.assertIn([100,101,102,103],StatsFixture.calls); self.assertIn([90,91,92,93],StatsFixture.calls)

    def test_quality_record_bound_to_exact_output(self):
        value=run(); evidence={value["id"]:{"run_id":value["id"],"kind":value["kind"],"promotion_accepted":True,
            "exact_signature_sha256":"other","independently_feasible_complete_rows":1,
            "quality_comparison_key":"key","quality_signature_sha256":"hash"}}
        self.assertFalse(n.qualify_quality(value,evidence))

    def test_exact216_all6_cells_retained(self):
        runs,pairs=all216(); value=n.combine(runs,pairs,StatsFixture,{})
        self.assertEqual(len(value["runtime_cells"]),36); self.assertEqual(len(value["runtime_contrasts"]),180)
        self.assertEqual(len(value["frozen_range_source_contrasts"]),6); self.assertEqual(len(value["corech_identity_controls"]),48)
        self.assertEqual(value["accepted_native_response_same_cost_edges"],[])

    def test_incomplete216_rejected(self):
        runs,pairs=all216()
        with self.assertRaisesRegex(ValueError,"216"):n.combine(runs[:-1],pairs,StatsFixture,{})

    def test_duplicate_runtime_tuple_rejected(self):
        runs,pairs=all216(); runs[1]["runtime"]=copy.deepcopy(runs[0]["runtime"])
        with self.assertRaisesRegex(ValueError,"18x6x2"):n.combine(runs,pairs,StatsFixture,{})

    def test_original_unknown_does_not_disappear(self):
        runs,pairs=all216(); pairs[0]["status"]="unknown"
        value=n.combine(runs,pairs,StatsFixture,{})
        self.assertEqual(value["original_pair_statuses"]["unknown"],1)

    def test_substituted_original_baseline_rejected(self):
        runs,pairs=all216(); pairs[0]["baseline"]="not-this-original"
        with self.assertRaisesRegex(ValueError,"baseline binding"):n.combine(runs,pairs,StatsFixture,{})


if __name__ == "__main__":
    unittest.main()
