#!/usr/bin/env python3
"""Create-only, offline native auxiliary evidence inventory, never a router.

This helper does not parse dataset models, build, execute benchmarks, generate
candidate pools, or infer feasibility/optimality from a process exit code. Input
and source identities are checked against the frozen plan and recorded supervisor
bindings. Only workload and output bytes are read and rehashed. Run it under the
campaign lock after headline work, because even offline analysis uses resources.
"""
import argparse
import collections
import copy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re

HEX = re.compile(r"[0-9a-f]{64}")
LOCK = "/workspace/shared/sg-coldstart/setup/campaign.lock"
CONTRACTS = {
    "familybench": "point native objective; emitted certificates only, independent feasibility/quality requires the separate accepted evaluator",
    "profilebench": "whole inclusive readiness profile with fixed latest arrival; response includes every integer-ready witness checking; never divided into point latency",
    "tadbench": "one earliest-arrival witness under the hard boarding cap; not a Pareto frontier or full-model independent optimality proof",
    "corechgraphbench": "directed raw walking-anchor graph one-source-many-target row, checked by native independent Bellman-Ford audit; not transit, ULTRA, or OTP",
    "ultrabench": "canonical ULTRA native contract with capability declines; response includes native full-itinerary checker; control is additional different work",
}
PARITY_FIELDS = ("query", "stratum", "raw", "final", "completed", "attempted",
                 "valid_empty", "transit", "status", "error", "certificates")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def read(path, bindings, max_bytes=128 * 1024 * 1024):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > max_bytes:
        raise ValueError("artifact exceeds bounded read size: " + str(path))
    data = path.read_bytes()
    bindings[str(path)] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def flag(argv, name, default=None):
    positions = [i for i, value in enumerate(argv) if value == name]
    require(len(positions) <= 1, "duplicate flag " + name)
    if not positions:
        return default
    require(positions[0] + 1 < len(argv), "missing flag value " + name)
    return argv[positions[0] + 1]


def algorithm(argv, driver):
    if driver == "corechgraphbench":
        # This driver deliberately executes both identity and core_ch controls.
        return "core_ch"
    if driver == "ultrabench":
        # Canonical driver always includes the unaccelerated RAPTOR control.
        return "ultra_raptor"
    value = flag(argv, "-algorithm") or flag(argv, "-algorithms")
    require(isinstance(value, str) and value and "," not in value and "csa" not in value.lower(),
            "must select exactly one non-CSA algorithm")
    return value


def driver_for(argv):
    matches = [key for key in CONTRACTS if Path(argv[0]).name.startswith(key)]
    require(len(matches) == 1, "unknown/ambiguous native driver")
    return matches[0]


def distribution(values):
    values = sorted(values)
    n = len(values)
    return {"count": n, "p50": values[math.ceil(.50*n)-1] if n else None,
            "p95": values[math.ceil(.95*n)-1] if n else None,
            "p99": values[math.ceil(.99*n)-1] if n else None,
            "max": values[-1] if n else None,
            "method": "empirical nearest rank; no point latency division or population tail claim"}


def validate_clock(row):
    for key in ("response_ns",):
        value = row.get(key)
        require(type(value) is int and value >= 0, "invalid " + key)
    if row.get("core_ns") is not None:
        require(type(row["core_ns"]) is int and 0 <= row["core_ns"] <= row["response_ns"], "invalid core timing")


def resolve_reference(reference, plan_dir, bindings):
    require(isinstance(reference, dict), "missing evidence reference")
    path = Path(reference["path"])
    if not path.is_absolute():
        path = plan_dir / path
    value = read(path, bindings)
    require(bindings[str(path.resolve())] == reference.get("sha256"),
            "frozen evidence digest differs: " + str(path))
    return value


def expected_items(workload, driver, argv):
    items = copy.deepcopy(workload["items"])
    if driver == "profilebench" and "-point-workload" in argv:
        span = int(flag(argv, "-ready-span-seconds", "60"))
        require(span >= 0, "negative readiness span")
        for item in items:
            q = item["query"]
            require(q["departure"] + span <= q["latest_arrival"], "span exceeds fixed horizon")
            item["query"] = {"base": q, "ready_window_end_inclusive": q["departure"] + span}
    if driver == "corechgraphbench":
        return sorted({q["query"][key] for q in items for key in ("origin", "destination")})
    by_id = {}
    for item in items:
        q = item["query"]
        qid = q["base"]["id"] if driver == "profilebench" else q["id"]
        require(qid and qid not in by_id, "empty/duplicate offered query ID")
        by_id[qid] = item
    require(by_id, "empty offered workload")
    return by_id


def validate_envelope(spec, command, result, freeze, run_dir, campaign_dir):
    argv = [str(x).replace("{run_dir}", str(run_dir)).replace("{campaign_dir}", str(campaign_dir))
            for x in spec["argv"]]
    actual = command["argv"]
    require(actual[:3] == ["/usr/bin/taskset", "-c", command["requested_cpu_affinity"]],
            "unexpected taskset envelope")
    require(actual[3:] == argv, "command argv differs from frozen plan")
    require(command.get("id") == spec["id"] and command.get("cwd") == spec["cwd"],
            "command run/cwd identity differs")
    if result is not None:
        require(result.get("id") == spec["id"], "supervisor run identity differs")
    roles = [role for role in freeze["source_roles"].values() if role["source_root"] == spec["cwd"]]
    require(len(roles) == 1, "missing/ambiguous frozen source role")
    role = roles[0]
    driver = driver_for(argv)
    binary = role["binaries"][driver]
    require(command.get("binary", {}).get("path") == binary["path"] and
            command["binary"].get("sha256") == binary["sha256"] and argv[0] == binary["path"],
            "supervisor binary differs from source freeze")
    before = command.get("sources_before", [])
    require(len(before) == 1 and before[0].get("path") == role["source_root"] and
            before[0].get("go_source_hash_sha256") == role["go_source_hash_sha256"] and
            before[0].get("commit") == role["git_commit"] and not before[0].get("status_porcelain"),
            "supervisor source differs from freeze or dirty source")
    if result is not None:
        after = result.get("sources_after", [])
        require(result.get("source_contents_unchanged") is True and len(after) == 1 and
                after[0].get("path") == role["source_root"] and
                after[0].get("go_source_hash_sha256") == role["go_source_hash_sha256"] and
                after[0].get("commit") == role["git_commit"] and not after[0].get("status_porcelain"),
                "source changed across process")
    frozen = {entry["path"]: entry for entry in freeze["input_files"]}
    recorded = {entry["path"]: entry for entry in command.get("inputs", [])}
    for name in ("-dataset", "-queries", "-scoped-config", "-preference-scenarios"):
        path = flag(argv, name)
        if path:
            require(path in recorded and path in frozen and
                    recorded[path]["sha256"] == frozen[path]["sha256"] and
                    recorded[path]["bytes"] == frozen[path]["bytes"],
                    "input binding differs from freeze: " + name)
    return argv, driver, role, recorded


def validate_manifest(summary, command, role, driver, alg, dataset_sha, workload_sha):
    require(summary.get("dataset_sha256") == dataset_sha and
            (summary.get("queries_sha256") or summary.get("workload_sha256")) == workload_sha,
            "manifest dataset/workload binding differs")
    if driver == "familybench":
        require(summary.get("algorithm") == alg, "summary algorithm differs")
    p = summary.get("provenance", {})
    for key in ("build_source_sha256", "runtime_tree_sha256", "routing_source_sha256", "executable_sha256"):
        require(isinstance(p.get(key), str) and HEX.fullmatch(p[key]), "invalid provenance " + key)
    require(p.get("source_binding") == "embedded_build_source" and p.get("runtime_matches_build") is True and
            p["build_source_sha256"] == p["runtime_tree_sha256"] == role["go_source_hash_sha256"] and
            p["executable_sha256"] == command["binary"]["sha256"] and
            p["routing_source_sha256"] == role["routing_file_list_sha256"], "manifest source/binary binding differs")


def preparation_state(summary, driver, alg):
    prep = summary.get("preparation", {})
    if summary.get("phase") == "independent_audit":
        return "independent_audit_failed"
    if driver == "familybench":
        return "complete" if prep.get("complete") is True else prep.get("status", "incomplete_or_unknown")
    target = {"ultrabench": "ultra", "corechgraphbench": "core_ch", "tadbench": "tad",
              "profilebench": "range_raptor"}[driver]
    node = prep.get(target)
    # Profile/TAD ordinary constructor wrappers have no complete flag. A finished
    # manifest plus an error-free measured constructor is their native certificate.
    if not isinstance(node, dict):
        return "incomplete_or_unknown"
    if "complete" in node:
        return "complete" if node["complete"] is True else "incomplete"
    return "complete" if node.get("error") == "" and type(node.get("elapsed_ns")) is int else "incomplete_or_unknown"


def row_status(row, driver):
    if driver == "familybench":
        return row.get("status", "missing_status")
    if row.get("unsupported") is True:
        return "unsupported"
    if row.get("timed_out") is True:
        return "deadline"
    if row.get("complete") is True and not row.get("error"):
        return "native_complete" if (row.get("final") or row.get("final_points") or row.get("final_direct")) else "native_complete_empty"
    return "incomplete_or_error"


def preparation_diagnosis(summary, driver, state):
    prep = summary.get("preparation", {})
    nodes = [prep] if driver == "familybench" else [value for value in prep.values() if isinstance(value, dict)]
    errors = [node["error"] for node in nodes if node.get("error") not in (None, "", "<nil>")]
    if summary.get("error"):
        errors.append(summary["error"])
    text = "\n".join(errors).lower()
    if state == "complete":
        label = None
    elif "capability:" in text:
        label = "explicit_semantic_capability_refusal"
    elif driver == "familybench":
        label = "native_explicit_" + str(prep.get("status", "unknown"))
    elif "deadline" in text or "context canceled" in text:
        label = "deadline_or_cancellation"
    elif "budget" in text and "invalid" not in text:
        label = "native_budget_exhaustion_reported"
    else:
        label = "unresolved_preparation_failure"
    return {"classification": label, "exact_native_error_texts": errors,
            "scope": "Native explicit status/error diagnosis, not proof of infeasibility or support outside this budget/contract."}


def validate_rows(payload, expected, driver, argv):
    records = payload["records"]
    seen = set()
    for row in records:
        if driver == "corechgraphbench":
            key = row.get("requested_source")
            targets = row.get("requested_targets", [])
            require(key in expected and key not in seen and len(targets) == len(expected) and
                    set(targets) == set(expected) and
                    row.get("requested_maximum_duration") == int(flag(argv, "-maximum-duration", "600")),
                    "graph requested source/targets/cap differ")
            if row.get("complete") is True:
                raw = row.get("raw", {})
                require(row.get("request_shape_valid") is True and not row.get("request_shape_error") and
                        raw.get("source") == key and raw.get("maximum_duration") == row["requested_maximum_duration"] and
                        [p.get("target") for p in raw.get("paths", [])] == targets and
                        [p.get("target") for p in row.get("final", [])] == targets,
                        "graph accepted row shape differs")
        else:
            q = row.get("query", {})
            key = q.get("base", {}).get("id") if driver == "profilebench" else q.get("id")
            require(key in expected and key not in seen and q == expected[key]["query"] and
                    row.get("stratum") == expected[key]["stratum"], "row differs from offered request")
            if driver == "profilebench" and row.get("complete") is True:
                ready = list(range(q["base"]["departure"], q["ready_window_end_inclusive"] + 1))
                require([g.get("ready") for g in row.get("every_integer_ready_time", [])] == ready,
                        "complete profile omitted/reordered readiness grid")
                require(all(len(g.get("arrival_under_boarding_caps", [])) == q["base"]["max_boardings"] + 1
                            for g in row["every_integer_ready_time"]), "profile objective grid shape differs")
            if driver == "tadbench" and row.get("complete") is True:
                require(len(row.get("raw", [])) <= 1 and len(row.get("final", [])) <= 1,
                        "TAD output exceeds one EA witness")
        seen.add(key)
        attempted = row.get("attempted") is True if driver == "familybench" else True
        if attempted:
            validate_clock(row)
        elif row.get("completed") is True or row.get("valid_empty") is True or row.get("raw") or row.get("final"):
            raise ValueError("not-run row contains accepted witnesses/completion")
    require(seen == set(expected), "missing offered records")
    return records


def load_passes(summary, artifact, expected, driver, argv, alg, bindings):
    selected, controls, discarded = [], [], []
    for desc in summary.get("passes", summary.get("summaries", [])):
        name = desc.get("file")
        require(isinstance(name, str) and Path(name).name == name and name not in (".", ".."), "unsafe pass filename")
        path = artifact / name
        payload = read(path, bindings)
        require(bindings[str(path.resolve())] == desc.get("sha256"), "pass digest differs")
        require(payload.get("repetition") == desc.get("repetition") and
                type(payload.get("warmup")) is bool and payload["warmup"] == desc.get("warmup"),
                "pass repetition/warmup differs")
        pa = payload.get("algorithm")
        require(pa == desc.get("algorithm", alg), "pass algorithm differs")
        require(isinstance(pa, str) and "csa" not in pa.lower(), "CSA artifact excluded")
        allowed = {alg}
        if driver == "ultrabench":
            allowed.add("unaccelerated_raptor")
        if driver == "corechgraphbench":
            allowed.add("identity")
        require(pa in allowed, "unrequested pass algorithm")
        require(isinstance(payload.get("records"), list), "pass records not an array")
        if payload.get("warmup") or desc.get("forced"):
            discarded.append({"file": name, "reason": "forced_or_warmup_diagnostic_not_ordinary"})
            continue
        require(payload.get("repetition") == 0, "unexpected ordinary repetition")
        rows = validate_rows(payload, expected, driver, argv)
        target = selected if pa == alg else controls
        target.append({"algorithm": pa, "descriptor": desc, "records": rows})
    require(len(selected) <= 1, "multiple ordinary selected passes for one-repeat native plan")
    if selected and driver in ("ultrabench", "corechgraphbench"):
        require(len(controls) == 1, "missing/duplicate mandatory native control pass")
    return selected, controls, discarded


def classify_failure(summary, result, prep_state, statuses):
    if not result:
        return "pending_or_no_supervisor_terminal_result"
    if result.get("termination"):
        return result["termination"]
    if summary is None:
        return "missing_native_manifest"
    if prep_state != "complete":
        return "native_preparation_" + prep_state
    if any(s not in ("complete", "native_complete", "native_complete_empty", "valid_empty") for s in statuses):
        return "query_partial_or_declined"
    if result.get("ok") is not True or summary.get("success") is not True:
        return "native_process_or_checks_failed"
    return "native_artifacts_complete_not_independent_optimality"


def inspect_run(campaign, spec, freeze, bindings):
    run_dir = campaign / spec["id"]
    base = {key: spec.get(key) for key in ("id", "variant_id", "family", "window", "walking_metric", "contrast", "equal_caps_control")}
    base.update(campaign=str(campaign), binding_status="unknown", timing_contract=None,
                independent_feasibility="not_performed_by_this_inventory", native_complete=0,
                measured_response_ns=distribution([]), measured_core_ns=distribution([]))
    command_path, result_path = run_dir / "command.json", run_dir / "result.json"
    if not command_path.exists():
        base.update(status="not_launched_or_no_command", **failure_context(campaign, spec, freeze, bindings))
        return base, None
    command = read(command_path, bindings)
    result = read(result_path, bindings) if result_path.exists() else None
    argv, driver, role, inputs = validate_envelope(spec, command, result, freeze, run_dir, campaign)
    workload_path = Path(flag(argv, "-queries"))
    workload = read(workload_path, bindings)
    require(bindings[str(workload_path.resolve())] == inputs[str(workload_path)]["sha256"], "current workload bytes differ")
    dataset_sha = inputs[flag(argv, "-dataset")]["sha256"]
    require(workload.get("dataset_sha256") == dataset_sha, "workload dataset binding differs")
    alg = algorithm(argv, driver)
    expected = expected_items(workload, driver, argv)
    base.update(driver=driver, algorithm=alg, offered=len(expected), original_point_queries=len(workload["items"]),
                timing_contract=CONTRACTS[driver], source_role=role.get("source_role"),
                dataset_sha256=dataset_sha, workload_sha256=bindings[str(workload_path.resolve())],
                domain_contract="tune-only fixed destination/source domain; not arbitrary OD" if "fixed-destination" in str(workload_path) else "primary tune offered demand, driver-native output contract",
                binding_status="command_matches_freeze")
    if driver == "corechgraphbench":
        base.update(requested_rows=len(expected), requested_cells=len(expected)**2,
                    requested_self_cells=len(expected), requested_nonself_cells=len(expected)*(len(expected)-1))
    if result:
        base["supervisor"] = {key: result.get(key) for key in ("ok", "returncode", "termination", "timed_out", "process_wall_s", "elapsed_wall_s", "sampled_peak_process_group_rss_bytes", "wait4_ru_maxrss_kib", "user_cpu_s", "system_cpu_s", "launch_to_first_available_answer_ns", "publication_receipt", "source_contents_unchanged")}
        base["publication_scope"] = "native emitted marker only; no independent first-answer acceptance claimed"
    artifact = run_dir / "artifact"
    summary_path = artifact / ("manifest.json" if driver in ("profilebench", "tadbench") else "summary.json")
    if not summary_path.exists():
        base["status"] = classify_failure(None, result, "unknown", {})
        base["unavailable"] = len(expected)
        return base, None
    summary = read(summary_path, bindings)
    validate_manifest(summary, command, role, driver, alg, dataset_sha, inputs[str(workload_path)]["sha256"])
    base.update(binding_status="native_manifest_command_freeze_bound", native_manifest_path=str(summary_path),
                native_success_flag=summary.get("success"), native_phase=summary.get("phase"),
                preparation=summary.get("preparation"), input_load_ns=summary.get("input_load_ns"),
                checker_preparation=summary.get("checker_preparation", summary.get("checker_preparation_ns")),
                quality_preparation=summary.get("quality_preparation"))
    prep_state = preparation_state(summary, driver, alg)
    base["preparation_status"] = prep_state
    base["preparation_diagnosis"] = preparation_diagnosis(summary, driver, prep_state)
    selected, controls, discarded = load_passes(summary, artifact, expected, driver, argv, alg, bindings)
    rows = selected[0]["records"] if selected else []
    # Preparation failure placeholders are retained but never timed as requests.
    failure_path = artifact / "preparation-failures.json"
    if failure_path.exists():
        failures = read(failure_path, bindings)
        require(not rows and isinstance(failures, list), "ambiguous ordinary and prep-failure records")
        require(len(failures) == len(expected), "preparation failure denominator differs")
        seen = set()
        for row in failures:
            qid = row.get("query", {}).get("id")
            require(qid in expected and qid not in seen and row.get("query") == expected[qid]["query"] and
                    row.get("stratum") == expected[qid]["stratum"] and not row.get("complete") and
                    not row.get("raw") and not row.get("final") and row.get("error"),
                    "invalid preparation-failure placeholder")
            seen.add(qid)
        base["preparation_failure_record_count"] = len(failures)
        base["preparation_failure_errors"] = dict(collections.Counter(x.get("error", "") for x in failures))
    statuses = collections.Counter(row_status(row, driver) for row in rows)
    attempted = [row for row in rows if driver != "familybench" or row.get("attempted") is True]
    complete_field = "completed" if driver == "familybench" else "complete"
    complete = [row for row in rows if row.get(complete_field) is True and not row.get("error") and not row.get("unsupported")]
    if driver == "familybench":
        # Successful native familybench rows omit error; some emit an empty string.
        complete = [row for row in rows if row.get("completed") is True and not row.get("error")]
    require(prep_state == "complete" or not attempted, "query timing exists after unavailable preparation")
    base.update(statuses=dict(statuses), native_complete=len(complete), attempted=len(attempted),
                unavailable=len(expected)-len(complete), not_run=len(expected)-len(attempted),
                measured_response_ns=distribution([row["response_ns"] for row in attempted]),
                measured_core_ns=distribution([row["core_ns"] for row in attempted if row.get("core_ns") is not None]),
                individual_core_unavailable_count=sum(row.get("core_ns") is None for row in attempted),
                complete_response_ns=distribution([row["response_ns"] for row in complete]),
                native_pass_descriptors=[x["descriptor"] for x in selected],
                additional_control_pass_descriptors=[x["descriptor"] for x in controls],
                excluded_diagnostic_passes=discarded,
                native_errors=dict(collections.Counter(row.get("error", "") for row in rows if row.get("error"))),
                emitted_certificate_combinations=dict(collections.Counter(json.dumps(row.get("certificates"), sort_keys=True) for row in rows)) if driver == "familybench" else None)
    if driver == "profilebench":
        base.update(ready_time_observations=sum(len(row.get("every_integer_ready_time", [])) for row in rows),
                    complete_profiles=len(complete), profile_contract=summary.get("contract"))
    if driver == "corechgraphbench":
        base.update(independent_graph_audit=summary.get("independent_audit"),
                    independent_graph_audit_passes=summary.get("independent_audit_passes"),
                    independent_graph_audit_ns=summary.get("independent_audit_ns"),
                    complete_cells=len(complete)*len(expected), complete_self_cells=len(complete),
                    complete_nonself_cells=len(complete)*(len(expected)-1))
    base["status"] = classify_failure(summary, result, prep_state, statuses)
    if not selected and prep_state == "complete":
        base["status"] = "missing_ordinary_selected_pass"
    # Keep compact field hashes, not all raw journey trees across every run.
    parity = {}
    if spec.get("family", "").startswith("trex"):
        for row in rows:
            parity[row["query"]["id"]] = {"completed": row.get("completed") is True,
                "fields": {key: hashlib.sha256(json.dumps(row.get(key), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
                           for key in PARITY_FIELDS}}
    return base, {"spec": spec, "argv": argv, "record_fields": parity, "complete": len(complete) == len(expected),
                  "preparation_complete": prep_state == "complete", "supervisor_ok": bool(result and result.get("ok")),
                  "manifest_success": summary.get("success") is True}


def comparable_argv(argv):
    result, i = [], 1  # binary is the only allowed source-only difference
    while i < len(argv):
        if argv[i] == "-out-dir":
            i += 2
        else:
            result.append(argv[i]); i += 1
    return result


def failure_context(campaign, spec, freeze, bindings):
    """Retain known offered denominator even when output validation fails."""
    context = {"offered": None, "attempted": None, "unavailable": None,
               "offered_denominator_source": "unresolved_frozen_workload"}
    try:
        argv = spec["argv"]
        path = Path(flag(argv, "-queries"))
        workload = read(path, bindings)
        pin = next(x for x in freeze["input_files"] if x["path"] == str(path))
        require(bindings[str(path.resolve())] == pin["sha256"], "workload changed")
        driver = driver_for(argv)
        offered = len(expected_items(workload, driver, argv))
        context.update(offered=offered, unavailable=offered,
                       original_point_queries=len(workload["items"]),
                       offered_denominator_source="hash-bound frozen plan workload; output qualification failed")
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        pass
    result_path = campaign / spec["id"] / "result.json"
    if result_path.exists():
        try:
            result = read(result_path, bindings)
            context["supervisor"] = {key: result.get(key) for key in ("ok", "returncode", "termination", "timed_out", "process_wall_s", "sampled_peak_process_group_rss_bytes", "source_contents_unchanged")}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            context["supervisor_evidence_error"] = str(exc)
    return context


def compare_trex(candidate, control):
    require(comparable_argv(candidate["argv"]) == comparable_argv(control["argv"]),
            "compact TREX contrast changed argv/config/caps/workload")
    differences, incomplete_differences = [], []
    left = control["record_fields"]
    right = candidate["record_fields"]
    for qid in sorted(set(left) | set(right)):
        a, b = left.get(qid), right.get(qid)
        fields = [key for key in PARITY_FIELDS if (a or {}).get("fields", {}).get(key) != (b or {}).get("fields", {}).get(key)]
        if a is None or b is None:
            fields.append("missing_record")
        if fields:
            target = differences if a and b and a.get("completed") is True and b.get("completed") is True else incomplete_differences
            target.append({"query_id": qid, "fields": fields})
    ready = all(x["complete"] and x["preparation_complete"] and x["supervisor_ok"] and x["manifest_success"] for x in (candidate, control))
    return {"status": "mismatch" if differences else "exact" if ready else "unknown",
            "differences": differences, "incomplete_outcome_differences": incomplete_differences,
            "reason": None if ready else "preparation/query/process not complete on both sides",
            "compared_fields": list(PARITY_FIELDS), "scope": "native output parity only, no independent correctness or speedup claim"}


def summarize(campaigns, out):
    bindings, rows, snapshots, plans, requested_contrasts = {}, [], {}, [], []
    for campaign in map(lambda x: Path(x).resolve(), campaigns):
        plan_path = campaign / "plan.json"
        plan = read(plan_path, bindings)
        require(plan.get("evaluation_mode") == "diagnostic", "native inventory only accepts diagnostic tune plans")
        freeze = resolve_reference(plan.get("auxiliary_input_source_freeze"), campaign, bindings)
        resolve_reference(plan.get("actual_driver_coverage"), campaign, bindings)
        require(freeze.get("all_csa_execution_excluded") is True and freeze.get("native_domain_split") == "tune_only", "freeze scope differs")
        plans.append({"campaign": str(campaign), "plan_sha256": bindings[str(plan_path)]})
        ids = [spec["id"] for spec in plan["runs"]]
        require(len(ids) == len(set(ids)), "duplicate run IDs")
        for spec in plan["runs"]:
            require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", spec["id"]), "unsafe run ID")
            if spec.get("contrast") == "compact_trex_equal_caps":
                requested_contrasts.append(((str(campaign), spec["id"]), spec))
            try:
                row, snapshot = inspect_run(campaign, spec, freeze, bindings)
                if snapshot:
                    snapshots[(str(campaign), spec["id"])] = snapshot
            except (ValueError, KeyError, TypeError, OSError) as exc:
                row = {"id": spec["id"], "family": spec.get("family"), "window": spec.get("window"),
                       "campaign": str(campaign), "binding_status": "invalid_or_unresolved",
                       "status": "evidence_validation_failed", "error": type(exc).__name__ + ": " + str(exc),
                       "native_complete": 0, "measured_response_ns": distribution([]),
                       "independent_feasibility": "not_performed_by_this_inventory"}
                row.update(failure_context(campaign, spec, freeze, bindings))
            rows.append(row)
    contrasts = []
    for key, spec in requested_contrasts:
        candidate = snapshots.get(key)
        if candidate is None:
            contrasts.append({"candidate": key[1], "campaign": key[0], "status": "unknown",
                              "reason": "candidate has no validated terminal native output"})
            continue
        wanted = spec["equal_caps_control"]
        controls = [(ckey, value) for ckey, value in snapshots.items() if ckey[0] == key[0] and
                    value["spec"].get("family") == wanted["family"] and
                    value["spec"].get("window") == wanted["window"] and
                    value["spec"].get("contrast") != "compact_trex_equal_caps" and
                    comparable_argv(value["argv"]) == comparable_argv(candidate["argv"])]
        entry = {"candidate": key[1], "campaign": key[0]}
        if len(controls) != 1:
            entry.update(status="unknown", reason="missing/ambiguous exact-argv control")
        else:
            ckey, control = controls[0]
            entry.update(control=ckey[1], **compare_trex(candidate, control))
        contrasts.append(entry)
    families = []
    for family in sorted({row.get("family") or "unknown" for row in rows}):
        members = [row for row in rows if (row.get("family") or "unknown") == family]
        families.append({"family": family, "runs": len(members),
                         "run_ids": [row["id"] for row in members],
                         "native_offered_units": sum(row.get("offered") or 0 for row in members),
                         "unresolved_offered_denominators": sum(row.get("offered") is None for row in members),
                         "native_completed_units": sum(row.get("native_complete") or 0 for row in members),
                         "statuses": dict(collections.Counter(row["status"] for row in members)),
                         "preparation_statuses": dict(collections.Counter(row.get("preparation_status", "unresolved") for row in members)),
                         "timing_note": "Per-run contract/resource clocks retained; no pooling across native units or resource/source tiers."})
    report = {"schema": "sg-v2-native-auxiliary-evidence-inventory-v1", "plans": plans,
              "analysis_source_sha256": digest(__file__), "inputs": bindings, "runs": rows,
              "compact_trex_contrasts": contrasts, "families": families,
              "run_status_counts": dict(collections.Counter(row["status"] for row in rows)),
              "limitations": ["No dataset model parsed and no router or independent feasibility evaluator executed by this helper.",
                  "Input/source/binary agreement is against frozen and recorded process hashes, not a signed attestation or fresh live source rehash.",
                  "No profile, TAD, CoreCH, native ULTRA, or unavailable point result enters an observed contributor candidate pool.",
                  "Native emitted completion/certificates are not global completeness or independent feasibility proof.",
                  "Independent accepted familybench point quality must be attached separately using the qualified bounded evaluator.",
                  "All offered native failures remain in denominators. Preparation placeholders and missing publications are never zero-latency successes.",
                  "Whole profile/graph-row response is never divided by readiness or target count; native controls have separate work/resource costs.",
                  "Process RSS includes sequential controls, diagnostics, validation and retained outputs; sampled peaks are not a hard cap."]}
    with Path(out).open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True); stream.write("\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--lock", default=LOCK)
    args = parser.parse_args()
    with Path(args.lock).open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = summarize(args.campaign, args.out)
    print(json.dumps({"runs": len(report["runs"]), "run_status_counts": report["run_status_counts"],
                      "compact_trex_contrasts": len(report["compact_trex_contrasts"])}))


if __name__ == "__main__":
    main()
