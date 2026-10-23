"""STATIC DRAFT: bounded typed native216 parity/clock projection, not scoring.

No CLI, auto-import of campaign helpers, restoration, archive, router, evaluator,
model read, source selection or implicit acceptance. A separately qualified
caller holds the owner-released lock and injects pinned unchanged modules:
  orches: native216_orchestrator_v1 (census and command_binding)
  inv: summarize_native_auxiliary_v1 (typed envelope/manifest/row validators)
  stats: project_runtime8_frontier_v2 (distribution and ratio)
  io: accepted bounded canonical-path reader, INCLUDING recoverably retired JSON.

io.read_path(logical_raw_path, expected_sha=None) must resolve only exact admitted
canonical bytes. It may not restore/create raw files, prefer a stale alias, or
equate a retired path to an unavailable native result. Pass payloads and all
profile/TAD outputs remain canonical. This module never calls inv.inspect_run or
inv.load_passes because those reopen retired raw summary paths internally.

The caller, not this draft, must accept exact storage/consumption closures and
helper/input source hashes. These are future API requirements, not receipts that
already exist. Full witness parity admits only native-contract clocks. Promotion
also requires independently accepted witness/quality evidence; absent means
pending, never equal quality, feasibility, global optimality or production speed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import statistics


CELLS = tuple((str(gc), heap) for gc in (50, 100, 200) for heap in ("4GiB", "7GiB"))
WINDOWS = tuple("weekday-" + x + "-20261020" for x in ("morning", "midday", "evening", "overnight"))
KINDS = {"range_profile", "tad", "corech_graph", "bare_tb", "scoped_tp"}
POINT_FIELDS = ("query", "stratum", "raw", "final", "completed", "attempted",
                "valid_empty", "transit", "status", "error", "certificates", "display_options")
FLAGS = ("complete", "completed", "attempted", "valid_empty", "transit", "status",
         "error", "unsupported", "timed_out", "request_shape_valid",
         "request_shape_error", "core_error_kind")
ERRORS = (ValueError, KeyError, TypeError, OSError, StopIteration, IndexError, RuntimeError, AttributeError, EOFError)
IO_SCOPE = "JSON marshal plus newline; file open/write/close; OS-buffered writes, no fsync; sidecar serialization/writing excluded"


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sig(value):
    """Field identity only, not a new evaluator or witness normalization."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def take(value, keys):
    return {key: value.get(key) for key in keys}


def logical_call(argv):
    """The declared source-control pair may differ only in binary/output path."""
    out, pos = [], 1
    while pos < len(argv):
        if argv[pos] == "-out-dir":
            need(pos + 1 < len(argv), "truncated output flag"); pos += 2
        else:
            out.append(argv[pos]); pos += 1
    return out


def native_complete(row, driver):
    return (isinstance(row, dict) and
            row.get("completed" if driver == "familybench" else "complete") is True
            and not row.get("error") and not row.get("unsupported") and not row.get("timed_out"))


def identity(row, driver):
    return (row.get("requested_source") if driver == "corechgraphbench" else
            row.get("query", {}).get("base", row.get("query", {})).get("id"))


def checked_final_vectors(row):
    """Read emitted metrics only; independent witness checking is external."""
    out = []
    for witness in row.get("final", []):
        metrics = witness["metrics"]
        arrival, boardings = metrics["arrival"], metrics["boardings"]
        need(type(arrival) is int and type(boardings) is int and boardings >= 0,
             "invalid emitted arrival/boarding metric")
        out.append((arrival, boardings))
    return out


def typed_signature(row, kind, driver):
    """Full declared output plus a narrower objective view, never just selected IDs.

    Stats/allocations/clocks are not native answers. An equal objective with
    different saved witnesses remains a full-output mismatch and cannot certify
    a source/runtime speedup. Profile direct/latest-ready values are preserved,
    not reconstructed through a production At/Reanchor or new routing math.
    """
    need(kind in KINDS, "unknown native contract")
    flags = take(row, FLAGS)
    if kind in {"bare_tb", "scoped_tp"}:
        exact = {**take(row, POINT_FIELDS),"flags":flags}
        vectors = checked_final_vectors(row)
        q = row["query"]
        objective = {"query": q, "stratum": row.get("stratum"), "flags": flags,
            "arrival_under_boarding_caps": [min((a for a, b in vectors if b <= cap), default=None)
                                            for cap in range(q["max_boardings"] + 1)]}
    elif kind == "tad":
        exact = {**take(row, ("query", "stratum", "raw", "final")), "flags": flags}
        vectors = checked_final_vectors(row)
        need(len(row.get("raw", [])) <= 1 and len(vectors) <= 1,
             "TAD completed output is not one EA witness")
        objective = {"query": row["query"], "stratum": row.get("stratum"), "flags": flags,
                     "earliest_arrival": min((a for a, _ in vectors), default=None)}
    elif kind == "range_profile":
        raw = row["raw"]
        exact = {**take(row, ("query", "stratum", "final_points", "final_direct",
                             "every_integer_ready_time")), "flags": flags,
                 "raw": take(raw, ("query", "transit_points", "direct_walking", "complete", "error"))}
        # Retain entire61-readiness grid AND compact profile/direct branches.
        # Grid equality alone is intentionally insufficient for full parity.
        objective = {"query": row["query"], "stratum": row.get("stratum"), "flags": flags,
                     "raw_query": raw.get("query"),
                     "compact_points": [take(point, ("latest_ready", "arrival", "boardings"))
                                        for point in raw.get("transit_points", [])],
                     "direct_branch": raw.get("direct_walking"),
                     "every_integer_ready_time": row.get("every_integer_ready_time")}
    else:
        raw = row["raw"]
        exact = {**take(row, ("requested_source", "requested_targets", "requested_maximum_duration", "final")),
                 "flags": flags, "raw": take(raw, ("source", "maximum_duration", "paths", "complete", "error"))}
        objective = {**take(row, ("requested_source", "requested_targets", "requested_maximum_duration")),
                     "flags": flags, "cells": [take(path, ("target", "found", "duration"))
                                              for path in row.get("final", [])]}
    return {"exact": sig(exact), "objective": sig(objective), "flags": sig(flags)}


def preparation(summary, driver):
    """Retain native measurements; do not synthesize missing prep as zero."""
    raw = summary.get("preparation", {})
    target = {"familybench": None, "profilebench": "range_raptor",
              "tadbench": "tad", "corechgraphbench": "core_ch"}[driver]
    router = raw if target is None else raw.get(target)
    router_ns = router.get("elapsed_ns") if isinstance(router, dict) else None
    if router_ns is not None:
        need(type(router_ns) is int and router_ns >= 0, "invalid selected router preparation")
    return {"selected_router_preparation_ns": router_ns, "preparation": raw,
            "input_load_ns": summary.get("input_load_ns"),
            "checker_preparation": summary.get("checker_preparation"),
            "checker_preparation_ns": summary.get("checker_preparation_ns"),
            "quality_preparation": summary.get("quality_preparation"),
            "independent_graph_audit_ns": summary.get("independent_audit_ns"),
            "note": "Router-only median is the frozen preparation gate; checker/audit/quality/control phases stay separately visible."}


def publication(row, driver, result):
    if driver != "familybench":
        need(row.get("published_response_ns") is None and row.get("serialization_ns") is None,
             "native nonstreaming driver has an unexpected publication field")
        return {"published_response_ns": None, "serialization_ns": None,
                "launch_to_first_available_answer_ns": None, "publication_contract": "not_instrumented"}
    receipt = result.get("publication_receipt", {})
    accepted = receipt.get("enabled") is True and receipt.get("valid") is True
    if accepted:
        for value in (row.get("published_response_ns"), row.get("serialization_ns"),
                      result.get("launch_to_first_available_answer_ns")):
            need(value is None or (type(value) is int and value >= 0), "invalid real publication clock")
        published,serialization,response=(row.get(key) for key in ("published_response_ns","serialization_ns","response_ns"))
        if published is not None:
            need(type(response) is int and response >= 0 and published >= response,
                 "per-row publication precedes native response")
            need(serialization is None or serialization <= published-response,
                 "per-row serialization exceeds publication-response interval")
        else:
            need(serialization is None,"serialization without a real per-row publication marker")
    return {"published_response_ns": row.get("published_response_ns") if accepted else None,
            "serialization_ns": row.get("serialization_ns") if accepted else None,
            "launch_to_first_available_answer_ns": result.get("launch_to_first_available_answer_ns") if accepted else None,
            "publication_contract": "actual_native_stream_only_not_independent_first_answer_acceptance" if accepted else "unavailable_or_unaccepted_receipt"}


def load_passes(summary, artifact, expected, driver, argv, algorithm, io, inv, observer=None):
    """Transport-injected copy of pass envelope checks; unchanged row validator.

    No inv.load_passes call: its raw-file reopening is not storage-transparent.
    Missing/extra/partial ordinary/control records invalidate the run but every
    observed row is retained by the caller. Sidecar clocks are pass IO, not row
    answer publication or request response.
    """
    selected, controls, observed, sidecars, diagnostics = [], [], [], [], []
    allowed = {algorithm, "identity"} if driver == "corechgraphbench" else {algorithm}
    for desc in summary.get("passes", summary.get("summaries", [])):
        name = desc.get("file")
        need(isinstance(name, str) and Path(name).name == name and name not in (".", ".."), "unsafe pass filename")
        payload = io.read_path(str(artifact / name), expected_sha=desc["sha256"])
        need(payload.get("algorithm") == desc.get("algorithm", algorithm) and payload.get("algorithm") in allowed
             and payload.get("repetition") == desc.get("repetition")
             and type(payload.get("warmup")) is bool and payload["warmup"] == desc.get("warmup"),
             "pass envelope/algorithm differs")
        need(isinstance(payload.get("records"), list), "pass records missing")
        observed.extend({"algorithm": payload["algorithm"], "pass_file": name, "index": index,
                         "row": row, "diagnostic": bool(payload["warmup"] or desc.get("forced"))}
                        for index, row in enumerate(payload["records"]))
        if observer is not None:
            for index, row in enumerate(payload["records"]):
                observer({"algorithm": payload["algorithm"], "pass_file": name, "index": index,
                          "diagnostic": bool(payload["warmup"] or desc.get("forced")), "row": row})
        if payload["warmup"] or desc.get("forced"):
            diagnostics.append({"file": name, "descriptor": desc}); continue
        need(payload["repetition"] == 0, "unexpected measured repetition")
        inv.validate_rows(payload, expected, driver, argv)
        target = selected if payload["algorithm"] == algorithm else controls
        target.append((desc, payload))
        io_path = str(artifact / (name + ".io.json"))
        io_record = io.read_path(io_path)
        need(io_record.get("sha256") == desc["sha256"], "IO sidecar pass hash differs")
        need(io_record.get("scope") == IO_SCOPE,"IO sidecar clock scope differs from frozen writer")
        for key in ("serialization_ns", "write_ns", "bytes"):
            need(type(io_record.get(key)) is int and io_record[key] >= 0, "invalid artifact IO field")
        sidecars.append({"path": io_path, "algorithm": payload["algorithm"], **io_record})
    need(len(selected) == 1, "missing/duplicate ordinary selected pass")
    need(len(controls) == (1 if driver == "corechgraphbench" else 0), "missing/extra mandatory control")
    return selected[0], controls, observed, sidecars, diagnostics


def project_run(item, binding, io, orches, inv, operational, original=False):
    """One bound run at a time; release full journey trees after compact output."""
    spec, old = item["spec"], item["original"]
    campaign = item["campaign"]
    context = {"id": spec["id"], "campaign": str(campaign), "kind": item["kind"],
               "driver": item["driver"], "window": spec["window"],
               "original_native_contract_id": old["spec"]["id"],
               "product": old["spec"]["variant_id"], "original_comparator": original,
               "block": None if original else spec["block"],
               "position": None if original else spec["position"],
               "runtime": None if original else take(spec["env"], ("GOGC", "GOMEMLIMIT")),
               "source_contrast": old["spec"].get("contrast"),
               "logical_call_sha256": sig(logical_call(old["spec"]["argv"]))}
    out = {**context, "binding_error": None, "run_complete": False, "rows": {}, "observed": [],
           "control_rows": {}, "control_native_rows": {}, "artifact_io": [], "publication_first_answer_accepted": False,
           "analysis_status": "awaiting_bound_native_outputs"}
    expected, driver = None, item["driver"]
    try:
        argv = spec["argv"]
        workload_path = inv.flag(argv, "-queries")
        pin = next(x for x in old["freeze"]["input_files"] if x["path"] == workload_path)
        workload = io.read_path(workload_path, expected_sha=pin["sha256"])
        expected = inv.expected_items(workload, driver, argv)
        out.update(offered=len(expected), expected_locators=list(expected), workload_sha256=pin["sha256"],
                   dataset_sha256=workload["dataset_sha256"])
        if original:
            command = io.read_path(str(campaign / spec["id"] / "command.json"))
            result = io.read_path(str(campaign / spec["id"] / "result.json"))
            envelope = inv.validate_envelope(spec, command, result, old["freeze"], campaign / spec["id"], campaign)
        else:
            command, result, envelope = orches.command_binding(item, binding, io, inv, operational)
            need(envelope is not None, "run was not launched")
        argv, driver, role, inputs = envelope
        dataset_sha = inputs[inv.flag(argv,"-dataset")]["sha256"]
        need(workload.get("dataset_sha256") == dataset_sha,"workload/model consumed SHA binding differs")
        out["supervisor"] = take(result, ("ok", "returncode", "signal", "termination", "timed_out", "process_wall_s",
            "elapsed_wall_s", "sampled_peak_process_group_rss_bytes", "wait4_ru_maxrss_kib", "user_cpu_s", "system_cpu_s", "source_contents_unchanged"))
        out["measurement_envelope"] = take(command, ("requested_cpu_affinity", "monitor_cpu_affinity",
            "rss_sample_interval_s", "sampled_rss_safety_stop_bytes", "environment"))
        artifact = campaign / spec["id"] / "artifact"
        manifest_name = "manifest.json" if driver in {"profilebench", "tadbench"} else "summary.json"
        summary = io.read_path(str(artifact / manifest_name))
        algorithm = inv.algorithm(argv, driver)
        inv.validate_manifest(summary, command, role, driver, algorithm, dataset_sha, pin["sha256"])
        out["native_manifest_status"] = take(summary,("success","phase","error","complete","algorithm"))
        out.update(preparation(summary, driver))
        out["preparation_status"] = inv.preparation_state(summary, driver, algorithm)
        out["native_preparation_diagnosis"] = inv.preparation_diagnosis(summary,driver,out["preparation_status"])
        def observation(value):
            native = value["row"]
            brief = ({"offered_locator": identity(native, driver), **take(native, FLAGS + ("response_ns", "core_ns")),
                      "diagnostic_saved_output_sha256": sig({k: v for k, v in native.items() if k not in {
                          "core_ns", "response_ns", "core_allocated_bytes", "stats", "detail", "recommendation_quality"}})}
                     if isinstance(native, dict) else {"invalid_row_type": type(native).__name__})
            out["observed"].append({**{k: v for k, v in value.items() if k != "row"}, **brief})
        chosen, controls, observed, sidecars, diagnostics = load_passes(summary, artifact, expected, driver, argv, algorithm, io, inv, observation)
        out.update(artifact_io=sidecars, diagnostic_passes=diagnostics,
                   selected_pass_descriptor=chosen[0], control_pass_descriptors=[value[0] for value in controls])
        # Full observations stay separate from compact accepted row signatures.
        complete = (result.get("ok") is True and summary.get("success") is True
                    and out["preparation_status"] == "complete")
        for row in chosen[1]["records"]:
            key = identity(row, driver)
            attempted = driver != "familybench" or row.get("attempted") is True
            signatures = typed_signature(row, item["kind"], driver) if native_complete(row, driver) else None
            out["rows"][key] = {"offered_locator": key, "native_complete": native_complete(row, driver),
                "flags": take(row, FLAGS), "signature": signatures,
                "diagnostic_saved_output_sha256": sig({k: v for k, v in row.items() if k not in {
                    "core_ns", "response_ns", "core_allocated_bytes", "stats", "detail", "recommendation_quality"}}),
                "response_ns": row.get("response_ns") if attempted else None,
                "core_ns": row.get("core_ns") if attempted else None,
                "published": publication(row, driver, result),
                "grid_materialization_validation_ns": None,
                "grid_clock_scope": "profile response includes checking/materialization; no separately measured pure-grid clock" if driver == "profilebench" else None}
            complete = complete and native_complete(row, driver)
        for _, payload in controls:
            for row in payload["records"]:
                key = identity(row, driver)
                out["control_rows"][key] = typed_signature(row, "corech_graph", driver) if native_complete(row, driver) else None
                out["control_native_rows"][key] = {"native_complete": native_complete(row, driver),
                    "flags": take(row, FLAGS), "response_ns": row.get("response_ns"), "core_ns":row.get("core_ns")}
                complete = complete and native_complete(row, driver)
        out["run_complete"] = bool(complete)
        out["analysis_status"] = inv.classify_failure(summary, result, out["preparation_status"],
                                                      [inv.row_status(row, driver) for row in chosen[1]["records"]])
        out["exact_signature_sha256"] = sig({"rows": {k: v["signature"] for k, v in out["rows"].items()},
                                                   "controls": out["control_rows"]})
    except ERRORS as exc:
        out["binding_error"] = type(exc).__name__ + ": " + str(exc)
        out["analysis_status"] = "analysis_binding_or_transport_error_not_native_family_failure"
        out["run_complete"] = False
        out.setdefault("offered", len(expected) if expected is not None else None)
        out.setdefault("expected_locators", list(expected) if expected is not None else [])
    return out


def compare(left, right):
    """Missing/incomplete remains unknown even if partial output hashes match."""
    expected = set(left.get("expected_locators", []))
    shape = (expected == set(right.get("expected_locators", [])) and bool(expected)
             and left.get("kind") == right.get("kind")
             and left.get("dataset_sha256") == right.get("dataset_sha256")
             and left.get("workload_sha256") == right.get("workload_sha256"))
    ready = shape and left["run_complete"] and right["run_complete"]
    checks = []
    for key in sorted(expected | set(right.get("expected_locators", []))):
        a, b = left["rows"].get(key), right["rows"].get(key)
        full = bool(a and b and a["native_complete"] and b["native_complete"] and a["signature"] and b["signature"])
        checks.append({"offered_locator": key,
            "exact": full and a["signature"]["exact"] == b["signature"]["exact"],
            "objective": full and a["signature"]["objective"] == b["signature"]["objective"],
            "status": "complete_pair" if full else "incomplete_or_missing",
            "incomplete_outcome_difference": (a.get("diagnostic_saved_output_sha256") != b.get("diagnostic_saved_output_sha256")) if a and b and not full else None,
            "baseline_flags": a.get("flags") if a else None, "candidate_flags": b.get("flags") if b else None})
    control_exact = left.get("control_rows") == right.get("control_rows")
    mismatch = any(check["status"] == "complete_pair" and not check["exact"] for check in checks)
    exact = ready and all(check["exact"] for check in checks) and control_exact
    return {"baseline": left["id"], "candidate": right["id"],
            "status": "exact" if exact else "mismatch" if mismatch or (ready and not control_exact) else "unknown",
            "complete_offered_pair": bool(ready), "objective_equal": bool(ready and all(check["objective"] for check in checks)),
            "control_output_exact": control_exact if ready else None, "rows": checks}


def qualify_quality(run, evidence):
    """Externally accepted typed witness/quality projection, no new scoring here."""
    record = evidence.get(run["id"])
    return bool(record and record.get("run_id") == run["id"]
        and record.get("kind") == run["kind"] and record.get("promotion_accepted") is True
        and record.get("exact_signature_sha256") == run.get("exact_signature_sha256")
        and record.get("independently_feasible_complete_rows") == run.get("offered")
        and isinstance(record.get("quality_comparison_key"), str)
        and isinstance(record.get("quality_signature_sha256"), str))


def pooled_clock(runs, field):
    return [row[field] for run in runs for row in run["rows"].values() if row.get(field) is not None]


def measurement_valid(run):
    envelope = run.get("measurement_envelope",{})
    return (envelope.get("rss_sample_interval_s") == .1
            and envelope.get("requested_cpu_affinity") == "0-3"
            and envelope.get("monitor_cpu_affinity") == [8])


def graph_internal_control(run):
    """Actual two algorithms, same graph process. No separate RSS/prep gate."""
    expected = set(run.get("expected_locators", []))
    rows = []
    for key in sorted(expected):
        selected = run["rows"].get(key)
        control = run.get("control_native_rows", {}).get(key)
        csig = run.get("control_rows", {}).get(key)
        complete = bool(selected and control and selected["native_complete"]
                        and control["native_complete"] and selected["signature"] and csig)
        rows.append({"source_anchor":key, "complete_pair":complete,
            "native_objective_equal": bool(complete and selected["signature"]["objective"] == csig["objective"]),
            "full_witness_output_equal": bool(complete and selected["signature"]["exact"] == csig["exact"]),
            "corech_response_ns":selected.get("response_ns") if selected else None,
            "identity_response_ns":control.get("response_ns") if control else None,
            "corech_core_ns":selected.get("core_ns") if selected else None,
            "identity_core_ns":control.get("core_ns") if control else None,
            "corech_flags":selected.get("flags") if selected else None,
            "identity_flags":control.get("flags") if control else None})
    complete = bool(expected) and run["run_complete"] and all(row["complete_pair"] for row in rows)
    return {"id":run["id"], "complete_offered_graph_control":bool(complete),
        "native_objective_equal":bool(complete and all(row["native_objective_equal"] for row in rows)),
        "rows":rows, "scope":"Walking graph anchors/cells only; both algorithms share one process. No transit/OTP, separate-algorithm RSS, or independent first-answer claim."}


def frontier_contrast(left, right, stats, quality_evidence, kind):
    need(len(left) == len(right) and bool(left), "empty/unmatched contrast")
    a = {(run["block"], run["window"]): run for run in left}
    b = {(run["block"], run["window"]): run for run in right}
    need(len(a) == len(left) and len(b) == len(right) and set(a) == set(b), "duplicate/missing contrast block/window")
    need({block for block, _ in a} == {0, 1}, "both reverse blocks required")
    comparisons, clocks = [], []
    for key in sorted(a):
        x, y = a[key], b[key]
        comparison = compare(x, y)
        rx = stats.distribution(pooled_clock([x], "response_ns"))
        ry = stats.distribution(pooled_clock([y], "response_ns"))
        enough = rx["count"] == x["offered"] and ry["count"] == y["offered"]
        comparisons.append({**comparison, "block": key[0], "window": key[1],
                            "raw_response_clocks_complete": enough,
                            "p95_response_ratio": stats.ratio(rx["p95"], ry["p95"])})
        clocks.append(enough)
    ratios = {}
    for block in (0, 1):
        av = pooled_clock([run for run in left if run["block"] == block], "response_ns")
        bv = pooled_clock([run for run in right if run["block"] == block], "response_ns")
        ratios[str(block)] = stats.ratio(stats.distribution(av)["p95"], stats.distribution(bv)["p95"])
    rss_a = [run.get("supervisor", {}).get("sampled_peak_process_group_rss_bytes") for run in left]
    rss_b = [run.get("supervisor", {}).get("sampled_peak_process_group_rss_bytes") for run in right]
    prep_a = [run.get("selected_router_preparation_ns") for run in left]
    prep_b = [run.get("selected_router_preparation_ns") for run in right]
    def resource_ratio(x, y, reducer):
        return stats.ratio(reducer(x), reducer(y)) if all(value is not None for value in x+y) else None
    rss_ratio = resource_ratio(rss_a, rss_b, max)
    prep_ratio = resource_ratio(prep_a, prep_b, statistics.median)
    exact = (all(check["status"] == "exact" for check in comparisons)
             and all(run.get("original_parity_status") == "exact" for run in left+right))
    envelope = all(measurement_valid(run) for run in left+right)
    native_gate = (exact and all(clocks) and envelope
        and all(value is not None and value <= .97 for value in ratios.values())
        and all(check["p95_response_ratio"] is not None and check["p95_response_ratio"] <= 1.03 for check in comparisons)
        and rss_ratio is not None and rss_ratio <= 1.05 and prep_ratio is not None and prep_ratio <= 1.05)
    independent = all(qualify_quality(run, quality_evidence) for run in left+right)
    quality_equal = independent and all(
        quality_evidence[a[key]["id"]]["quality_comparison_key"] == quality_evidence[b[key]["id"]]["quality_comparison_key"]
        and quality_evidence[a[key]["id"]]["quality_signature_sha256"] == quality_evidence[b[key]["id"]]["quality_signature_sha256"] for key in a)
    return {"kind": kind, "baseline_ids": [run["id"] for run in left], "candidate_ids": [run["id"] for run in right],
        "comparisons": comparisons, "pooled_raw_response_p95_ratio_by_block": ratios,
        "max_whole_process_sampled_rss_ratio": rss_ratio, "median_selected_router_preparation_ratio": prep_ratio,
        "native_exact_clock_gate": bool(native_gate), "independent_quality_equality_accepted": bool(quality_equal),
        "passes_frozen_native_response_same_cost_gate": bool(native_gate and quality_equal),
        "publication_same_cost_gate_performed":False,"headline_publication_speedup_claim":False,
        "promotion_blocker": None if quality_equal else "separate independent typed witness/quality acceptance missing or unequal",
        "scope": "Raw whole native-unit response, never publication for nonstreaming drivers; no divided profile/target latency."}


def combine(projected, original_pairs, stats, quality_evidence):
    """All216 and all six runtime cells remain in the report, even dominated."""
    need(len(projected) == 216 and len({run["id"] for run in projected}) == 216, "new216 exact census required")
    need(len(original_pairs) == 216 and {pair["candidate"] for pair in original_pairs} == {run["id"] for run in projected},
         "all216 original/native parity pairs required")
    census = Counter(run["kind"] for run in projected)
    need(census == Counter(range_profile=96, tad=48, corech_graph=48, bare_tb=12, scoped_tp=12), "native216 kinds differ")
    tuples = {(run["original_native_contract_id"], run["block"], run["runtime"]["GOGC"], run["runtime"]["GOMEMLIMIT"]) for run in projected}
    originals = {run["original_native_contract_id"] for run in projected}
    need(len(originals) == 18 and len(tuples) == 216 and tuples == {
        (oid, block, gc, heap) for oid in originals for block in (0, 1) for gc, heap in CELLS}, "exact18x6x2 closure differs")
    need(Counter(run["window"] for run in projected) == Counter(dict(zip(WINDOWS, (48,48,48,72)))), "window census differs")
    pair_by_id = {pair["candidate"]: pair for pair in original_pairs}
    need(all(pair_by_id[run["id"]].get("baseline") == run["original_native_contract_id"] for run in projected),
         "original/native parity baseline binding differs")
    projected = [{**run, "original_parity_status": pair_by_id[run["id"]]["status"]} for run in projected]
    products = defaultdict(list)
    for run in projected:
        products[run["product"]].append(run)
    contrasts, cells = [], []
    for product, runs in sorted(products.items()):
        by_cell = defaultdict(list)
        for run in runs:
            by_cell[(run["runtime"]["GOGC"], run["runtime"]["GOMEMLIMIT"])].append(run)
        need(set(by_cell) == set(CELLS), "missing/extra runtime cell")
        signatures = {(run["original_native_contract_id"], run["block"]) for run in runs}
        originals = {run["original_native_contract_id"] for run in runs}
        need(len(signatures) == 2*len(originals) and len(runs) == 12*len(originals), "product original/runtime/block census differs")
        for cell, group in sorted(by_cell.items()):
            need(len(group) == 2*len(originals), "runtime cell has missing fresh processes")
            cells.append({"product": product, "runtime": {"GOGC": cell[0], "GOMEMLIMIT": cell[1]},
                "run_ids": [run["id"] for run in group],
                "offered": sum(run["offered"] for run in group) if all(run.get("offered") is not None for run in group) else None,
                "known_offered_count":sum(run["offered"] for run in group if run.get("offered") is not None),
                "unknown_offered_run_ids":[run["id"] for run in group if run.get("offered") is None],
                "observed_native_complete": sum(row["native_complete"] for run in group for row in run["rows"].values()),
                "native_response_ns": stats.distribution(pooled_clock(group, "response_ns")),
                "original_parity_and_envelope_admitted_native_response_ns":stats.distribution(pooled_clock(
                    [run for run in group if run["original_parity_status"] == "exact" and measurement_valid(run)],"response_ns")),
                "native_core_ns": stats.distribution(pooled_clock(group, "core_ns")),
                "publication_response_ns": stats.distribution([row["published"]["published_response_ns"] for run in group for row in run["rows"].values() if row["published"]["published_response_ns"] is not None]),
                "retained": True, "window_pooling_scope": "same driver/product only; full per-block/window clocks also retained"})
        for baseline, candidate in itertools.permutations(CELLS, 2):
            contrast = frontier_contrast(by_cell[baseline], by_cell[candidate], stats, quality_evidence, "registered_runtime_cell")
            contrasts.append({"product": product, "baseline_runtime": baseline, "candidate_runtime": candidate, **contrast})
    source_contrasts = []
    controls = [run for run in projected if run["kind"] == "range_profile" and run["source_contrast"] == "frozen_native_range_control"]
    candidates = [run for run in projected if run["kind"] == "range_profile" and run["source_contrast"] is None]
    need(len(controls) == len(candidates) == 48, "frozen range source/control census differs")
    for gc, heap in CELLS:
        left = [run for run in controls if (run["runtime"]["GOGC"], run["runtime"]["GOMEMLIMIT"]) == (gc,heap)]
        right = [run for run in candidates if (run["runtime"]["GOGC"], run["runtime"]["GOMEMLIMIT"]) == (gc,heap)]
        # Workload differs by window, so validate each exact pair, not an
        # across-window logical-call equality.
        by_key = {(run["block"], run["window"]): run for run in left}
        need(all(run["logical_call_sha256"] == by_key[(run["block"],run["window"])]["logical_call_sha256"]
                 for run in right), "range source/control changed native argv/workload/config contract")
        source_contrasts.append({"runtime": {"GOGC":gc,"GOMEMLIMIT":heap},
            **frontier_contrast(left, right, stats, quality_evidence, "frozen_range_source_control")})
    return {"schema": "native216-typed-native-frontier-draft-v1", "processes": 216,
        "native_kind_process_counts": dict(census), "original_pair_statuses": dict(Counter(pair["status"] for pair in original_pairs)),
        "original_parity": original_pairs, "runtime_cells": cells, "runtime_contrasts": contrasts,
        "frozen_range_source_contrasts": source_contrasts,
        "corech_identity_controls": [graph_internal_control(run) for run in projected if run["kind"] == "corech_graph"],
        "accepted_native_response_same_cost_edges": [{"product": row["product"], "baseline": row["baseline_runtime"], "candidate": row["candidate_runtime"]}
                                     for row in contrasts if row["passes_frozen_native_response_same_cost_gate"]],
        "independent_quality_evidence_available": bool(quality_evidence),
        "limits": ["All six cells retained. No automatic winner, new cap, target or source hypothesis.",
            "Objective/witness parity is not independent feasibility, full3D/profile completeness, global optimum or production latency.",
            "Original18-to-new216 output parity is not equal-envelope timing; only new .1s CPU0-3/monitor8 fresh processes enter runtime gates.",
            "CoreCH rows/cells are walking graph evidence only; TAD is singleEA; scopedTP stays fixed12destination tune-only.",
            "No native profile/TAD/graph publication stream is invented. No request latency is divided by61 or target count.",
            "Grid materialization/validation has no isolated clock in these drivers; response/core and pass serialization remain separate.",
            "Missing/partial/unsupported/failed output is unknown or mismatch, never exact parity or zero-latency success."]}


def project_window(binding, io, out, orches, inv):
    """Actual native data only after separate input/reader/quiet acceptance.

    Produces compact rows and original18-v-new216 parity; no model read. Output
    directory must have been created exclusively by the authorized caller.
    A combined frontier requires all four terminal window projections, separately
    accepted source/storage closure, and injected unchanged stats helpers.
    """
    window = binding["window"]
    need(window in WINDOWS and binding.get("mode") == "inventory", "no model/scalar mode permitted here")
    rows, census, operational = orches.census(binding, io, inv)
    need(Path(out).is_dir() and not any(Path(out).iterdir()), "fresh exclusive output directory required")
    cache, projected, pairs = {}, [], []
    for item in rows:
        if item["spec"]["window"] != window:
            continue
        oid = item["original"]["spec"]["id"]
        if oid not in cache:
            # A frozen plan's directory is NOT its actual output campaign.
            # Bind the two original roots explicitly in the consuming binding.
            links = [entry for entry in binding["original_native_campaigns"]
                     if entry["plan"] == item["original"]["original_plan"]]
            need(len(links) == 1 and Path(links[0]["campaign"]).is_absolute(),
                 "missing/ambiguous actual original native campaign binding")
            original = {"campaign": Path(links[0]["campaign"]),
                        "spec": item["original"]["spec"], "original": item["original"],
                        "driver": item["driver"], "kind": item["kind"]}
            cache[oid] = project_run(original, binding, io, orches, inv, operational, original=True)
        run = project_run(item, binding, io, orches, inv, operational)
        pair = compare(cache[oid], run)
        run["original_parity_status"] = pair["status"]
        run["native_response_clock_admitted"] = pair["status"] == "exact" and measurement_valid(run)
        for row in run["rows"].values():
            row["accepted_native_contract_response_ns"] = row["response_ns"] if run["native_response_clock_admitted"] else None
        projected.append(run); pairs.append(pair)
    need(len(projected) == (72 if window == WINDOWS[3] else 48), "projected window count differs")
    orches.put(Path(out)/"NATIVE_RUN_PROJECTIONS.json", projected)
    orches.put(Path(out)/"ORIGINAL_PARITY_PAIRS.json", pairs)
    report = {"schema":"native216-parity-clock-window-draft-v1", "window":window,
        "process_census":census, "processes":len(projected),
        "original_pair_statuses":dict(Counter(pair["status"] for pair in pairs)),
        "accepted_native_contract_clock_rows":sum(row["accepted_native_contract_response_ns"] is not None for run in projected for row in run["rows"].values()),
        "independent_quality_promotion_performed":False, "model_count":0,
        "source_or_router_execution":False, "canonical_inputs":dict(io.bindings)}
    orches.put(Path(out)/"REPORT.json", report)
    return report
