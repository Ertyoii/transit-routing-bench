#!/usr/bin/env python3
"""Synthetic-only tests. Do not run during headline measurement barriers."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).with_name("summarize_native_auxiliary_v1.py")
SPEC = importlib.util.spec_from_file_location("native_inventory", SOURCE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def query():
    return {"id": "q", "origin": "a", "destination": "b", "departure": 10,
            "latest_arrival": 100, "max_boardings": 4}


def item():
    return {"stratum": "geographic", "query": query()}


def point_row():
    return dict(item(), raw=[], final=[], completed=True, attempted=True,
                valid_empty=True, transit=False, status="complete", certificates={"ea": True},
                core_ns=5, response_ns=9)


def field_snapshot(row):
    return {row["query"]["id"]: {"completed": row.get("completed") is True,
            "fields": {key: json.dumps(row.get(key), sort_keys=True) for key in m.PARITY_FIELDS}}}


class NativeInventoryTests(unittest.TestCase):
    def test_driver_algorithms_do_not_rely_on_nonexistent_ultra_flag(self):
        self.assertEqual(m.algorithm(["ultrabench"], "ultrabench"), "ultra_raptor")
        self.assertEqual(m.algorithm(["corechgraphbench"], "corechgraphbench"), "core_ch")
        self.assertEqual(m.algorithm(["tadbench", "-algorithms", "tad"], "tadbench"), "tad")
        with self.assertRaises(ValueError):
            m.algorithm(["profilebench", "-algorithms", "profile_csa,range_raptor"], "profilebench")

    def test_no_measurements_means_null_not_zero(self):
        self.assertEqual(m.distribution([])["count"], 0)
        self.assertIsNone(m.distribution([])["p50"])
        self.assertEqual(m.distribution([1, 3])["p95"], 3)

    def test_complete_source_binding_is_required(self):
        p = {key: "a"*64 for key in ("build_source_sha256", "runtime_tree_sha256", "routing_source_sha256", "executable_sha256")}
        p.update(source_binding="embedded_build_source", runtime_matches_build=True)
        summary = {"algorithm": "trex", "dataset_sha256": "d", "queries_sha256": "w", "provenance": p}
        command = {"binary": {"sha256": "a"*64}}
        role = {"go_source_hash_sha256": "a"*64, "routing_file_list_sha256": "a"*64}
        m.validate_manifest(summary, command, role, "familybench", "trex", "d", "w")
        for key, value in (("runtime_matches_build", False), ("executable_sha256", "b"*64), ("routing_source_sha256", "b"*64), ("source_binding", "unverified_runtime_tree")):
            changed = copy.deepcopy(summary); changed["provenance"][key] = value
            with self.assertRaises(ValueError):
                m.validate_manifest(changed, command, role, "familybench", "trex", "d", "w")

    def test_legacy_manifest_workload_hash_alias(self):
        p = {key: "a"*64 for key in ("build_source_sha256", "runtime_tree_sha256", "routing_source_sha256", "executable_sha256")}
        p.update(source_binding="embedded_build_source", runtime_matches_build=True)
        m.validate_manifest({"dataset_sha256": "d", "workload_sha256": "w", "provenance": p},
                            {"binary": {"sha256": "a"*64}}, {"go_source_hash_sha256": "a"*64, "routing_file_list_sha256": "a"*64},
                            "tadbench", "tad", "d", "w")

    def test_prep_constructor_names(self):
        for driver, key in (("tadbench", "tad"), ("profilebench", "range_raptor")):
            self.assertEqual(m.preparation_state({"preparation": {key: {"error": "", "elapsed_ns": 3}}}, driver, "unused"), "complete")
        self.assertEqual(m.preparation_state({"phase": "independent_audit"}, "corechgraphbench", "core_ch"), "independent_audit_failed")
        self.assertEqual(m.preparation_state({"preparation": {"complete": False, "status": "unsupported"}}, "familybench", "x"), "unsupported")

    def test_profile_derivation_keeps_fixed_horizon_and_all61_readiness(self):
        expected = m.expected_items({"items": [item()]}, "profilebench", ["x", "-point-workload", "-ready-span-seconds", "60"])
        q = expected["q"]["query"]
        self.assertEqual(q["base"], query())
        self.assertEqual(q["ready_window_end_inclusive"], 70)
        row = dict(expected["q"], complete=True, core_ns=4, response_ns=7,
                   every_integer_ready_time=[{"ready": t, "arrival_under_boarding_caps": [99]*5} for t in range(10, 71)])
        m.validate_rows({"records": [row]}, expected, "profilebench", ["x"])
        row["every_integer_ready_time"].pop()
        with self.assertRaisesRegex(ValueError, "readiness grid"):
            m.validate_rows({"records": [row]}, expected, "profilebench", ["x"])

    def test_profile_horizon_violation_is_rejected(self):
        with self.assertRaises(ValueError):
            m.expected_items({"items": [item()]}, "profilebench", ["x", "-point-workload", "-ready-span-seconds", "91"])

    def test_point_rows_bind_every_offered_byte(self):
        expected = {"q": item()}
        row = point_row()
        m.validate_rows({"records": [row]}, expected, "familybench", ["x"])
        row["query"]["departure"] += 1
        with self.assertRaises(ValueError):
            m.validate_rows({"records": [row]}, expected, "familybench", ["x"])

    def test_not_run_placeholder_is_not_timed_or_completed(self):
        row = dict(item(), attempted=False, completed=False, raw=[], final=[], valid_empty=False,
                   status="not_run_preparation_unavailable", core_ns=None, response_ns=0)
        m.validate_rows({"records": [row]}, {"q": item()}, "familybench", ["x"])
        row["valid_empty"] = True
        with self.assertRaises(ValueError):
            m.validate_rows({"records": [row]}, {"q": item()}, "familybench", ["x"])

    def test_missing_duplicate_and_extra_rows_fail_closed(self):
        for records in ([], [point_row(), point_row()]):
            with self.assertRaises(ValueError):
                m.validate_rows({"records": records}, {"q": item()}, "familybench", ["x"])

    def test_tad_cannot_claim_a_frontier(self):
        row = dict(item(), complete=True, raw=[{}, {}], final=[], core_ns=1, response_ns=2)
        with self.assertRaisesRegex(ValueError, "one EA witness"):
            m.validate_rows({"records": [row]}, {"q": item()}, "tadbench", ["x"])
        row["complete"] = False; row["error"] = "multiple representatives for single EA output"
        m.validate_rows({"records": [row]}, {"q": item()}, "tadbench", ["x"])

    def test_semantic_refusal_is_not_budget_infeasibility(self):
        report = m.preparation_diagnosis({"preparation": {"ultra": {"complete": False, "error": "capability: transfer rules unsupported"}}}, "ultrabench", "incomplete")
        self.assertEqual(report["classification"], "explicit_semantic_capability_refusal")

    def test_validation_failure_retains_frozen_offered_denominator_and_supervisor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workload = root / "queries.json"
            workload.write_text(json.dumps({"items": [item()]}))
            run = root / "run"; run.mkdir(); (run / "result.json").write_text(json.dumps({"ok": False, "termination": "timeout", "process_wall_s": 3}))
            spec = {"id": "run", "argv": ["familybench-x", "-queries", str(workload)]}
            frozen = {"input_files": [{"path": str(workload), "sha256": m.digest(workload)}]}
            context = m.failure_context(root, spec, frozen, {})
            self.assertEqual(context["offered"], 1)
            self.assertEqual(context["unavailable"], 1)
            self.assertIsNone(context["attempted"])
            self.assertEqual(context["supervisor"]["termination"], "timeout")

    def test_ultra_mandatory_control_is_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row = dict(item(), complete=True, raw=[], final=[], core_ns=1, response_ns=2)
            descs = []
            for alg in ("ultra_raptor", "unaccelerated_raptor"):
                payload = {"algorithm": alg, "repetition": 0, "warmup": False, "records": [row]}
                path = root / (alg + ".json"); path.write_text(json.dumps(payload))
                descs.append({"algorithm": alg, "repetition": 0, "warmup": False, "file": path.name, "sha256": m.digest(path)})
            with self.assertRaisesRegex(ValueError, "mandatory native control"):
                m.load_passes({"passes": descs[:1]}, root, {"q": item()}, "ultrabench", ["x"], "ultra_raptor", {})
            selected, controls, _ = m.load_passes({"passes": descs}, root, {"q": item()}, "ultrabench", ["x"], "ultra_raptor", {})
            self.assertEqual((len(selected), len(controls)), (1, 1))
            with self.assertRaises(ValueError):
                m.load_passes({"passes": descs + descs[1:]}, root, {"q": item()}, "ultrabench", ["x"], "ultra_raptor", {})

    def test_graph_rows_keep_sources_targets_caps_self_cells(self):
        anchors = ["a", "b"]
        rows = []
        for source in anchors:
            targets = list(reversed(anchors))
            paths = [{"target": t, "found": source == t} for t in targets]
            rows.append(dict(requested_source=source, requested_targets=targets, requested_maximum_duration=600,
                             request_shape_valid=True, complete=True, core_ns=4, response_ns=8,
                             raw={"source": source, "maximum_duration": 600, "paths": paths}, final=paths))
        m.validate_rows({"records": rows}, anchors, "corechgraphbench", ["x"])
        rows[0]["final"].reverse()
        with self.assertRaises(ValueError):
            m.validate_rows({"records": rows}, anchors, "corechgraphbench", ["x"])

    def test_process_success_is_not_native_completion(self):
        summary = {"success": True}
        self.assertEqual(m.classify_failure(summary, {"ok": True}, "unsupported", {}), "native_preparation_unsupported")
        self.assertEqual(m.classify_failure(summary, {"ok": True}, "complete", {"unsupported": 60}), "query_partial_or_declined")
        self.assertEqual(m.classify_failure(None, {"termination": "sampled_rss_safety_stop"}, "unknown", {}), "sampled_rss_safety_stop")

    def test_compact_trex_equal_argv_and_native_fields(self):
        row = point_row()
        a = {"argv": ["binary-a", "-algorithm", "trex", "-max-transfers", "25", "-out-dir", "a"],
             "record_fields": field_snapshot(row), "complete": True, "preparation_complete": True,
             "supervisor_ok": True, "manifest_success": True}
        b = copy.deepcopy(a); b["argv"][0] = "binary-b"; b["argv"][-1] = "b"
        self.assertEqual(m.compare_trex(b, a)["status"], "exact")
        b["record_fields"]["q"]["fields"]["certificates"] = "different"
        self.assertEqual(m.compare_trex(b, a)["status"], "mismatch")
        b["record_fields"] = field_snapshot(row); b["complete"] = False
        self.assertEqual(m.compare_trex(b, a)["status"], "unknown")
        b["argv"][4] = "100"
        with self.assertRaises(ValueError):
            m.compare_trex(b, a)

    def test_incomplete_differences_never_count_exact(self):
        row = point_row(); row["completed"] = False
        a = {"argv": ["a"], "record_fields": field_snapshot(row), "complete": False,
             "preparation_complete": True, "supervisor_ok": True, "manifest_success": True}
        b = copy.deepcopy(a); b["record_fields"]["q"]["fields"]["status"] = "changed"
        check = m.compare_trex(b, a)
        self.assertEqual(check["status"], "unknown")
        self.assertEqual(len(check["incomplete_outcome_differences"]), 1)

    def test_pass_digest_and_safe_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); payload = {"algorithm": "trex", "repetition": 0, "warmup": False, "records": [point_row()]}
            path = root / "p.json"; path.write_text(json.dumps(payload))
            desc = {"repetition": 0, "warmup": False, "file": "p.json", "sha256": m.digest(path)}
            selected, _, _ = m.load_passes({"passes": [desc]}, root, {"q": item()}, "familybench", ["x"], "trex", {})
            self.assertEqual(len(selected), 1)
            for change in ({"sha256": "0"*64}, {"file": "../p.json"}):
                bad = dict(desc, **change)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    m.load_passes({"passes": [bad]}, root, {"q": item()}, "familybench", ["x"], "trex", {})


if __name__ == "__main__":
    unittest.main()
