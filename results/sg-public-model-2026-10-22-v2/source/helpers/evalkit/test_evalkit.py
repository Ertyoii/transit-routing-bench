"""Synthetic contract tests only: no SG authenticity or exact-search claims."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import evalkit as e


def dataset():
    return {"schema_version": "0.2", "id": "synthetic-contract-only", "time_zone": "Asia/Singapore",
            "service_date": "2026-10-20", "data_kind": "original_synthetic",
            "stops": [{"id": x, "accessible": "yes"} for x in ("O", "X", "Y", "D", "E")],
            "trips": [{"id": x, "route_id": r, "accessible": "yes"} for x, r in (("a", "A"), ("b", "B"), ("s", "S"), ("s2", "S"))],
            "connections": [
                {"id": "ax", "trip_id": "a", "sequence": 0, "from": "O", "to": "X", "departure": 10, "arrival": 20, "pickup": True, "dropoff": True},
                {"id": "bd", "trip_id": "b", "sequence": 0, "from": "X", "to": "D", "departure": 30, "arrival": 40, "pickup": True, "dropoff": True},
                {"id": "slow", "trip_id": "s", "sequence": 0, "from": "O", "to": "D", "departure": 15, "arrival": 70, "pickup": True, "dropoff": True},
                {"id": "slow2", "trip_id": "s2", "sequence": 0, "from": "O", "to": "D", "departure": 16, "arrival": 70, "pickup": True, "dropoff": True}],
            "footpaths": [{"id": "ox", "from": "O", "to": "X", "duration": 5, "accessible": "yes"},
                          {"id": "od", "from": "O", "to": "D", "duration": 80, "accessible": "yes"}],
            "transfers": []}


def query(qid="q", dest="D", dep=0):
    return {"id": qid, "origin": "O", "destination": dest, "departure": dep, "latest_arrival": 300,
            "transfer_buffer": 0, "max_walk_seconds": 100, "max_boardings": 4, "max_legs": 20, "accessible_only": False,
            "walking_limits": {"access_seconds": 100, "egress_seconds": 100, "transfer_seconds": 100, "direct_seconds": 100}}


def journey(*refs, data=None, departure=0):
    data = data or dataset()
    rides = {r["id"]: r for r in data["connections"]}
    walks = {r["id"]: r for r in data["footpaths"]}
    now, legs = departure, []
    for ref in refs:
        if ref in rides:
            r = rides[ref]
            legs.append({"kind": "ride", "ref": ref, "departure": r["departure"], "arrival": r["arrival"]})
        else:
            r = walks[ref]
            legs.append({"kind": "walk", "ref": ref, "departure": now, "arrival": now+r["duration"]})
        now = legs[-1]["arrival"]
    return {"legs": legs}


def claim(checker, q, j):
    checked = checker.check(q, j)
    return {k: checked[k] for k in ("journey", "identity", "metrics")}


def config():
    cfg = copy.deepcopy(e.DEFAULT_CONFIG)
    cfg["bootstrap"]["replicates"] = 100
    return cfg


def write(path, value):
    path.write_text(json.dumps(value, indent=2)+"\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row(checker, q, js, complete=True, status=None):
    final = [claim(checker, q, j) for j in js]
    return {"query": q, "stratum": "original_synthetic", "raw": js, "final": final,
            "display_options": {str(k): {"k": k, "candidate_count": len(final), "ranking_transfer_penalty_seconds": 300,
                                         "global_optimality_claim": False,
                                         "options": [{"journey": j, "actual_duration_seconds": j["metrics"]["arrival"]-q["departure"],
                                                      "transfer_penalty_cost_seconds": 300*j["metrics"]["transfers"],
                                                      "generalized_score_seconds": j["metrics"]["arrival"]-q["departure"]+300*j["metrics"]["transfers"]}
                                                     for j in sorted(final, key=lambda j: e.presentation_key(j, q["departure"], 300))[:k]]} for k in (3, 5)},
            "completed": complete, "attempted": True, "valid_empty": complete and not final,
            "transit": complete and any(j["metrics"]["boardings"] for j in final),
            "status": status or ("complete" if complete else "deadline"),
            "certificates": {}, "response_ns": 100, "core_ns": None, "quality_ns": 10, "validation_rank_ns": 20}


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.d, self.q = dataset(), query()
        self.c = e.Checker(self.d)

    def test_metrics_and_claims(self):
        result = self.c.check(self.q, journey("ax", "bd"))
        self.assertEqual(result["metrics"]["boardings"], 2)
        self.assertEqual(result["metrics"]["transfers"], 1)
        self.assertEqual(result["duration_seconds"], 40)
        obj = claim(self.c, self.q, journey("ax", "bd"))
        obj["metrics"]["arrival"] -= 1
        with self.assertRaisesRegex(e.ValidationError, "metrics mismatch"):
            self.c.check(self.q, obj)

    def test_access_walk_not_transfer(self):
        result = self.c.check(self.q, journey("ox", "bd"))
        self.assertEqual(result["metrics"]["access_walking_seconds"], 5)
        self.assertEqual(result["metrics"]["transfers"], 0)
        self.q["walking_limits"]["access_seconds"] = 4
        with self.assertRaisesRegex(e.ValidationError, "walking block"):
            self.c.check(self.q, journey("ox", "bd"))

    def test_direct_cap(self):
        self.assertEqual(self.c.check(self.q, journey("od"))["metrics"]["direct_walking_seconds"], 80)
        self.q["walking_limits"]["direct_seconds"] = 79
        with self.assertRaisesRegex(e.ValidationError, "direct walking"):
            self.c.check(self.q, journey("od"))

    def test_absorbing_destination(self):
        self.d["footpaths"].append({"id": "do", "from": "D", "to": "O", "duration": 1, "accessible": "yes"})
        with self.assertRaisesRegex(e.ValidationError, "absorbing"):
            e.Checker(self.d).check(self.q, journey("slow", "do", data=self.d))

    def test_unknown_accessibility_is_not_yes(self):
        self.d["trips"][0]["accessible"] = "unknown"
        self.q["accessible_only"] = True
        with self.assertRaisesRegex(e.ValidationError, "trip accessibility"):
            e.Checker(self.d).check(self.q, journey("ax", "bd"))

    def test_transfer_minimum_overlap_walking(self):
        self.d["footpaths"].append({"id": "xy", "from": "X", "to": "Y", "duration": 10, "accessible": "yes"})
        self.d["connections"][1].update(**{"from": "Y", "departure": 35, "arrival": 50})
        self.q["transfer_buffer"] = 15
        result = e.Checker(self.d).check(self.q, journey("ax", "xy", "bd", data=self.d))
        self.assertEqual(result["metrics"]["transfer_walking_seconds"], 10)
        self.d["connections"][1]["departure"] = 34
        with self.assertRaisesRegex(e.ValidationError, "transfer rule"):
            e.Checker(self.d).check(self.q, journey("ax", "xy", "bd", data=self.d))

    def test_transfer_precedence_and_ambiguity(self):
        self.d["transfers"] = [{"id": "forbid", "from_stop": "X", "to_stop": "X", "type": 3},
                                {"id": "trip-allow", "from_stop": "X", "to_stop": "X", "from_trip": "a", "to_trip": "b", "type": 0}]
        self.assertEqual(e.Checker(self.d).check(self.q, journey("ax", "bd"))["metrics"]["arrival"], 40)
        self.d["transfers"].pop()
        with self.assertRaisesRegex(e.ValidationError, "transfer rule"):
            e.Checker(self.d).check(self.q, journey("ax", "bd"))
        self.d["stops"].append({"id": "station", "location_type": 1, "accessible": "yes"})
        self.d["stops"][1]["parent_station"] = "station"
        self.d["transfers"].append({"id": "parent", "from_stop": "station", "to_stop": "X", "type": 0})
        with self.assertRaisesRegex(e.ValidationError, "ambiguous"):
            e.Checker(self.d).check(self.q, journey("ax", "bd"))

    def test_continuing_vehicle_not_reboarding(self):
        self.d["connections"][1].update(trip_id="a", sequence=1, pickup=False)
        self.d["connections"][0]["dropoff"] = False
        result = e.Checker(self.d).check(self.q, journey("ax", "bd", data=self.d))
        self.assertEqual(result["metrics"]["boardings"], 1)
        self.assertEqual(len(json.loads(result["pattern"])), 1)

    def test_over_24h_and_literal_departure(self):
        for r in self.d["connections"]:
            r["departure"] += 86400
            r["arrival"] += 86400
        self.q.update(departure=86410, latest_arrival=86700)
        result = e.Checker(self.d).check(self.q, journey("ax", "bd", data=self.d))
        self.assertEqual(result["duration_seconds"], 30)
        self.q["departure"] += 1
        with self.assertRaisesRegex(e.ValidationError, "leg departure"):
            e.Checker(self.d).check(self.q, journey("ax", "bd", data=self.d))

    def test_patterns_ignore_trip_instances_but_not_identity(self):
        a = self.c.check(self.q, journey("slow"))
        b = self.c.check(self.q, journey("slow2"))
        self.assertEqual(a["pattern"], b["pattern"])
        self.assertNotEqual(a["identity"], b["identity"])
        self.assertEqual(len(e.legitimate_alternatives([a, b], config()["profiles"], 300)), 2)

    def test_duplicate_ids_rejected(self):
        self.d["stops"].append(self.d["stops"][0])
        with self.assertRaisesRegex(e.ValidationError, "duplicate"):
            e.Checker(self.d)


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.d, self.cfg = dataset(), config()
        self.c = e.Checker(self.d)
        self.qs = [query("q1"), query("q2", "E")]
        self.ds = self.root/"data.json"
        self.qp = self.root/"queries.json"
        self.dh = write(self.ds, self.d)
        self.wh = write(self.qp, {"dataset_sha256": self.dh, "items": [{"stratum": "original_synthetic", "query": q} for q in self.qs]})

    def tearDown(self):
        self.tmp.cleanup()

    def run_dir(self, name, fail=False, corrupt=False, reps=2):
        directory = self.root/name
        directory.mkdir()
        passes = []
        for rep in range(reps):
            records = [row(self.c, self.qs[0], [journey("slow")], complete=not fail), row(self.c, self.qs[1], [])]
            if corrupt:
                records[0]["final"][0]["metrics"]["arrival"] = 0
            filename = f"pass-{rep:02d}.json"
            digest = write(directory/filename, {"algorithm": name, "repetition": rep, "warmup": False, "records": records, "batches": []})
            passes.append({"file": filename, "sha256": digest, "repetition": rep, "warmup": False, "forced": False, "requested": 2, "makespan_ns": 1000})
        write(directory/"summary.json", {"algorithm": name, "kind": "pareto", "dataset_sha256": self.dh, "queries_sha256": self.wh,
                                         "provenance": {"synthetic_fixture_only": True, "runtime_matches_build": True, "source_binding": "embedded_build_source",
                                                        "routing_source_sha256": "0"*64, "executable_sha256": "1"*64,
                                                        "build_source_sha256": "2"*64, "runtime_tree_sha256": "2"*64}, "passes": passes})
        return directory

    def evaluate(self, *runs, **kw):
        return e.evaluate(self.ds, self.qp, runs, self.cfg, **kw)

    def test_failures_in_denominator_and_null_regret(self):
        a, b = self.run_dir("good"), self.run_dir("timeout", fail=True)
        report, rows, pool = self.evaluate(a, b)
        failed = report["algorithms"][1]
        self.assertEqual(failed["requested"], 4)
        self.assertEqual(failed["completion_rate"], .5)
        self.assertEqual(failed["stages"]["displayed"]["pool_profile_coverage_including_failures"], 0)
        failed_row = next(r for r in rows if r["algorithm"] == "timeout" and r["query_id"] == "q1")
        self.assertIsNone(failed_row["quality"]["displayed"]["profiles"][0]["pool_relative_regret_seconds"])
        self.assertEqual(failed_row["outcome_cohort"], "incomplete_with_feasible_output")
        self.assertFalse(report["complete_reference"])
        self.assertFalse(pool["complete_reference"])
        self.assertEqual(report["paired_comparisons"][0]["baseline_only_success"], 2)

    def test_empty_pool_is_unknown_not_recall_one(self):
        report, rows, _ = self.evaluate(self.run_dir("good"))
        empty = next(r for r in rows if r["query_id"] == "q2")
        self.assertEqual(empty["outcome_cohort"], "completed_valid_empty")
        self.assertIsNone(empty["quality"]["displayed"]["profile_coverage"])
        self.assertIn("true no-path", " ".join(report["unsupported_metrics"]))
        self.assertIsNone(empty["core_ns"])

    def test_invalid_witness_quarantined(self):
        report, rows, pool = self.evaluate(self.run_dir("bad", corrupt=True))
        bad = next(r for r in rows if r["query_id"] == "q1")
        self.assertEqual(bad["status"], "invalid_output")
        self.assertFalse(bad["success"])
        self.assertEqual(next(q for q in pool["queries"] if q["query_id"] == "q1")["witnesses"], [])
        self.assertEqual(report["algorithms"][0]["failed_or_not_run"], 2)

    def test_source_hash_mismatch_fails_closed(self):
        run = self.run_dir("good")
        with (run/"pass-00.json").open("a") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(e.ValidationError, "SHA256"):
            self.evaluate(run)

    def test_missing_query_cannot_shrink_denominator(self):
        run = self.run_dir("good")
        summary, _ = e.read_json(run/"summary.json")
        raw, _ = e.read_json(run/"pass-00.json")
        raw["records"].pop()
        summary["passes"][0]["sha256"] = write(run/"pass-00.json", raw)
        write(run/"summary.json", summary)
        with self.assertRaisesRegex(e.ValidationError, "missing frozen query"):
            self.evaluate(run)

    def test_frozen_pool_revalidation_and_signed_deficiency(self):
        run = self.run_dir("good")
        _, _, pool = self.evaluate(run)
        frozen = self.root/"pool.json"
        write(frozen, pool)
        report, rows, rerun = self.evaluate(run, reference_pool_path=frozen)
        self.assertEqual(pool["pool_sha256"], rerun["pool_sha256"])
        self.assertIsNotNone(report["binding"]["frozen_reference_pool_file_sha256"])
        self.assertEqual(next(r for r in rows if r["query_id"] == "q1")["frozen_reference_pool_diagnostics"]["displayed"][0]["signed_observed_minus_frozen_pool_seconds"], 0)
        # Frozen all-walk reference is feasible but beaten by the candidate: signed negative is reference deficiency.
        checked_walk = self.c.check(self.qs[0], journey("od"))
        for entry in pool["queries"]:
            if entry["query_id"] == "q1":
                entry["witnesses"] = [checked_walk]
        payload = {entry["query_id"]: sorted(entry["witnesses"], key=lambda j: j["identity"]) for entry in pool["queries"]}
        pool["pool_sha256"] = e.sha(payload)
        write(frozen, pool)
        _, rows, _ = self.evaluate(run, reference_pool_path=frozen)
        diff = next(r for r in rows if r["query_id"] == "q1")["frozen_reference_pool_diagnostics"]["displayed"][0]["signed_observed_minus_frozen_pool_seconds"]
        self.assertEqual(diff, -10)

    def test_metadata_split_leakage_rejected(self):
        path = self.root/"meta.json"
        metadata = {"schema_version": e.VERSION, "dataset_sha256": self.dh, "queries_sha256": self.wh,
                    "items": [{"query_id": q["id"], "od_cluster": "same", "split": split, "workload_cohort": "model_coverage"} for q, split in zip(self.qs, ("tune", "test"))]}
        write(path, metadata)
        with self.assertRaisesRegex(e.ValidationError, "crosses splits"):
            self.evaluate(self.run_dir("good"), metadata_path=path)

    def test_primary_and_secondary_and_decomposition(self):
        report, rows, _ = self.evaluate(self.run_dir("good"))
        self.assertEqual(report["display_stage_labels"]["displayed"]["k"], 3)
        self.assertEqual(report["display_stage_labels"]["displayed_secondary"]["k"], 5)
        self.assertEqual(len(report["config"]["profiles"]), 20)
        q = next(r for r in rows if r["query_id"] == "q1")
        self.assertEqual(q["candidate_ranking_decomposition"][0]["displayed_selection_loss_seconds"], 0)

    def test_certificate_counterexample_updates_throughput(self):
        run = self.run_dir("claimed")
        better = self.run_dir("better")
        for directory, modify in ((run, "claim"), (better, "better")):
            summary, _ = e.read_json(directory/"summary.json")
            for entry in summary["passes"]:
                path = directory/entry["file"]
                raw, _ = e.read_json(path)
                if modify == "claim":
                    raw["records"][0]["certificates"] = {"earliest_arrival": True, "arrival_boardings": True}
                else:
                    raw["records"][0] = row(self.c, self.qs[0], [journey("ax", "bd")])
                entry["sha256"] = write(path, raw)
            write(directory/"summary.json", summary)
        report, rows, _ = self.evaluate(run, better)
        bad = next(r for r in rows if r["algorithm"] == "claimed" and r["query_id"] == "q1")
        self.assertEqual(bad["status"], "certificate_counterexample")
        summary = report["algorithms"][0]
        self.assertEqual(summary["completed_valid"], 2)  # only the q2 empty rows survive
        self.assertTrue(all(p["successes"] == 1 and p["completed_qps"] == 1e6 for p in summary["measured_passes"]))
        self.assertEqual(summary["throughput"]["point_estimate"], 1e6)

    def test_duplicate_display_slots_invalid_even_after_dedup(self):
        q = self.qs[0]
        source = row(self.c, q, [journey("slow")])
        source["display_options"]["3"]["options"] *= 4
        checked = e.reconstruct_record(source, self.c, {q["id"]: {"query": q, "stratum": "original_synthetic"}}, self.cfg)
        self.assertFalse(checked["success"])
        self.assertEqual(checked["source_slot_counts"]["displayed"], 4)
        self.assertTrue(any("exceeds requested k" in x["error"] for x in checked["errors"]))

    def test_display_score_and_common_policy_tampering_rejected(self):
        q = self.qs[0]
        source = row(self.c, q, [journey("slow")])
        source["display_options"]["3"]["options"][0]["generalized_score_seconds"] = 0
        expected = {q["id"]: {"query": q, "stratum": "original_synthetic"}}
        checked = e.reconstruct_record(source, self.c, expected, self.cfg)
        self.assertFalse(checked["success"])
        self.assertTrue(any("score metadata mismatch" in x["error"] for x in checked["errors"]))
        source = row(self.c, q, [journey("slow")])
        source["display_options"]["3"]["ranking_transfer_penalty_seconds"] = 0
        checked = e.reconstruct_record(source, self.c, expected, self.cfg)
        self.assertTrue(any("frozen common policy" in x["error"] for x in checked["errors"]))

    def test_shared_pool_cohorts_and_transit_counts(self):
        report, rows, _ = self.evaluate(self.run_dir("good"), self.run_dir("failed", fail=True))
        good = report["algorithms"][0]
        self.assertEqual(set(good["reference_pool_cohorts"]), {"pool_has_transit", "pool_empty_unknown"})
        self.assertEqual(good["reference_pool_cohorts"]["pool_has_transit"]["requested"], 2)
        self.assertEqual(good["reference_pool_cohorts"]["pool_empty_unknown"]["requested"], 2)
        self.assertEqual(good["stages"]["candidates"]["offered_request_output_types"]["completed_with_transit"], 2)
        for qid in ("q1", "q2"):
            self.assertEqual(len({r["reference_pool_cohort"] for r in rows if r["query_id"] == qid}), 1)

    def test_impossible_timings_do_not_become_fast_successes(self):
        q = self.qs[0]
        expected = {q["id"]: {"query": q, "stratum": "original_synthetic"}}
        source = row(self.c, q, [journey("slow")])
        source.update(response_ns=1, core_ns=200, quality_ns=300, validation_rank_ns=400)
        checked = e.reconstruct_record(source, self.c, expected, self.cfg)
        self.assertFalse(checked["success"])
        self.assertTrue(any(x["stage"] == "timing" for x in checked["errors"]))
        source = row(self.c, q, [journey("slow")])
        source.update(service_start_offset_ns=0, search_done_offset_ns=90, validation_start_offset_ns=80)
        checked = e.reconstruct_record(source, self.c, expected, self.cfg)
        self.assertFalse(checked["success"])
        self.assertTrue(any("offsets not monotone" in x["error"] for x in checked["errors"]))

    def test_pool_retains_source_run_ledger(self):
        _, _, pool = self.evaluate(self.run_dir("good"))
        self.assertEqual(pool["source_runs"][0]["algorithm"], "good")
        source = next(q for q in pool["queries"] if q["query_id"] == "q1")["sources"][0]
        self.assertEqual(source["summary_sha256"], pool["source_runs"][0]["summary_sha256"])
        self.assertEqual(source["source_reported_status"], "complete")

    def test_2d_cap_projection_includes_zero_and_does_not_certify(self):
        q = self.qs[0]
        source = row(self.c, q, [journey("ax", "bd"), journey("slow"), journey("od")])
        source["certificates"] = {"arrival_boardings": True, "earliest_arrival": True, "best_score": True}
        checked = e.reconstruct_record(source, self.c, {q["id"]: {"query": q, "stratum": "original_synthetic"}}, self.cfg)
        projected = e.declared_2d_cap_projection(checked, "pareto")
        self.assertTrue(projected["eligible_declared_contract"])
        self.assertEqual([x["earliest_arrival"] for x in projected["caps"]], [80, 70, 40, 40, 40])
        self.assertFalse(projected["reference_complete_certified_by_evalkit"])
        self.assertFalse(e.declared_2d_cap_projection(checked, "arrival_top_k")["eligible_declared_contract"])
        checked["completed"] = False
        self.assertEqual(e.declared_2d_cap_projection(checked, "pareto")["caps"], [])

    def test_2d_crosscheck_mismatch_and_failure_ineligibility(self):
        a, b = self.run_dir("a"), self.run_dir("b")
        for directory, js in ((a, [journey("slow")]), (b, [journey("ax", "bd"), journey("slow")])):
            summary, _ = e.read_json(directory/"summary.json")
            for entry in summary["passes"]:
                path = directory/entry["file"]
                raw, _ = e.read_json(path)
                raw["records"][0] = row(self.c, self.qs[0], js)
                raw["records"][0]["certificates"] = {"arrival_boardings": True, "earliest_arrival": True, "best_score": True}
                entry["sha256"] = write(path, raw)
            write(directory/"summary.json", summary)
        report, rows, _ = self.evaluate(a, b)
        comparison = report["declared_2d_cap_crosschecks"]["comparisons"][0]
        self.assertEqual(comparison["status"], "failed_certificate_counterexample")
        self.assertEqual(comparison["certificate_rejected_pairs"], 2)
        self.assertEqual(comparison["mismatch_pairs"], 0)
        self.assertEqual(comparison["offered_query_cap_pairs"], 20)
        self.assertEqual(comparison["comparable_query_cap_pairs"], 0)
        rejected = next(r for r in rows if r["algorithm"] == "a" and r["query_id"] == "q1")
        self.assertFalse(rejected["declared_2d_cap_projection"]["eligible_declared_contract"])
        self.assertEqual(rejected["declared_2d_cap_projection"]["caps"], [])
        self.assertTrue(comparison["certificate_counterexamples"][0]["baseline_counterexamples"])
        self.assertFalse(comparison["truth_reference_selected"])
        failed_report, _, _ = self.evaluate(a, self.run_dir("failed", fail=True))
        self.assertEqual(failed_report["declared_2d_cap_crosschecks"]["comparisons"][0]["comparable_declared_complete_pairs"], 0)

    def test_3d_projection_and_nullable_cap_absence(self):
        q = self.qs[0]
        source = row(self.c, q, [journey("slow")])
        source["certificates"] = {"arrival_boardings": True, "arrival_boardings_walking": True, "earliest_arrival": True, "best_score": True}
        checked = e.reconstruct_record(source, self.c, {q["id"]: {"query": q, "stratum": "original_synthetic"}}, self.cfg)
        projection = e.declared_2d_cap_projection(checked, "pareto_walking")
        self.assertEqual(projection["projection"], "explicit_3D_to_2D_min_arrival_projection")
        self.assertIsNone(projection["caps"][0]["earliest_arrival"])
        self.assertIn("NOT independently certified", projection["caps"][0]["null_meaning"])
        checked["success"] = False
        self.assertFalse(e.declared_2d_cap_projection(checked, "pareto_walking")["eligible_declared_contract"])

    def test_json_duplicate_keys_rejected(self):
        path = self.root/"dup.json"
        path.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(e.ValidationError, "duplicate JSON"):
            e.read_json(path)

    def test_true_passenger_semantics_not_silently_accepted(self):
        workload, _ = e.read_json(self.qp)
        workload["request_semantics"] = "multi_origin_passenger"
        write(self.qp, workload)
        with self.assertRaisesRegex(e.ValidationError, "passenger workload unsupported"):
            self.evaluate(self.run_dir("good"))

    def test_cluster_bootstrap_reproducible(self):
        values = {"od1": [1, 3], "od2": [10], "od3": [-2, 2]}
        a = e.cluster_interval(values, self.cfg["bootstrap"])
        b = e.cluster_interval(values, self.cfg["bootstrap"])
        self.assertEqual(a, b)
        self.assertEqual(a["od_clusters"], 3)
        self.assertIsNotNone(a["interval"])
        self.assertIsNone(e.cluster_interval({"only": [1, 2]}, self.cfg["bootstrap"])["interval"])

    def test_unequal_repetitions_paired_comparison_unavailable(self):
        report, _, _ = self.evaluate(self.run_dir("a", reps=1), self.run_dir("b", reps=2))
        self.assertEqual(report["paired_comparisons"], [])
        self.assertIn("identical", report["unavailable_paired_comparisons"][0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
