#!/usr/bin/env python3
"""Synthetic tests for exact single-k serving; no model/router execution.

This file is prepared during the timing barrier, not yet an executed test claim.
"""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load("accepted_bounded_delivery_tests", HERE / "evaluate_v2_bounded_memory.py")
n = load("certified_delivery_tests", HERE / "evaluate_v2_certified_delivery.py")


def bounded(k):
    return {"max_candidates": 1024, "max_subsets": 200000,
            "bounded": {"limits": [k], "objective": "normalized", "min_transfer_seconds": 0,
                        "max_transfer_seconds": 900, "min_extra_walk_weight": 0, "max_extra_walk_weight": 4,
                        "max_critical_points": 100000, "max_work": 50000000, "max_matrix_bytes": 67108864,
                        "distinct_patterns": False, "nested": False, "exact_subset_search": False}}


def finite(k):
    return {"max_candidates": 1024, "max_subsets": 200000, "lean_delivery": True,
            "delivery_policy": "finite_preferences_v2", "delivery_limits": [k],
            "groups": [{"name": "twenty", "description": "test", "preferences": [
                {"id": "p", "transfer_seconds": 0, "extra_walk_weight": 0}]}]}


def bounded_row(k, selected=None):
    return {"final": [], "recommendation_quality": {
        "continuous_choices": {"complete": True, "config": bounded(k)["bounded"], "selections": [
            {"limit": k, "complete": True, "selected": [] if selected is None else selected,
             "method": "empty_pool" if not selected else "greedy_best_swap_local"}]}, "selections": []}}


def finite_row(k):
    return {"final": [], "recommendation_quality": {"choices": {"complete": True, "groups": [
        {"group": finite(k)["groups"][0], "selections": [
            {"limit": k, "complete": True, "selected": [], "method": "preference_minimax"}]}]}, "selections": []}}


class CertifiedServingTests(unittest.TestCase):
    def test_accepted_sources_unchanged(self):
        self.assertEqual(n.sha(HERE / "evaluate_v2.py"), n.ACCEPTED_ORIGINAL_SHA256)
        self.assertEqual(n.sha(HERE / "evaluate_v2_bounded_memory.py"), n.ACCEPTED_BOUNDED_SHA256)

    def test_all_legacy_helpers_including_selected_ids_remain_ast_identical(self):
        def functions(path):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(path.read_text()).body
                    if isinstance(node, ast.FunctionDef)}
        before, after = functions(HERE / "evaluate_v2_bounded_memory.py"), functions(HERE / "evaluate_v2_certified_delivery.py")
        for name in before.keys() - {"evaluate"}:
            self.assertEqual(before[name], after[name], name)

    def test_explicit_k3_k5_and_per_run(self):
        for k in (3, 5):
            self.assertEqual(n.delivery_config(bounded(k), k), (k, "bounded"))
            self.assertEqual(n.delivery_config(bounded(k), "per-run"), (k, "bounded"))
            self.assertEqual(n.delivery_config(finite(k), k), (k, "finite"))
            with self.assertRaises(ValueError):
                n.delivery_config(bounded(k), 8-k)

    def test_absent_joint_mixed_wrong_or_boolean_limits_fail_closed(self):
        for limits in (None, [], [3, 5], [5, 3], [3, 3], [True], [3.0], [4]):
            cfg = bounded(3)
            if limits is None:
                cfg["bounded"].pop("limits")
            else:
                cfg["bounded"]["limits"] = limits
            with self.assertRaises(ValueError):
                n.delivery_config(cfg)

    def test_legacy_pattern_schema_is_not_certified_serving(self):
        with self.assertRaises(ValueError):
            n.delivery_config({"lean_delivery": True, "delivery_policy": "pattern_anchors_v1", "delivery_limits": [3]})

    def test_requested_certified_selection_empty_pool_and_nonempty(self):
        for k in (3, 5):
            self.assertEqual(n.selected_delivery_ids(bounded_row(k), bounded(k), k), [])
            row = bounded_row(k, ['[{"kind":"walk","ref":"f"}]'])
            row["final"] = [{"identity": "witness"}]
            self.assertEqual(len(n.selected_delivery_ids(row, bounded(k), k)), 1)
            self.assertEqual(n.selected_delivery_ids(finite_row(k), finite(k), k), [])

    def test_absent_incomplete_duplicate_wrong_and_mixed_output_limits(self):
        for k in (3, 5):
            good = bounded_row(k)
            cases = []
            a = copy.deepcopy(good); a.pop("recommendation_quality"); cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["complete"] = False; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["selections"][0]["complete"] = False; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["selections"] = []; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["selections"] *= 2; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["selections"][0]["limit"] = 8-k; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["selections"][0].pop("selected"); cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["selections"][0]["selected"] = ["x"]*(k+1); cases.append(a)
            a = copy.deepcopy(good); a["final"] = [{}]; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["selections"] = [{"limit": 3}]; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["choices"] = {}; cases.append(a)
            a = copy.deepcopy(good); a["recommendation_quality"]["continuous_choices"]["config"]["max_work"] += 1; cases.append(a)
            for row in cases:
                with self.subTest(k=k, row=row), self.assertRaises((ValueError, KeyError, TypeError)):
                    n.selected_delivery_ids(row, bounded(k), k)

    def test_finite_wrong_group_or_method_is_not_accepted(self):
        for mutation in ("group", "method", "complete", "controls"):
            row = finite_row(3)
            if mutation == "group": row["recommendation_quality"]["choices"]["groups"][0]["group"]["name"] = "other"
            if mutation == "method": row["recommendation_quality"]["choices"]["groups"][0]["selections"][0]["method"] = "score_dump"
            if mutation == "complete": row["recommendation_quality"]["choices"]["complete"] = False
            if mutation == "controls": row["recommendation_quality"]["continuous_choices"] = {}
            with self.assertRaises(ValueError): n.selected_delivery_ids(row, finite(3), 3)

    def test_full_config_equality_accepts_only_known_go_omitted_zero_defaults(self):
        cfg = bounded(5)
        summary_cfg = copy.deepcopy(cfg); summary_cfg["groups"] = None
        self.assertEqual(n.normalize_serving_config(cfg), n.normalize_serving_config(summary_cfg))
        summary_cfg["bounded"]["max_work"] += 1
        self.assertNotEqual(n.normalize_serving_config(cfg), n.normalize_serving_config(summary_cfg))
        cfg["unknown_new_policy"] = True
        with self.assertRaises(ValueError): n.normalize_serving_config(cfg)

    def test_consuming_argv_config_hash_summary_and_supervisor_bindings(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"; path.write_text(json.dumps(bounded(5)))
            argv = ["/binary", "-quality", "-display-k", "-1", "-preference-scenarios", str(path), "-out-dir", "{run_dir}/artifact"]
            actual = argv.copy(); actual[-1] = str(Path(temp) / "artifact")
            summary = {"quality_enabled": True, "preference_config_sha256": n.sha(path), "preference_config": bounded(5), "display_k": []}
            command = {"argv": ["/usr/bin/taskset", "-c", "0-3", *actual], "inputs": [
                {"path": str(path), "sha256": n.sha(path), "bytes": path.stat().st_size}]}
            self.assertEqual(n.validate_delivery_binding(summary, command, argv, "per-run", {}), (5, "bounded"))
            cases = []
            s = copy.deepcopy(summary); s["quality_enabled"] = False; cases.append((s, command, argv))
            s = copy.deepcopy(summary); s["preference_config_sha256"] = "0"*64; cases.append((s, command, argv))
            s = copy.deepcopy(summary); s["preference_config"]["bounded"]["max_work"] += 1; cases.append((s, command, argv))
            s = copy.deepcopy(summary); s["display_k"] = [3]; cases.append((s, command, argv))
            c = copy.deepcopy(command); c["inputs"][0]["sha256"] = "0"*64; cases.append((summary, c, argv))
            c = copy.deepcopy(command); c["argv"][4] = "-quality=false"; cases.append((summary, c, argv))
            a = argv + ["-quality"]; cases.append((summary, command, a))
            a = argv + ["-quality=false"]; cases.append((summary, command, a))
            for s, c, a in cases:
                with self.assertRaises(ValueError): n.validate_delivery_binding(s, c, a, "per-run", {})

    def test_per_k_buckets_never_merge_same_variant_offered_rows(self):
        buckets = {}
        for k in (3, 5):
            value = {"dataset_sha256": "model", "window": "morning", "variant_id": "same-name", "delivery_k": k,
                     "stage": "display", "stratum": "geographic", "complete": False,
                     "score": {"eligible": 393, "missing": True}, "leave_donor_family_out_signed": {"eligible": 393, "missing": True}}
            n.accumulate_delivery_quality_row(buckets, value)
        self.assertEqual(len(buckets), 4)
        self.assertTrue(all(b["rows"] == 1 and b["missing"] == 393 for b in buckets.values()))

    def test_quality_arithmetic_is_unmodified(self):
        c = [{"duration_seconds": 100, "metrics": {"transfers": 0, "walking_seconds": 0}}]
        r = [{"duration_seconds": 90, "metrics": {"transfers": 0, "walking_seconds": 0}}]
        weights = [{"transfer_seconds": 0.5, "extra_walk_weight": 0.25}]
        self.assertEqual(base.score_stage(c, r, weights, True), n.score_stage(c, r, weights, True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
