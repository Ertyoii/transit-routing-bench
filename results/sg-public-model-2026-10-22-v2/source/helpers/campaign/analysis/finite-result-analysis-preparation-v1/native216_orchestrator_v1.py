"""SOURCE-ONLY candidate for a separately accepted, bounded native216 reader.

No CLI, lock, helper imports, source discovery, process launch, router, evaluator
implementation, or implicit acceptance lives here. Do not import/execute during
measurement. The caller pins the unchanged helpers, accepts the input binding,
holds the one global lock, imposes limits, and creates an exclusive output dir.

run_native_window receives the accepted binding's ``native`` subsection:
  window: one exact WINDOWS value; mode: inventory | feasibility-window
  original_native_plans: [primary ref, domain ref] (executed, not renamed runs)
  original_scope_ledger: ref; original_alias_equality: ref
  operational_inputs: refs for every additive non-original command/spec input
  allowed_terminal_states: independently accepted, nonempty state vocabulary
  expected_command_environment: exact complete runner-recorded environment keys
      except GOGC/GOMEMLIMIT, which are checked against the exact new spec
  expected_cpu_affinity: exact runner-recorded affinity string
  native_sources: two entries, one per actual block, each containing
      campaign (absolute), plan ref, terminal_receipt ref, and terminal_rows.
      Every terminal_rows entry contains id, state, launched (bool), id_pointer,
      state_pointer, command ref|null, result ref|null. A pointer is an array of
      JSON object keys/array indexes into the actual receipt. These projections
      are accepted externally, not a claim that a receipt schema exists today.
  optional compare_original_scalar: false by default. If true, require
      original_scalar_inputs: exact refs for ALL files consumed by unchanged
      audit.load_scalar. This runs only in feasibility-window mode.

io.read_ref checks bytes/SHA; io.read_path checks an optional expected SHA and
bounded JSON size; io.file_ref checks generic file bytes without JSON decoding;
io.bindings is the caller's shared path->SHA map. References are lexical absolute
paths. Relative original freeze/coverage refs are anchored to their original
plan, never to a new campaign. New216 stays separate from original960/scalar432.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re


WINDOWS = tuple("weekday-" + name + "-20261020" for name in
                ("morning", "midday", "evening", "overnight"))
CELLS = tuple((str(gc), heap) for gc in (50, 100, 200)
              for heap in ("4GiB", "7GiB"))
STOP = 5_500_000_000
TP = "tp_source_domain_retained_fixed_caps_experimental_v1"
KINDS = {"range_raptor": "range_profile", "tad": "tad",
         "core_ch": "corech_graph", "trip_based": "bare_tb", TP: "scoped_tp"}
DRIVERS = {"range_profile": "profilebench", "tad": "tadbench",
           "corech_graph": "corechgraphbench", "bare_tb": "familybench",
           "scoped_tp": "familybench"}
ERRORS = (ValueError, KeyError, TypeError, OSError, StopIteration, IndexError)
OPERATIONAL_KEYS = frozenset({"id", "argv", "env", "rss_safety_stop_bytes",
    "inputs", "block", "position", "source_policy_binding",
    "native_contract_only", "original_native_contract_id"})
HEX = re.compile(r"[0-9a-f]{64}")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def absolute(path):
    need(isinstance(path, str) and Path(path).is_absolute()
         and ".." not in Path(path).parts, "lexical absolute path required")
    return Path(path)


def ref_at(ref, base=None):
    need(isinstance(ref, dict) and isinstance(ref.get("path"), str)
         and isinstance(ref.get("sha256"), str)
         and HEX.fullmatch(ref["sha256"]), "frozen path/SHA reference required")
    value = dict(ref)
    path = Path(value["path"])
    if not path.is_absolute():
        need(base is not None, "relative reference lacks original plan base")
        path = base / path
    value["path"] = str(absolute(str(path)))
    return value


def same_ref(actual, frozen):
    return (actual.get("path") == frozen["path"]
            and actual.get("sha256") == frozen["sha256"]
            and ("bytes" not in frozen or actual.get("bytes") == frozen["bytes"]))


def pointer(value, parts):
    need(isinstance(parts, list), "receipt pointer must be an explicit array")
    for part in parts:
        if isinstance(value, list):
            need(type(part) is int and 0 <= part < len(value), "invalid receipt array pointer")
        else:
            need(isinstance(value, dict) and isinstance(part, str) and part in value,
                 "invalid receipt object pointer")
        value = value[part]
    return value


def put(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


class Lines:
    def __init__(self, path):
        self.stream = Path(path).open("x", encoding="utf-8")
        self.count = 0

    def append(self, value):
        self.stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False) + "\n")
        self.count += 1

    def close(self):
        self.stream.close()


def originals(binding, io):
    refs = binding["original_native_plans"]
    need(isinstance(refs, list) and len(refs) == 2, "exact original primary/domain plans required")
    io.read_ref(ref_at(binding["original_scope_ledger"]))
    io.read_ref(ref_at(binding["original_alias_equality"]))
    all_rows, selected = {}, {}
    for index, raw_ref in enumerate(refs):
        ref = ref_at(raw_ref)
        plan = io.read_ref(ref)
        need(plan.get("evaluation_mode") == "diagnostic", "original plan is not diagnostic tune")
        freeze_ref = ref_at(plan["auxiliary_input_source_freeze"], Path(ref["path"]).parent)
        freeze = io.read_ref(freeze_ref)
        coverage_ref = ref_at(plan["actual_driver_coverage"], Path(ref["path"]).parent)
        io.read_ref(coverage_ref)
        need(freeze.get("all_csa_execution_excluded") is True
             and freeze.get("native_domain_split") == "tune_only", "original freeze scope changed")
        for spec in plan["runs"]:
            rid = spec["id"]
            need(rid not in all_rows, "ambiguous original contract ID")
            all_rows[rid] = spec
            family = spec["family"]
            chosen = ((index == 0 and (family in {"range_raptor", "tad", "core_ch"}
                       or (family == "trip_based" and spec["window"] == WINDOWS[3])))
                      or (index == 1 and family == TP and spec["window"] == WINDOWS[3]))
            if chosen:
                selected[rid] = {"spec": spec, "kind": KINDS[family], "freeze": freeze,
                    "freeze_ref": freeze_ref, "coverage_ref": coverage_ref, "original_plan": ref}
    need(len(all_rows) == 68 and len(selected) == 18, "original68/selected18 census differs")
    need(Counter(value["kind"] for value in selected.values()) == Counter(
        range_profile=8, tad=4, corech_graph=4, bare_tb=1, scoped_tp=1), "selected original kind census differs")
    need(Counter(value["spec"]["window"] for value in selected.values()) ==
         Counter(dict(zip(WINDOWS, (4, 4, 4, 6)))), "original window census differs")
    return all_rows, selected


def alias(spec, original, operational, inv):
    """Exact spec comparison, not a configurable logical-field ignore list."""
    old = original["spec"]
    need(set(spec) - set(old) <= OPERATIONAL_KEYS, "unaccepted additive spec metadata")
    need(set(old) <= set(spec), "original spec field removed")
    for key in set(old) - OPERATIONAL_KEYS:
        need(spec[key] == old[key], "original logical spec field changed: " + key)
    expected_argv = list(old["argv"])
    if "-rss-safety-stop" in expected_argv:
        need(expected_argv.count("-rss-safety-stop") == 1, "duplicate original RSS flag")
        pos = expected_argv.index("-rss-safety-stop")
        need(pos + 1 < len(expected_argv), "truncated original RSS flag")
        expected_argv[pos + 1] = str(STOP)
    # The generator retains literal {run_dir}/{campaign_dir} output templates.
    # Runtime expansion is checked unchanged by inv.validate_envelope.
    need(spec["argv"] == expected_argv, "native logical argv changed beyond exact RSS guard")
    env, old_env = spec["env"], old.get("env", {})
    need(isinstance(env, dict) and (env.get("GOGC"), env.get("GOMEMLIMIT")) in CELLS,
         "undeclared native runtime cell")
    need({k: v for k, v in env.items() if k not in {"GOGC", "GOMEMLIMIT"}} ==
         {k: v for k, v in old_env.items() if k not in {"GOGC", "GOMEMLIMIT"}},
         "non-runtime native environment changed")
    need(spec["rss_safety_stop_bytes"] == STOP and spec.get("native_contract_only") is True,
         "native operational guard/scope differs")
    need(len(spec["inputs"]) == len(set(spec["inputs"])), "duplicate declared input path")
    need(set(old.get("inputs", [])) <= set(spec["inputs"]), "original input ancestry lost")
    frozen_paths = {row["path"] for row in original["freeze"]["input_files"]}
    need(set(spec["inputs"]) <= frozen_paths | set(operational), "unaccepted additive native input")
    need(set(spec["inputs"]) - set(old.get("inputs", [])) <= set(operational),
         "additive input lacks independent operational pin")
    driver = inv.driver_for(spec["argv"])
    need(driver == DRIVERS[original["kind"]], "native typed driver changed")
    roles = [role for role in original["freeze"]["source_roles"].values()
             if role["source_root"] == old["cwd"]]
    need(len(roles) == 1, "original frozen source role missing/ambiguous")
    role = roles[0]
    policy = spec["source_policy_binding"]
    source, binary = policy["source"], role["binaries"][driver]
    need(source.get("path") == old["cwd"] and policy.get("native_origin") == old["cwd"]
         and source.get("go_source_hash_sha256") == role["go_source_hash_sha256"]
         and source.get("commit") == role["git_commit"] and not source.get("status_porcelain")
         and same_ref(policy["binary"], binary) and spec["argv"][0] == binary["path"],
         "new source_policy_binding differs from exact original freeze")
    qualification = ref_at(policy["qualification"])
    need(qualification["path"] in operational
         and same_ref(qualification, operational[qualification["path"]]),
         "source qualification lacks independently accepted operational pin")
    return driver


def census(binding, io, inv):
    all_original, selected = originals(binding, io)
    operational = {}
    for raw in binding["operational_inputs"]:
        ref = ref_at(raw)
        need(ref["path"] not in operational, "duplicate operational input pin")
        need(same_ref(io.file_ref(ref["path"]), ref), "current operational input differs from accepted pin")
        operational[ref["path"]] = ref
    allowed_states = binding["allowed_terminal_states"]
    need(isinstance(allowed_states, list) and allowed_states
         and all(isinstance(state, str) and state for state in allowed_states),
         "independently accepted terminal vocabulary missing")
    sources = binding["native_sources"]
    need(isinstance(sources, list) and len(sources) == 2, "both actual native campaign roots required")
    rows, blocks, campaigns, ids = [], {}, set(), set()
    for source in sources:
        campaign = absolute(source["campaign"])
        need(str(campaign) not in campaigns, "duplicate actual native campaign root")
        campaigns.add(str(campaign))
        plan_ref = ref_at(source["plan"])
        need(plan_ref["path"] == str(campaign / "plan.json"), "plan is not actual new campaign plan")
        plan = io.read_ref(plan_ref)
        need(plan.get("evaluation_mode") == "diagnostic", "new native plan is not diagnostic")
        lane = plan["finite_lane"]
        block = lane["block"]
        need(lane.get("stage") == "native" and type(block) is int and block in (0, 1)
             and block not in blocks, "missing/duplicate native block")
        terminal_ref = ref_at(source["terminal_receipt"])
        receipt = io.read_ref(terminal_ref)
        terminals = {}
        for terminal in source["terminal_rows"]:
            rid = terminal["id"]
            need(rid not in terminals and terminal["state"] in allowed_states
                 and type(terminal["launched"]) is bool, "ambiguous/nonterminal projected run")
            need(pointer(receipt, terminal["id_pointer"]) == rid
                 and pointer(receipt, terminal["state_pointer"]) == terminal["state"],
                 "accepted terminal projection differs from pinned actual receipt")
            terminals[rid] = terminal
        need(len(plan["runs"]) == 108 and set(terminals) == {row["id"] for row in plan["runs"]},
             "actual terminal receipt/plan108 census differs")
        order, cells = [], set()
        for position, spec in enumerate(plan["runs"]):
            rid, original_id = spec["id"], spec["original_native_contract_id"]
            need(original_id in selected and rid not in ids and rid not in all_original,
                 "extra/duplicate/forged original native ID")
            ids.add(rid)
            need(type(spec["position"]) is int and spec["position"] == position
                 and spec["block"] == block, "native fixed block/position differs")
            old = selected[original_id]
            driver = alias(spec, old, operational, inv)
            gc, heap = spec["env"]["GOGC"], spec["env"]["GOMEMLIMIT"]
            need(rid == f"b{block}-native-{original_id}-gc{gc}-{heap}", "new ID differs from frozen generator identity")
            cell = original_id, gc, heap
            need(cell not in cells, "duplicate native original/runtime tuple")
            cells.add(cell); order.append(cell)
            rows.append({"campaign": campaign, "spec": spec, "original": old,
                         "driver": driver, "terminal": terminals[rid], "terminal_receipt": terminal_ref,
                         "plan": plan_ref, "kind": old["kind"]})
        need(cells == {(rid, gc, heap) for rid in selected for gc, heap in CELLS},
             "native108 Cartesian process census differs")
        blocks[block] = order
    need(set(blocks) == {0, 1} and blocks[1] == list(reversed(blocks[0])), "block1 is not exact full block0 reverse")
    need(len(ids) == 216, "actual new216 process census differs")
    need(Counter(row["kind"] for row in rows) == Counter(
        range_profile=96, tad=48, corech_graph=48, bare_tb=12, scoped_tp=12), "native216 driver partition differs")
    need(Counter(row["spec"]["window"] for row in rows) ==
         Counter(dict(zip(WINDOWS, (48, 48, 48, 72)))), "native216 window process partition differs")
    return rows, {"original_contract_count": 68, "selected_original_contract_count": 18,
        "other_original_contract_count": 50, "other_original_new_offers": 0,
        "other_original_contract_ids": sorted(set(all_original) - set(selected)),
        "selected_original_contract_ids": sorted(selected), "new_process_count": 216,
        "processes_by_kind": dict(Counter(row["kind"] for row in rows)),
        "processes_by_window": dict(Counter(row["spec"]["window"] for row in rows)),
        "reverse_blocks_verified": True}, operational


def command_binding(row, binding, io, inv, operational):
    campaign, spec, terminal = row["campaign"], row["spec"], row["terminal"]
    run = campaign / spec["id"]
    if not terminal["launched"]:
        need(terminal.get("command") is None and terminal.get("result") is None
             and not (run / "command.json").exists() and not (run / "result.json").exists(),
             "unlaunched receipt conflicts with actual command/result")
        return None, None, None
    command_ref, result_ref = ref_at(terminal["command"]), ref_at(terminal["result"])
    need(command_ref["path"] == str(run / "command.json")
         and result_ref["path"] == str(run / "result.json"), "terminal command/result points outside actual run")
    command, result = io.read_ref(command_ref), io.read_ref(result_ref)
    argv, driver, role, inputs = inv.validate_envelope(
        spec, command, result, row["original"]["freeze"], run, campaign)
    expected_env = dict(binding["expected_command_environment"], GOGC=spec["env"]["GOGC"],
                        GOMEMLIMIT=spec["env"]["GOMEMLIMIT"])
    need(command.get("environment") == expected_env, "actual new command environment differs from accepted envelope")
    need(command.get("requested_cpu_affinity") == binding["expected_cpu_affinity"]
         and command.get("sampled_rss_safety_stop_bytes") == STOP
         and command.get("timeout_s") == spec["timeout_s"], "actual new command CPU/RSS/timeout differs")
    need(len(command.get("inputs", [])) == len(inputs), "duplicate actual command input path")
    original_pins = {entry["path"]: entry for entry in row["original"]["freeze"]["input_files"]}
    for path, recorded in inputs.items():
        pin = original_pins.get(path) or operational.get(path)
        need(pin is not None and same_ref(recorded, pin), "actual command input lacks exact original/operational pin: " + path)
    need(set(spec["inputs"]) <= set(inputs), "actual command omitted declared native input")
    return command, result, (argv, driver, role, inputs)


def observed_rows(summary, artifact, alg, driver, expected, argv, io, inv):
    """Retain all observations; validation remains the unchanged helper's job."""
    observed, chosen, diagnostics = [], [], []
    for desc in summary.get("passes", summary.get("summaries", [])):
        name = desc.get("file")
        need(isinstance(name, str) and Path(name).name == name and name not in (".", ".."), "unsafe native pass filename")
        need(isinstance(desc.get("sha256"), str) and HEX.fullmatch(desc["sha256"]), "pass lacks frozen SHA")
        payload = io.read_path(str(artifact / name), expected_sha=desc["sha256"])
        need(payload.get("repetition") == desc.get("repetition")
             and type(payload.get("warmup")) is bool and payload["warmup"] == desc.get("warmup")
             and payload.get("algorithm") == desc.get("algorithm", alg), "native pass envelope differs")
        pa = payload["algorithm"]
        need(isinstance(pa, str) and "csa" not in pa.lower()
             and pa in ({alg, "identity"} if driver == "corechgraphbench" else {alg}), "unrequested native pass algorithm")
        need(isinstance(payload.get("records"), list), "native records not an array")
        ref = {"path": str(artifact / name), "sha256": desc["sha256"]}
        diagnostic = payload["warmup"] or desc.get("forced")
        if diagnostic:
            diagnostics.append({"pass": ref, "reason": "forced_or_warmup_diagnostic_not_ordinary"})
        else:
            need(payload["repetition"] == 0, "unexpected ordinary repetition")
            if pa == alg:
                chosen.append((desc, payload, ref))
        for index, native in enumerate(payload["records"]):
            observed.append({"pass": ref, "record_index": index, "algorithm": pa,
                             "diagnostic": bool(diagnostic), "row": native})
    need(len(chosen) <= 1, "multiple selected ordinary passes")
    # This is the authoritative full-pass validator, including graph identity
    # controls and exact row sets. Its failure is retained, not converted to pass.
    whole_error = None
    try:
        inv.load_passes(summary, artifact, expected, driver, argv, alg, io.bindings)
    except ERRORS as exc:
        whole_error = type(exc).__name__ + ": " + str(exc)
    return chosen[0] if chosen else None, observed, diagnostics, whole_error


def offered_bindings(chosen, expected, driver, argv, inv):
    if chosen is None:
        return {}, {}, []
    payload = chosen[1]
    if driver == "corechgraphbench":
        # Validate graph source/target/control row shape once as a whole, never
        # by reducing its expected target set, and never quadratically per row.
        try:
            inv.validate_rows(payload, expected, driver, argv)
        except ERRORS as exc:
            return {}, {}, [{"record_index": None, "offered_locator": None,
                             "error": type(exc).__name__ + ": " + str(exc)}]
        return ({row["requested_source"]: row for row in payload["records"]},
                {row["requested_source"]: index for index, row in enumerate(payload["records"])}, [])
    good, indices, failures, seen = {}, {}, [], set()
    for index, row in enumerate(payload["records"]):
        key = None
        try:
            need(isinstance(row, dict), "native record is not an object")
            key = row.get("query", {}).get("base", row.get("query", {})).get("id")
            need(key in expected, "row does not identify an offered locator")
            if key in seen:
                good.pop(key, None); indices.pop(key, None)
                raise ValueError("duplicate native offered locator")
            seen.add(key)
            inv.validate_rows({"records": [row]}, {key: expected[key]}, driver, argv)
            good[key], indices[key] = row, index
        except ERRORS as exc:
            failures.append({"record_index": index, "offered_locator": key,
                             "error": type(exc).__name__ + ": " + str(exc)})
    return good, indices, failures


def native_complete(row, driver):
    return bool(row is not None and row.get("completed" if driver == "familybench" else "complete") is True
                and not row.get("error") and not row.get("unsupported"))


def run_native_window(binding, io, out, inv, audit=None):
    """Run only after external acceptance/release, never self-accept any input."""
    window, mode = binding["window"], binding.get("mode", "inventory")
    need(window in WINDOWS and mode in {"inventory", "feasibility-window"}, "unsupported native mode/window")
    need(mode == "inventory" or audit is not None, "feasibility requires pinned unchanged audit helper")
    need(not binding.get("export_witnesses", False), "new native witness export is not enabled by this candidate")
    out = absolute(str(out))
    need(out.is_dir(), "caller must supply fresh exclusive output directory")
    for existing in out.iterdir():
        need(existing.name == "RESOURCE_OBSERVATIONS.json" and existing.is_file()
             and not existing.is_symlink(), "unexpected preexisting analysis output")
    all_rows, process_census, operational = census(binding, io, inv)
    selected = [row for row in all_rows if row["spec"]["window"] == window]
    datasets = {inv.flag(row["spec"]["argv"], "-dataset") for row in selected}
    need(len(datasets) == 1, "exactly one dataset per native analysis window required")
    dataset_path = next(iter(datasets))
    dataset_pins = {entry["sha256"] for row in selected for entry in row["original"]["freeze"]["input_files"]
                    if entry["path"] == dataset_path}
    need(len(dataset_pins) == 1, "original dataset identity is missing/ambiguous")
    dataset_sha = next(iter(dataset_pins))
    checker, scalar_slots = None, {}
    sinks = {name: Lines(out / name) for name in ("RUN_INVENTORY.jsonl", "OFFERED_NATIVE_ROWS.jsonl",
             "OBSERVED_NATIVE_ROWS.jsonl", "SCALAR_COMPARISONS.jsonl", "VALIDATION_ERRORS.jsonl")}
    totals, by_kind = Counter(), defaultdict(Counter)
    try:
        if mode == "feasibility-window":
            dataset = io.read_path(dataset_path, expected_sha=dataset_sha)
            checker = audit.legacy.Checker(dataset)
        if binding.get("compare_original_scalar", False):
            need(checker is not None, "scalar comparison is unavailable in no-model inventory")
            pins = {ref_at(ref)["path"]: ref_at(ref) for ref in binding["original_scalar_inputs"]}
            for path, ref in pins.items():
                need(same_ref(io.file_ref(path), ref), "original scalar input changed")
            prior = dict(io.bindings)
            scalar_sink = Lines(out / "ORIGINAL_SCALAR_SLOTS.jsonl")
            try:
                scalar_slots = audit.load_scalar(window, checker, dataset_sha, io.bindings, scalar_sink)
            finally:
                scalar_sink.close()
            for path, sha in io.bindings.items():
                if path not in prior or prior[path] != sha:
                    need(path in pins and pins[path]["sha256"] == sha, "unchanged scalar helper consumed an unpinned input")
        scalar_by_query = defaultdict(list)
        for slot in scalar_slots.values():
            scalar_by_query[slot["query"]["id"]].append(slot)
        for item in selected:
            campaign, spec, original = item["campaign"], item["spec"], item["original"]
            driver, kind = item["driver"], item["kind"]
            context = {"campaign": str(campaign), "run_id": spec["id"],
                "original_native_contract_id": spec["original_native_contract_id"],
                "original_plan": original["original_plan"], "source_freeze": original["freeze_ref"],
                "coverage": original["coverage_ref"], "new_plan": item["plan"],
                "terminal_receipt": item["terminal_receipt"], "terminal_state": item["terminal"]["state"],
                "block": spec["block"], "position": spec["position"], "window": window,
                "kind": kind, "driver": driver, "GOGC": spec["env"]["GOGC"], "GOMEMLIMIT": spec["env"]["GOMEMLIMIT"],
                "dataset_sha256": dataset_sha}
            argv = spec["argv"]
            workload_path = inv.flag(argv, "-queries")
            workload_pins = [entry for entry in original["freeze"]["input_files"] if entry["path"] == workload_path]
            need(len(workload_pins) == 1, "original workload pin missing/ambiguous")
            workload = io.read_path(workload_path, expected_sha=workload_pins[0]["sha256"])
            need(workload.get("dataset_sha256") == dataset_sha, "workload dataset identity differs")
            expected = inv.expected_items(workload, driver, argv)
            context.update(workload_path=workload_path, workload_sha256=workload_pins[0]["sha256"])
            inventory, manifest, chosen, observed, bound_rows, indices = None, None, None, [], {}, {}
            preparation = None
            binding_error, whole_error, diagnostics, row_errors = None, None, [], []
            try:
                command, result, envelope = command_binding(item, binding, io, inv, operational)
                # Actual campaign + actual spec + original freeze, unchanged.
                try:
                    inventory, _ = inv.inspect_run(campaign, spec, original["freeze"], io.bindings)
                except ERRORS as exc:
                    inventory = {"binding_status": "unchanged_inventory_rejected", "error": type(exc).__name__ + ": " + str(exc)}
                if envelope is not None:
                    argv, driver, role, inputs = envelope
                    artifact = campaign / spec["id"] / "artifact"
                    manifest_path = artifact / ("manifest.json" if driver in {"profilebench", "tadbench"} else "summary.json")
                    if manifest_path.exists():
                        manifest = io.read_path(str(manifest_path))
                        alg = inv.algorithm(argv, driver)
                        inv.validate_manifest(manifest, command, role, driver, alg, dataset_sha, workload_pins[0]["sha256"])
                        preparation = inv.preparation_state(manifest, driver, alg)
                        chosen, observed, diagnostics, whole_error = observed_rows(
                            manifest, artifact, alg, driver, expected, argv, io, inv)
                        bound_rows, indices, row_errors = offered_bindings(chosen, expected, driver, argv, inv)
                        need(preparation == "complete" or not any(
                            driver != "familybench" or native.get("attempted") is True
                            for native in bound_rows.values()), "request timing exists after unavailable preparation")
                        if driver == "corechgraphbench" and whole_error:
                            bound_rows = {}  # missing/invalid identity control never qualifies a graph pass
            except ERRORS as exc:
                binding_error = type(exc).__name__ + ": " + str(exc)
                bound_rows = {}  # no accepted witnesses or clocks from a bad run binding
            rr = {**context, "offered": len(expected), "inventory": inventory,
                  "run_binding_error": binding_error, "whole_pass_validation_error": whole_error,
                  "row_binding_failures": row_errors, "excluded_diagnostic_passes": diagnostics}
            if binding_error:
                sinks["VALIDATION_ERRORS.jsonl"].append({**context, "scope": "run_binding", "error": binding_error})
            if whole_error:
                sinks["VALIDATION_ERRORS.jsonl"].append({**context, "scope": "whole_pass", "error": whole_error})
            for error in row_errors:
                sinks["VALIDATION_ERRORS.jsonl"].append({**context, "scope": "row_binding", **error})
            for observation in observed:
                row = observation["row"]
                brief = {key: row.get(key) for key in ("query", "stratum", "requested_source", "requested_targets",
                    "requested_maximum_duration", "complete", "completed", "attempted", "error", "status",
                    "unsupported", "timed_out", "response_ns", "core_ns")} if isinstance(row, dict) else {"invalid_row_type": type(row).__name__}
                sinks["OBSERVED_NATIVE_ROWS.jsonl"].append({**context, **{key: value for key, value in observation.items() if key != "row"}, **brief})
            for key in expected:
                row = bound_rows.get(key)
                offer = expected[key] if driver != "corechgraphbench" else None
                attempted = bool(row is not None and (driver != "familybench" or row.get("attempted") is True))
                complete = native_complete(row, driver)
                record = {**context, "offered_locator": key, "native_row_present_and_validated": row is not None,
                    "native_preparation_status": preparation,
                    "native_complete": complete, "native_status": inv.row_status(row, driver) if row is not None else None,
                    "native_error": row.get("error") if row is not None else None,
                    "native_record_index": indices.get(key), "native_pass": chosen[2] if chosen else None,
                    "native_response_ns": row.get("response_ns") if attempted else None,
                    "native_core_ns": row.get("core_ns") if attempted else None,
                    "accepted_response_ns": None, "parity_status": "not_performed",
                    "independent_witness_integrity": "not_performed", "independent_optimality": "not_claimed",
                    "status": "native_row_validated_inventory_only" if row is not None else "unavailable_missing_or_unbound_native_row"}
                if row is None and preparation not in (None, "complete"):
                    record["status"] = "not_run_preparation_unavailable_or_invalid"
                    record["native_preparation_diagnosis"] = (inventory or {}).get("preparation_diagnosis")
                if offer is not None:
                    record.update(offered_native_query=offer["query"], stratum=offer["stratum"])
                else:
                    record.update(requested_source=key,
                        requested_targets=row.get("requested_targets") if row is not None else None,
                        requested_target_set=list(expected),
                        requested_maximum_duration=int(inv.flag(argv, "-maximum-duration", "600")),
                        graph_cells=len(expected), graph_self_cells=1, graph_nonself_cells=len(expected)-1,
                        graph_proof_scope="existing native raw walking-anchor graph audit only; no transit feasibility",
                        native_graph_audit=(manifest or {}).get("independent_audit"),
                        native_graph_audit_passes=(manifest or {}).get("independent_audit_passes"))
                result_audit, donated = None, {"raw": [], "final": []}
                if checker is not None and row is not None and driver != "corechgraphbench":
                    try:
                        result_audit = (audit.audit_profile(checker, row) if driver == "profilebench"
                                        else audit.audit_point(checker, row, driver))
                        extensions = result_audit.get("physical_extension_counterexamples", [])
                        record.update(independent_witness_integrity="passed",
                            status="native_complete_saved_witness_integrity" if complete and not extensions
                                   else "saved_witness_integrity_native_incomplete_or_counterexample",
                            physical_extension_counterexamples=extensions,
                            independent_statistics={name: result_audit[name] for name in (
                                "grid_cells_checked_per_stage", "saved_witness_materializations_checked", "readiness_observations")})
                    except ERRORS as exc:
                        record.update(independent_witness_integrity="failed", status="independent_witness_integrity_failed",
                                      independent_error=type(exc).__name__ + ": " + str(exc))
                        sinks["VALIDATION_ERRORS.jsonl"].append({**context, "offered_locator": key,
                            "scope": "independent_witness_integrity", "error": record["independent_error"]})
                    # Per-witness donations are an independent feasibility gate,
                    # not permission to export/import new216 into original960.
                    try:
                        donated, failures = audit.base_donations(checker, row, driver)
                        record.update(feasible_saved_witness_counts={stage: len(donated[stage]) for stage in ("raw", "final")},
                                      donation_reconstruction_failures=failures)
                    except ERRORS as exc:
                        record["donation_error"] = type(exc).__name__ + ": " + str(exc)
                        sinks["VALIDATION_ERRORS.jsonl"].append({**context, "offered_locator": key,
                            "scope": "donation_reconstruction", "error": record["donation_error"]})
                if driver in {"tadbench", "profilebench"} and scalar_slots:
                    q = offer["query"].get("base", offer["query"])
                    for slot in scalar_by_query.get(key, []):
                        need(q == slot["query"], "new native/scalar full query differs")
                        supported = slot["weight"]["extra_walk_weight"] == 0 and (driver == "profilebench" or slot["weight"]["transfer_seconds"] == 0)
                        for stage in ("raw", "final"):
                            candidates = [entry[0] for entry in donated[stage]]
                            comparison = (audit.comparison(candidates, slot) if supported and (candidates or result_audit is not None)
                                else {"status": "unsupported_native_objective" if not supported else "native_witness_unavailable_or_invalid"})
                            sinks["SCALAR_COMPARISONS.jsonl"].append({**context, "query_id": key, "stage": stage,
                                "native_complete": complete, "weight_index": slot["weight_index"], "weight": slot["weight"],
                                "original_scalar_complete": slot["complete"], **comparison})
                totals["offered_rows"] += 1
                by_kind[kind]["offered_rows"] += 1
                by_kind[kind][record["status"]] += 1
                by_kind[kind]["native_complete_rows"] += complete
                sinks["OFFERED_NATIVE_ROWS.jsonl"].append(record)
            sinks["RUN_INVENTORY.jsonl"].append(rr)
    finally:
        for sink in sinks.values():
            sink.close()
    put(out / "PROCESS_CENSUS.json", process_census)
    report = {"schema": "sg-native216-window-orchestration-candidate-v1", "window": window, "mode": mode,
        "new_processes_in_window": len(selected), "model_count": int(checker is not None),
        "process_census": process_census, "typed_offer_counts": {key: dict(value) for key, value in by_kind.items()},
        "heterogeneous_offered_rows_inventory_only": totals["offered_rows"],
        "pooled_native_quality_denominator": None, "accepted_clocks": 0, "parity_status": "not_performed",
        "new_native_witness_exports": 0, "new216_imported_into_original960": False,
        "original_baselines_rewritten": False, "scalar_comparison_requested": bool(binding.get("compare_original_scalar", False)),
        "scalar_slots_in_this_window": len(scalar_slots),
        "original_baseline_expectations_not_recomputed": {"native_offered": 960, "native_source_complete": 780,
            "native_preparation_unavailable": 180, "scalar_offered": 432, "scalar_complete": 414, "scalar_unknown": 18},
        "validation_errors": sinks["VALIDATION_ERRORS.jsonl"].count, "inputs": dict(io.bindings),
        "scope": "Separate new216 native claims, typed observed clocks, and optional saved-witness feasibility; no optimality, universal empty proof, speedup, parity or delivery acceptance."}
    put(out / "REPORT.json", report)  # Last output: absent on interrupted/fatal validation.
    return report
