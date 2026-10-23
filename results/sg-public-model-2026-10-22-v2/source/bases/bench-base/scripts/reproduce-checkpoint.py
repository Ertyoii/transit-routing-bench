#!/usr/bin/env python3
"""Tiny public smoke reproduction; no network, feed download or load campaign."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new output directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    env = dict(os.environ, GOTOOLCHAIN="local", GOWORK="off", GOPROXY="off",
               GOSUMDB="off", GOMAXPROCS="2")
    binary = output / "familybench"
    subprocess.run(["sh", "scripts/build.sh", "familybench", str(binary)],
                   cwd=root, env=env, check=True)
    cases = [
        ("raptor_early", None), ("mc_raptor_early", None),
        ("trip_based_capped", "tb"),
        ("ultra_transfer_complete_capped", "ultra-control"),
        ("ultra_cap_safe_stay_witness_subset_v1", "ultra-subset"),
        ("flash_tb_static_stop_pair_suffix_flags_role_caps_v1", "flash"),
        ("tp_destination_fixed_caps_experimental", "tp"),
        ("tp_destination_fixed_caps_experimental", "tp-partial"),
        ("trex_static_caps_mandatory_verified_experimental", "trex"),
    ]
    results = []
    for index, (name, config) in enumerate(cases):
        dest = output / f"{index:02d}-{config or name}"
        command = [str(binary), "-fixture", "testdata/scoped.manifest.json",
                   "-algorithm", name, "-out-dir", str(dest),
                   "-warmups", "0", "-repetitions", "1", "-batch-size", "3"]
        if config:
            command += ["-scoped-config", f"testdata/scoped-config/{config}.json"]
        subprocess.run(command, cwd=root, env=env, check=True)
        summary = json.loads((dest / "summary.json").read_text())
        assert summary["success"] is True
        rows = json.loads((dest / "pass-00.json").read_text())["records"]
        assert len(rows) == 3
        by_id = {row["query"]["id"]: row for row in rows}
        expected = {"cap-hidden": 30, "broader-access": 20, "unreachable": None}
        if config == "tp-partial":
            assert all(not row["attempted"] and not row["completed"]
                       and row["status"] == "not_run_preparation_unavailable"
                       for row in rows)
        else:
            for query_id, arrival in expected.items():
                row = by_id[query_id]
                if config == "tp" and query_id == "broader-access":
                    assert not row["completed"] and row["status"] == "unsupported_semantics"
                elif config == "trex" and query_id == "cap-hidden":
                    assert not row["completed"] and not row["raw"] and not row["final"]
                    assert row["status"] == "unsupported_cap_certificate"
                else:
                    assert row["attempted"] and row["completed"], row
                    assert len(row["raw"]) == len(row["final"])
                    got = min((v["metrics"]["arrival"] for v in row["final"]), default=None)
                    assert got == arrival, (name, query_id, got, arrival)
                    assert row["valid_empty"] == (arrival is None)
                    assert row["transit"] == (arrival is not None)
        forced = json.loads((dest / "forced-deadline.json").read_text())["records"]
        assert len(forced) == 3 and not any(row["completed"] for row in forced)
        results.append({"algorithm": name, "configuration": config,
                        "summary": str(dest.relative_to(output) / "summary.json")})
    (output / "smoke.json").write_text(json.dumps({
        "success": True, "scope": "tiny synthetic functionality only; no SLA or full-model reproduction",
        "cases": results}, indent=2) + "\n")
    print("PASS: nine isolated synthetic runs; raw/final outcomes and forced deadlines checked")


if __name__ == "__main__":
    main()
