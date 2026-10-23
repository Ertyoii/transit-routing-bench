#!/usr/bin/env python3
"""Exact offered-query output parity for predeclared source-only controls.

This is post-run analysis, never a router and never used during headline timing.
It deliberately ignores clocks, allocations, implementation detail counters and
selector output, while preserving raw/final witness order, flags and certificates.
An incomplete pair is unknown, not a successful parity comparison.
"""
import argparse
import hashlib
import json
from pathlib import Path

FIELDS = ("query", "stratum", "raw", "final", "completed", "attempted",
          "valid_empty", "transit", "status", "error", "certificates")
SOURCE_GROUPS = (
    ("raptor-early-control", "raptor-early-storage", "raptor-early-slab"),
    ("raptor-control", "raptor-storage"),
    ("mc-early-control", "mc-early-storage", "mc-early-slab"),
    ("ultra-capped-control", "ultra-capped-storage"),
    ("tb-capped-control", "tb-capped-storage"),
)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(campaign, run, bindings):
    root = campaign / run["id"]
    summary_path = root / "artifact/summary.json"
    result_path = root / "result.json"
    if not summary_path.exists() or not result_path.exists():
        return None, "missing_summary_or_supervisor"
    summary, result = read(summary_path), read(result_path)
    bindings[str(summary_path)] = sha(summary_path)
    bindings[str(result_path)] = sha(result_path)
    if not result.get("ok") or summary.get("preparation", {}).get("complete") is not True:
        return None, "process_or_preparation_not_complete"
    argv = run["argv"]
    workload_path = Path(argv[argv.index("-queries") + 1])
    algorithm = argv[argv.index("-algorithm") + 1]
    workload = read(workload_path)
    bindings[str(workload_path)] = sha(workload_path)
    expected = {item["query"]["id"]: item for item in workload["items"]}
    if not expected or len(expected) != len(workload["items"]):
        raise ValueError("empty or duplicate frozen offered query set")
    if summary.get("algorithm") != algorithm or summary.get("queries_sha256") != bindings[str(workload_path)]:
        raise ValueError("summary algorithm/workload binding mismatch")
    records = {}
    ordinary_passes = 0
    for desc in summary.get("passes", []):
        if desc.get("warmup") or desc.get("forced"):
            continue
        filename = desc.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("unsafe pass filename")
        path = root / "artifact" / filename
        if sha(path) != desc["sha256"]:
            raise ValueError("pass digest changed")
        bindings[str(path)] = desc["sha256"]
        payload = read(path)
        if (payload.get("algorithm") != algorithm or payload.get("repetition") != desc.get("repetition")
                or payload.get("warmup") is not False):
            raise ValueError("ordinary pass algorithm/repetition/warmup mismatch")
        ordinary_passes += 1
        for row in payload["records"]:
            key = row["query"]["id"]
            if key in records:
                raise ValueError("duplicate query in measured pass")
            if key not in expected or row["query"] != expected[key]["query"] or row["stratum"] != expected[key]["stratum"]:
                raise ValueError("ordinary row differs from frozen offered query")
            records[key] = {field: row.get(field) for field in FIELDS}
    if ordinary_passes != 1 or set(records) != set(expected):
        return None, "missing_or_extra_ordinary_pass_or_offered_record"
    return records, None


def compare(campaign, out):
    campaign = Path(campaign).resolve()
    plan_path = campaign / "plan.json"
    plan = read(plan_path)
    bindings = {str(plan_path): sha(plan_path), str(Path(__file__)): sha(__file__)}
    by_cell = {(r["block"], r["window"], r["variant_id"]): r for r in plan["runs"]}
    cache, checks = {}, []
    for group in SOURCE_GROUPS:
        for block, window in sorted({(r["block"], r["window"]) for r in plan["runs"]}):
            baseline = by_cell.get((block, window, group[0]))
            if baseline is None:
                continue
            for variant in group[1:]:
                candidate = by_cell.get((block, window, variant))
                if candidate is None:
                    continue
                for run in (baseline, candidate):
                    if run["id"] not in cache:
                        cache[run["id"]] = load(campaign, run, bindings)
                left, le = cache[baseline["id"]]
                right, re = cache[candidate["id"]]
                entry = {"baseline": baseline["id"], "candidate": candidate["id"],
                         "block": block, "window": window}
                if le or re:
                    entry.update(status="unknown", baseline_error=le, candidate_error=re)
                else:
                    keys = sorted(set(left) | set(right))
                    differences = []
                    incomplete = []
                    incomplete_differences = []
                    for key in keys:
                        a, b = left.get(key), right.get(key)
                        if a is None or b is None:
                            differences.append({"query_id": key, "fields": ["missing_record"]})
                            continue
                        changed = [field for field in FIELDS if a[field] != b[field]]
                        if not a["completed"] or not b["completed"]:
                            incomplete.append(key)
                            if changed:
                                incomplete_differences.append({"query_id": key, "fields": changed})
                        elif changed:
                            differences.append({"query_id": key, "fields": changed})
                    entry.update(status="mismatch" if differences else "unknown" if incomplete else "exact",
                                 offered=len(keys), differences=differences,
                                 incomplete_query_ids=incomplete,
                                 incomplete_outcome_differences=incomplete_differences)
                checks.append(entry)
    report = {"schema": "sg-v2-exact-native-source-output-parity-v1",
              "scope": "Exact raw/final witness order, flags and native certificates only; no claim about selector equality or performance.",
              "compared_fields": list(FIELDS), "source_groups": SOURCE_GROUPS,
              "inputs": bindings, "checks": checks,
              "exact_checks": sum(x["status"] == "exact" for x in checks),
              "unknown_checks": sum(x["status"] == "unknown" for x in checks),
              "mismatch_checks": sum(x["status"] == "mismatch" for x in checks)}
    with Path(out).open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("exact_checks", "unknown_checks", "mismatch_checks")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    compare(args.campaign, args.out)
