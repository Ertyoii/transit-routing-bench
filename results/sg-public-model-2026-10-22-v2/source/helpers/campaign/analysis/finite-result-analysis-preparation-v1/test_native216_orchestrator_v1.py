"""UNEXECUTED synthetic test source. Run only after an explicit quiet release.

All fixtures are temporary synthetic metadata. No campaign models, workloads,
passes, binaries, or original ledgers are read. Fakes are dependency injection,
not monkeypatches of pinned production helpers. These tests do not independently
qualify real helper compatibility or a future accepted receipt schema.
"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("native216_candidate", Path(__file__).with_name("native216_orchestrator_v1.py"))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
SHA = "a" * 64


class FakeIO:
    def __init__(self):
        self.values, self.refs, self.bindings, self.reads = {}, {}, {}, []

    def add(self, path, value, sha=SHA):
        ref = {"path": str(path), "sha256": sha, "bytes": 1}
        self.values[str(path)], self.refs[str(path)] = value, ref
        return dict(ref)

    def file_ref(self, path):
        ref = self.refs[str(path)]
        self.bindings[str(path)] = ref["sha256"]
        return dict(ref)

    def read_ref(self, ref):
        if not m.same_ref(self.file_ref(ref["path"]), ref):
            raise ValueError("fake pinned bytes differ")
        return self.read_path(ref["path"], ref["sha256"])

    def read_path(self, path, expected_sha=None, max_bytes=128 * 1024 * 1024):
        ref = self.file_ref(path)
        if expected_sha is not None and ref["sha256"] != expected_sha:
            raise ValueError("fake pinned bytes differ")
        self.reads.append(str(path))
        return copy.deepcopy(self.values[str(path)])


class FakeInventory:
    def __init__(self):
        self.inspections, self.envelopes, self.row_validations = [], [], []

    def flag(self, argv, key, default=None):
        if key not in argv:
            return default
        if argv.count(key) != 1:
            raise ValueError("duplicate flag")
        return argv[argv.index(key) + 1]

    def driver_for(self, argv):
        return Path(argv[0]).name.split("-")[0]

    def algorithm(self, argv, driver):
        return "core_ch" if driver == "corechgraphbench" else self.flag(argv, "-algorithm", "range_raptor")

    def expected_items(self, workload, driver, argv):
        if driver == "corechgraphbench":
            return ["a", "b"]
        return {row["query"].get("base", row["query"])["id"]: copy.deepcopy(row) for row in workload["items"]}

    def validate_envelope(self, spec, command, result, freeze, run, campaign):
        self.envelopes.append((str(campaign), spec["id"], freeze))
        if command["id"] != spec["id"] or result["id"] != spec["id"]:
            raise ValueError("fake command identity mismatch")
        argv = [value.replace("{run_dir}", str(run)) for value in spec["argv"]]
        role = next(iter(freeze["source_roles"].values()))
        return argv, self.driver_for(argv), role, {row["path"]: row for row in command["inputs"]}

    def inspect_run(self, campaign, spec, freeze, bindings):
        self.inspections.append((str(campaign), copy.deepcopy(spec), freeze))
        return {"id": spec["id"], "campaign": str(campaign), "binding_status": "fake_unchanged_inventory"}, None

    def validate_manifest(self, summary, command, role, driver, alg, dataset_sha, workload_sha):
        if summary.get("dataset_sha256") != dataset_sha or summary.get("workload_sha256") != workload_sha:
            raise ValueError("fake manifest identity mismatch")

    def preparation_state(self, summary, driver, alg):
        return summary.get("synthetic_preparation", "complete")

    def validate_rows(self, payload, expected, driver, argv):
        self.row_validations.append(driver)
        keys = []
        for row in payload["records"]:
            key = row.get("requested_source") if driver == "corechgraphbench" else row.get("query", {}).get("base", row.get("query", {})).get("id")
            if key not in expected or key in keys:
                raise ValueError("fake invalid offered locator")
            keys.append(key)
            if driver != "corechgraphbench" and row["query"] != expected[key]["query"]:
                raise ValueError("fake full query mismatch")
            if type(row.get("response_ns")) is not int or row["response_ns"] < 0:
                raise ValueError("fake invalid response clock")
        if set(keys) != set(expected):
            raise ValueError("fake missing offered records")
        return payload["records"]

    def load_passes(self, summary, artifact, expected, driver, argv, alg, bindings):
        # The fake pass validator is intentionally separate from fixture IO.
        if driver == "corechgraphbench" and sum(desc.get("algorithm") == "identity"
                and not desc.get("warmup") for desc in summary.get("passes", [])) != 1:
            raise ValueError("fake missing mandatory identity control")
        for desc in summary.get("passes", []):
            if desc.get("algorithm") == alg and not desc.get("warmup"):
                payload = self.payloads[str(artifact / desc["file"])]
                self.validate_rows(payload, expected, driver, argv)
        return [], [], []

    def row_status(self, row, driver):
        return "native_complete" if m.native_complete(row, driver) else "native_incomplete"


class FakeAudit:
    class Legacy:
        def __init__(self, owner):
            self.owner = owner

        def Checker(self, dataset):
            self.owner.model_loads += 1
            return object()

    def __init__(self):
        self.model_loads, self.profile_calls, self.point_calls, self.donation_calls = 0, 0, [], []
        self.legacy = self.Legacy(self)

    def result(self, row):
        if row.get("invalid_witness"):
            raise ValueError("synthetic invalid witness")
        return {"raw": [], "final": [], "grid_cells_checked_per_stage": 0,
                "saved_witness_materializations_checked": 0, "readiness_observations": 0}

    def audit_profile(self, checker, row):
        self.profile_calls += 1
        return self.result(row)

    def audit_point(self, checker, row, driver):
        self.point_calls.append(driver)
        return self.result(row)

    def base_donations(self, checker, row, driver):
        self.donation_calls.append(driver)
        return {"raw": [], "final": []}, []


class Fixture:
    def __init__(self, root):
        self.root, self.io, self.inv = Path(root), FakeIO(), FakeInventory()
        self.inv.payloads = self.io.values
        self.source = str(self.root / "synthetic-source")
        self.binaries = {driver: self.io.add(self.root / (driver + "-frozen"), {}) for driver in m.DRIVERS.values()}
        self.role = {"source_root": self.source, "go_source_hash_sha256": SHA,
                     "git_commit": "synthetic-commit", "binaries": self.binaries}
        self.qualification = self.io.add(self.root / "qualification.json", {"synthetic": True})
        self.freeze = {"all_csa_execution_excluded": True, "native_domain_split": "tune_only",
                       "source_roles": {"synthetic": self.role}, "input_files": []}
        self.old = []
        for index, window in enumerate(m.WINDOWS):
            for copy_index in range(2):
                self.old.append(self.original(f"range-{index}-{copy_index}", "range_raptor", window))
            self.old.append(self.original(f"tad-{index}", "tad", window))
            self.old.append(self.original(f"graph-{index}", "core_ch", window))
        self.old.append(self.original("tb-overnight", "trip_based", m.WINDOWS[3]))
        self.tp = self.original("tp-overnight", m.TP, m.WINDOWS[3])
        primary = self.old + [self.original(f"other-primary-{i}", "not_selected", m.WINDOWS[0]) for i in range(43)]
        domain = [self.tp] + [self.original(f"other-domain-{i}", "not_selected", m.WINDOWS[0]) for i in range(7)]
        freeze_ref = self.io.add(self.root / "freeze.json", self.freeze)
        coverage_ref = self.io.add(self.root / "coverage.json", {"synthetic": True})
        refs = []
        for name, runs in (("primary", primary), ("domain", domain)):
            refs.append(self.io.add(self.root / (name + "-original.json"), {
                "evaluation_mode": "diagnostic", "runs": runs,
                "auxiliary_input_source_freeze": freeze_ref, "actual_driver_coverage": coverage_ref}))
        self.binding = {"window": m.WINDOWS[0], "mode": "inventory", "original_native_plans": refs,
            "original_scope_ledger": self.io.add(self.root / "scope-ledger.json", {"synthetic": True}),
            "original_alias_equality": self.io.add(self.root / "aliases.json", {"synthetic": True}),
            "operational_inputs": [self.qualification], "allowed_terminal_states": ["synthetic_not_offered", "synthetic_finished"],
            "expected_command_environment": {"GOMAXPROCS": "4", "GOTOOLCHAIN": "local"},
            "expected_cpu_affinity": "0-3", "native_sources": []}
        cells = [(spec, gc, heap) for spec in self.old + [self.tp] for gc, heap in m.CELLS]
        self.rows = []
        for block in (0, 1):
            campaign = self.root / ("new-b" + str(block)); campaign.mkdir()
            specs, terminals, receipt_rows = [], [], []
            for position, (original, gc, heap) in enumerate(cells if block == 0 else reversed(cells)):
                row = copy.deepcopy(original)
                row.update(id=f"b{block}-native-{original['id']}-gc{gc}-{heap}", block=block, position=position,
                    env={"GOGC": gc, "GOMEMLIMIT": heap}, rss_safety_stop_bytes=m.STOP,
                    native_contract_only=True, original_native_contract_id=original["id"],
                    source_policy_binding={"source": {"path": self.source, "go_source_hash_sha256": SHA,
                        "commit": "synthetic-commit", "status_porcelain": ""},
                        "binary": self.binaries[Path(original["argv"][0]).name.split("-")[0]],
                        "qualification": self.qualification, "native_origin": self.source})
                row["inputs"].append(self.qualification["path"])
                specs.append(row)
                receipt_rows.append({"run": row["id"], "outcome": "synthetic_not_offered"})
                terminal = {"id": row["id"], "state": "synthetic_not_offered", "launched": False,
                    "id_pointer": ["positions", position, "run"], "state_pointer": ["positions", position, "outcome"],
                    "command": None, "result": None}
                terminals.append(terminal); self.rows.append((campaign, row, terminal, receipt_rows[-1]))
            plan_ref = self.io.add(campaign / "plan.json", {"evaluation_mode": "diagnostic",
                "finite_lane": {"stage": "native", "block": block}, "runs": specs})
            receipt_ref = self.io.add(campaign / "terminal.json", {"positions": receipt_rows})
            self.binding["native_sources"].append({"campaign": str(campaign), "plan": plan_ref,
                "terminal_receipt": receipt_ref, "terminal_rows": terminals})

    def original(self, rid, family, window):
        driver = m.DRIVERS[m.KINDS[family]] if family in m.KINDS else "familybench"
        dataset = self.root / (window + "-model.json")
        if str(dataset) not in self.io.refs:
            self.freeze["input_files"].append(self.io.add(dataset, {"synthetic_model": window}))
        query = {"id": "query-" + rid, "origin": "a", "destination": "b", "departure": 10,
                 "latest_arrival": 100, "max_boardings": 3}
        if driver == "profilebench":
            query = {"base": query, "ready_window_end_inclusive": 70}
        workload = self.root / (rid + "-workload.json")
        self.freeze["input_files"].append(self.io.add(workload, {"dataset_sha256": SHA,
            "items": [{"query": query, "stratum": "synthetic"}]}))
        argv = [self.binaries[driver]["path"], "-dataset", str(dataset), "-queries", str(workload),
                "-algorithm", family, "-out-dir", "{run_dir}/artifact"]
        return {"id": rid, "family": family, "window": window, "variant_id": rid,
            "cwd": self.source, "source_roots": [self.source], "argv": argv,
            "inputs": [str(dataset), str(workload)], "timeout_s": 10, "env": {}}

    def launch(self, kind="tad", complete=True, records=None):
        campaign, spec, terminal, receipt_row = next(row for row in self.rows
            if m.KINDS.get(row[1]["family"]) == kind and row[1]["window"] == self.binding["window"])
        run = campaign / spec["id"]; run.mkdir(); artifact = run / "artifact"; artifact.mkdir()
        for name in ("command.json", "result.json"):
            (run / name).write_text("{}", encoding="utf-8")
        terminal.update(launched=True, state="synthetic_finished")
        receipt_row["outcome"] = "synthetic_finished"
        command = {"id": spec["id"], "environment": dict(self.binding["expected_command_environment"], **spec["env"]),
            "requested_cpu_affinity": "0-3", "sampled_rss_safety_stop_bytes": m.STOP,
            "timeout_s": 10, "inputs": [self.io.refs[path] for path in spec["inputs"]]}
        terminal["command"] = self.io.add(run / "command.json", command)
        terminal["result"] = self.io.add(run / "result.json", {"id": spec["id"], "ok": True})
        driver = self.inv.driver_for(spec["argv"])
        alg = self.inv.algorithm(spec["argv"], driver)
        workload = self.io.values[self.inv.flag(spec["argv"], "-queries")]
        if records is None:
            if kind == "corech_graph":
                records = [{"requested_source": source, "requested_targets": ["b", "a"],
                    "requested_maximum_duration": 600, "complete": complete, "response_ns": 9, "core_ns": 4}
                    for source in ("a", "b")]
            else:
                records = [dict(copy.deepcopy(workload["items"][0]), raw=[], final=[],
                    complete=complete, completed=complete, attempted=True, response_ns=9, core_ns=4)]
        payload = {"algorithm": alg, "repetition": 0, "warmup": False, "records": records}
        pass_ref = self.io.add(artifact / "ordinary.json", payload)
        desc = dict(pass_ref, file="ordinary.json", algorithm=alg, repetition=0, warmup=False)
        manifest = {"dataset_sha256": SHA, "workload_sha256": SHA, "passes": [desc],
                    "independent_audit": {"scope": "synthetic_graph_only"}}
        if kind == "corech_graph":
            identity = dict(copy.deepcopy(payload), algorithm="identity")
            identity_ref = self.io.add(artifact / "identity.json", identity)
            manifest["passes"].append(dict(identity_ref, file="identity.json", algorithm="identity",
                                           repetition=0, warmup=False))
        manifest_path = artifact / ("manifest.json" if driver in {"profilebench", "tadbench"} else "summary.json")
        manifest_path.write_text("{}", encoding="utf-8")
        self.io.add(manifest_path, manifest)
        return campaign, spec, command, payload

    def run(self, audit=None):
        out = self.root / "output"; out.mkdir()
        return m.run_native_window(self.binding, self.io, out, self.inv, audit)

    def lines(self, name):
        return [json.loads(line) for line in (self.root / "output" / name).read_text().splitlines()]


class Native216SourceTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        return Fixture(temp.name)

    def test_exact216_census_and_inventory_load_no_models(self):
        f = self.fixture(); report = f.run()
        self.assertEqual(report["process_census"]["new_process_count"], 216)
        self.assertEqual(report["new_processes_in_window"], 48)
        self.assertEqual(report["model_count"], 0)
        self.assertFalse(any(path.endswith("-model.json") for path in f.io.reads))
        self.assertEqual(report["process_census"]["other_original_new_offers"], 0)
        self.assertEqual(len(f.inv.inspections), 48)
        self.assertTrue(all(row["native_response_ns"] is None for row in f.lines("OFFERED_NATIVE_ROWS.jsonl")))

    def test_overnight_has72_processes_and_separate_scoped_tp(self):
        f = self.fixture(); f.binding["window"] = m.WINDOWS[3]; report = f.run()
        self.assertEqual(report["new_processes_in_window"], 72)
        self.assertIn("scoped_tp", report["typed_offer_counts"])
        self.assertFalse(report["new216_imported_into_original960"])

    def test_wrong_reverse_block_is_rejected(self):
        f = self.fixture()
        plan = f.io.values[f.binding["native_sources"][1]["plan"]["path"]]
        plan["runs"][0], plan["runs"][1] = plan["runs"][1], plan["runs"][0]
        with self.assertRaises(ValueError): f.run()

    def test_original68_census_is_required(self):
        f = self.fixture(); plan = f.io.values[f.binding["original_native_plans"][0]["path"]]
        plan["runs"].pop()
        with self.assertRaisesRegex(ValueError, "original68"): f.run()

    def test_logical_cap_argv_cannot_be_ignored(self):
        f = self.fixture(); f.rows[0][1]["argv"].extend(["-max-labels", "999"])
        with self.assertRaisesRegex(ValueError, "argv"): f.run()

    def test_unrecognized_additive_spec_metadata_is_rejected(self):
        f = self.fixture(); f.rows[0][1]["logical_override"] = True
        with self.assertRaisesRegex(ValueError, "metadata"): f.run()

    def test_nonruntime_environment_mutation_is_rejected(self):
        f = self.fixture(); f.rows[0][1]["env"]["GODEBUG"] = "changed"
        with self.assertRaisesRegex(ValueError, "non-runtime"): f.run()

    def test_source_policy_substitution_is_rejected(self):
        f = self.fixture(); f.rows[0][1]["source_policy_binding"]["source"]["go_source_hash_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "source_policy_binding"): f.run()

    def test_terminal_receipt_projection_is_checked(self):
        f = self.fixture(); f.rows[0][2]["state_pointer"] = ["positions", 0, "run"]
        with self.assertRaisesRegex(ValueError, "projection"): f.run()

    def test_missing_terminal_position_prevents_final_report(self):
        f = self.fixture(); f.binding["native_sources"][0]["terminal_rows"].pop()
        with self.assertRaises(ValueError): f.run()
        self.assertFalse((f.root / "output" / "REPORT.json").exists())

    def test_actual_command_env_failure_keeps_every_offer_unknown(self):
        f = self.fixture(); _, spec, command, _ = f.launch()
        command["environment"]["GOGC"] = "999"
        report = f.run()
        offers = [row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"]]
        self.assertEqual(len(offers), 1)
        self.assertIsNone(offers[0]["native_response_ns"])
        self.assertFalse(offers[0]["native_complete"])
        self.assertGreater(report["validation_errors"], 0)

    def test_missing_row_keeps_denominator_and_missing_clock_null(self):
        f = self.fixture(); _, spec, _, payload = f.launch(); payload["records"] = []
        f.run()
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertFalse(offer["native_row_present_and_validated"])
        self.assertIsNone(offer["native_response_ns"])
        self.assertEqual(offer["parity_status"], "not_performed")

    def test_invalid_clock_is_not_accepted_or_replaced_by_zero(self):
        f = self.fixture(); _, spec, _, payload = f.launch(); payload["records"][0].pop("response_ns")
        f.run()
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertIsNone(offer["native_response_ns"])
        self.assertIsNone(offer["accepted_response_ns"])
        self.assertTrue(any(row.get("response_ns") is None for row in f.lines("OBSERVED_NATIVE_ROWS.jsonl")))

    def test_partial_saved_witness_integrity_is_not_native_completion(self):
        f = self.fixture(); _, spec, _, _ = f.launch(complete=False)
        f.binding["mode"] = "feasibility-window"; audit = FakeAudit(); report = f.run(audit)
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertFalse(offer["native_complete"])
        self.assertEqual(offer["independent_witness_integrity"], "passed")
        self.assertEqual(audit.model_loads, 1)
        self.assertEqual(report["accepted_clocks"], 0)
        self.assertIsNone(offer["accepted_response_ns"])

    def test_preparation_unavailable_never_accepts_query_timing(self):
        f = self.fixture(); campaign, spec, _, _ = f.launch()
        manifest = f.io.values[str(campaign / spec["id"] / "artifact" / "manifest.json")]
        manifest["synthetic_preparation"] = "incomplete"
        f.run()
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertEqual(offer["native_preparation_status"], "incomplete")
        self.assertIsNone(offer["native_response_ns"])
        self.assertFalse(offer["native_complete"])

    def test_not_attempted_placeholder_clock_is_unavailable_not_zero(self):
        f = self.fixture(); f.binding["window"] = m.WINDOWS[3]
        _, spec, _, payload = f.launch(kind="bare_tb", complete=False)
        payload["records"][0].update(attempted=False, response_ns=0, core_ns=None)
        f.run()
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertIsNone(offer["native_response_ns"])
        self.assertIsNone(offer["native_core_ns"])

    def test_invalid_witness_does_not_rewrite_native_claim(self):
        f = self.fixture(); _, spec, _, payload = f.launch(); payload["records"][0]["invalid_witness"] = True
        f.binding["mode"] = "feasibility-window"; f.run(FakeAudit())
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertTrue(offer["native_complete"])
        self.assertEqual(offer["independent_witness_integrity"], "failed")
        self.assertIsNone(offer["accepted_response_ns"])

    def test_graph_preserves_whole_anchor_rows_without_transit_audit(self):
        f = self.fixture(); _, spec, _, _ = f.launch(kind="corech_graph")
        f.binding["mode"] = "feasibility-window"; audit = FakeAudit(); f.run(audit)
        offers = [row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"]]
        self.assertEqual(len(offers), 2)
        self.assertTrue(all(row["graph_cells"] == 2 and row["graph_self_cells"] == 1 for row in offers))
        self.assertEqual(audit.point_calls, [])
        self.assertTrue(all(row["independent_witness_integrity"] == "not_performed" for row in offers))
        observed = [row for row in f.lines("OBSERVED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"]]
        self.assertEqual(observed[0]["requested_targets"], ["b", "a"])

    def test_duplicate_locator_never_produces_an_accepted_row(self):
        f = self.fixture(); _, spec, _, payload = f.launch()
        payload["records"].append(copy.deepcopy(payload["records"][0])); f.run()
        offer = next(row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"])
        self.assertFalse(offer["native_row_present_and_validated"])

    def test_missing_graph_identity_control_cannot_qualify_graph_rows(self):
        f = self.fixture(); campaign, spec, _, _ = f.launch(kind="corech_graph")
        manifest = f.io.values[str(campaign / spec["id"] / "artifact" / "summary.json")]
        manifest["passes"] = manifest["passes"][:1]
        f.run()
        offers = [row for row in f.lines("OFFERED_NATIVE_ROWS.jsonl") if row["run_id"] == spec["id"]]
        self.assertEqual(len(offers), 2)
        self.assertTrue(all(not row["native_complete"] and row["native_response_ns"] is None for row in offers))

    def test_original_and_new_identities_are_not_aliased_in_helper_call(self):
        f = self.fixture(); f.run()
        for campaign, spec, freeze in f.inv.inspections:
            self.assertTrue(spec["id"].startswith("b"))
            self.assertNotEqual(spec["id"], spec["original_native_contract_id"])
            self.assertIn("new-b", campaign)
            self.assertEqual(freeze, f.freeze)

    def test_resource_observation_is_the_only_allowed_caller_file(self):
        f = self.fixture(); out = f.root / "output"; out.mkdir()
        (out / "RESOURCE_OBSERVATIONS.json").write_text("{}", encoding="utf-8")
        m.run_native_window(f.binding, f.io, out, f.inv)

    def test_preexisting_other_file_is_rejected(self):
        f = self.fixture(); out = f.root / "output"; out.mkdir()
        (out / "other.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            m.run_native_window(f.binding, f.io, out, f.inv)

    def test_create_only_output_and_report_are_not_overwritten(self):
        f = self.fixture(); f.run()
        with self.assertRaises(ValueError):
            m.run_native_window(f.binding, f.io, f.root / "output", f.inv)


if __name__ == "__main__":
    unittest.main()
