#!/usr/bin/env python3
"""Metadata-only SG workload planning and normalized-input binding; no routing calls.

Plan is immutable and outcome-independent. Bind must not change selected queries.
Only Python standard library is used. Full metadata and raw timetable are private
research inputs and are not copied into public repositories by this program.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import zipfile

SCHEMA = "sg-metadata-workload-plan-v1"
SEED = 20261020
STRATA = [("spatial_balanced", 30), ("uniform_parent_od", 25),
          ("network_structure", 20), ("nearby_stop_density_proxy", 15),
          ("temporal_coverage", 10)]
PROFILES = {
    "primary_1h_walk600": {"horizon_seconds": 3600, "walking_limits": {
        "access_seconds": 600, "egress_seconds": 600,
        "transfer_seconds": 600, "direct_seconds": 600}, "max_walk_seconds": 3000},
    "binding_total2400_walk600": {"horizon_seconds": 3600, "walking_limits": {
        "access_seconds": 600, "egress_seconds": 600,
        "transfer_seconds": 600, "direct_seconds": 600}, "max_walk_seconds": 2400},
    "legacy_walk900_total3900": {"horizon_seconds": 3600, "walking_limits": {
        "access_seconds": 600, "egress_seconds": 600,
        "transfer_seconds": 900, "direct_seconds": 600}, "max_walk_seconds": 3900},
    "long_horizon_2h_walk600": {"horizon_seconds": 7200, "walking_limits": {
        "access_seconds": 600, "egress_seconds": 600,
        "transfer_seconds": 600, "direct_seconds": 600}, "max_walk_seconds": 3000},
}


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, obj):
    data = canonical(obj)
    with Path(path).open("xb") as f:
        f.write(data)
    return digest(data)


class HashRNG:
    """SHA256 counter stream with unbiased rejection randbelow; stable across Python releases."""
    def __init__(self, tag):
        self.tag = str(tag)
        self.counter = 0

    def below(self, n):
        if n < 1:
            raise ValueError("empty selection domain")
        ceiling = (1 << 256) - ((1 << 256) % n)
        while True:
            data = f"sg-workload-v1|{SEED}|{self.tag}|{self.counter}".encode()
            self.counter += 1
            value = int.from_bytes(hashlib.sha256(data).digest(), "big")
            if value < ceiling:
                return value % n

    def pick(self, seq):
        return seq[self.below(len(seq))]


def distance_m(a, b):
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(max(0.0, h))))


def csv_in(z, filename):
    with z.open(filename) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))


def metadata_from_gtfs(path):
    with zipfile.ZipFile(path) as z:
        stop_rows = csv_in(z, "stops.txt")
        routes = {r["route_id"]: r for r in csv_in(z, "routes.txt")}
        trips = {r["trip_id"]: r for r in csv_in(z, "trips.txt")}
        times = csv_in(z, "stop_times.txt")
        frequencies = csv_in(z, "frequencies.txt")
    source_stops = {s["stop_id"]: s for s in stop_rows}
    if len(source_stops) != len(stop_rows):
        raise ValueError("duplicate stop_id")
    meta = {}
    for sid, s in sorted(source_stops.items()):
        if int(s.get("location_type") or 0) != 0:
            continue
        lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"invalid coordinate: {sid}")
        parent = s.get("parent_station", "") or sid
        if parent not in source_stops:
            raise ValueError(f"missing parent_station: {sid}")
        meta[sid] = {"stop_id": sid, "name": s.get("stop_name", ""),
                     "lat": lat, "lon": lon, "parent_group": parent,
                     "location_type": 0}
    if len(meta) < 2:
        raise ValueError("at least two eligible passenger stops required")
    adjacency = defaultdict(set)
    stop_trips = defaultdict(set)
    trip_stops = defaultdict(list)
    mode = defaultdict(set)
    for row in times:
        sid, tid = row["stop_id"], row["trip_id"]
        if sid in meta:
            stop_trips[sid].add(tid)
            route = routes.get(trips.get(tid, {}).get("route_id", ""), {})
            mode[sid].add(str(route.get("route_type", "unknown")))
        trip_stops[tid].append((int(row["stop_sequence"]), sid))
    for rows in trip_stops.values():
        rows.sort()
        for (_, a), (_, b) in zip(rows, rows[1:]):
            if a in meta and b in meta and a != b:
                adjacency[a].add(b)
                adjacency[b].add(a)
    # Structural frequency proxy only: sum one modeled departures/hour per
    # distinct trip pattern, not normalized-event density or observed demand.
    trip_rates = defaultdict(float)
    for row in frequencies:
        headway = int(row["headway_secs"])
        if headway <= 0:
            raise ValueError("invalid frequency headway")
        trip_rates[row["trip_id"]] += 3600.0 / headway
    tiny_grid = defaultdict(list)
    for sid, m in meta.items():
        tiny_grid[(math.floor(m["lat"] / .01), math.floor(m["lon"] / .01))].append(sid)
    groups = defaultdict(list)
    spatial = defaultdict(list)
    for sid, m in meta.items():
        groups[m["parent_group"]].append(sid)
        m["adjacent_stop_degree"] = len(adjacency[sid])
        m["trip_pattern_count"] = len(stop_trips[sid])
        m["modeled_departures_per_hour_proxy"] = round(sum(trip_rates[t] for t in sorted(stop_trips[sid])), 6)
        m["route_types"] = sorted(mode[sid])
        m["spatial_cell_0p025deg"] = [math.floor(m["lat"] / .025), math.floor(m["lon"] / .025)]
        spatial[tuple(m["spatial_cell_0p025deg"])].append(sid)
        cell = (math.floor(m["lat"] / .01), math.floor(m["lon"] / .01))
        nearby = 0
        # 840m = 600s at assumed 1.4m/s, a geometric density proxy, NOT walking access.
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for other in tiny_grid.get((cell[0] + di, cell[1] + dj), []):
                    o = meta[other]
                    if distance_m((m["lat"], m["lon"]), (o["lat"], o["lon"])) <= 840:
                        nearby += 1
        m["nearby_stops_840m_geometric_proxy"] = nearby
    return meta, {k: sorted(v) for k, v in groups.items()}, {k: sorted(v) for k, v in spatial.items()}


def allocation(n):
    """Largest-remainder allocation of immutable primary construction strata."""
    counts = {k: n * p // 100 for k, p in STRATA}
    remainders = sorted(STRATA, key=lambda kp: (-(n * kp[1] % 100), kp[0]))
    for key, _ in remainders[:n - sum(counts.values())]:
        counts[key] += 1
    return counts


def pair_key(meta, origin, destination):
    return tuple(sorted((meta[origin]["parent_group"], meta[destination]["parent_group"])))


def build_clusters(stage, n, meta, groups, spatial, used, windows, departures):
    rng = HashRNG(stage)
    ids, gids, cells = sorted(meta), sorted(groups), sorted(spatial)
    degree = sorted(ids, key=lambda s: (meta[s]["adjacent_stop_degree"], meta[s]["modeled_departures_per_hour_proxy"], s))
    density = sorted(ids, key=lambda s: (meta[s]["nearby_stops_840m_geometric_proxy"], s))
    quarter = max(1, len(ids) // 4)
    clusters = []
    for stratum, count in allocation(n).items():
        for j in range(count):
            for attempt in range(100000):
                desired_band = None
                subtype = ""
                if stratum == "spatial_balanced":
                    origin = rng.pick(spatial[rng.pick(cells)])
                    destination = rng.pick(spatial[rng.pick(cells)])
                    desired_band = j % 3
                    subtype = ["under_3km", "3_to_10km", "over_10km"][desired_band]
                elif stratum == "uniform_parent_od":
                    origin, destination = rng.pick(groups[rng.pick(gids)]), rng.pick(groups[rng.pick(gids)])
                elif stratum == "network_structure":
                    subtype = ["low_to_high_degree", "high_to_low_degree", "low_to_low_degree", "high_to_high_degree"][j % 4]
                    a = degree[:quarter] if j % 4 in (0, 2) else degree[-quarter:]
                    b = degree[-quarter:] if j % 4 in (0, 3) else degree[:quarter]
                    origin, destination = rng.pick(a), rng.pick(b)
                elif stratum == "nearby_stop_density_proxy":
                    subtype = "sparse_to_dense" if j % 2 == 0 else "dense_to_sparse"
                    a, b = (density[:quarter], density[-quarter:]) if j % 2 == 0 else (density[-quarter:], density[:quarter])
                    origin, destination = rng.pick(a), rng.pick(b)
                else:
                    origin, destination = rng.pick(ids), rng.pick(ids)
                    subtype = "departure_first_two_hours_binned"
                key = pair_key(meta, origin, destination)
                if key[0] == key[1] or key in used:
                    continue
                a, b = meta[origin], meta[destination]
                dist = distance_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
                band = 0 if dist < 3000 else 1 if dist <= 10000 else 2
                if desired_band is not None and band != desired_band:
                    continue
                break
            else:
                raise ValueError(f"exhausted metadata pair sampling for {stage}/{stratum}; no fallback")
            used.add(key)
            cluster_id = f"{stage}-{digest(canonical(list(key)))[:16]}"
            offsets = {}
            for w in windows:
                width = w["departures_end_exclusive"] - w["departures_start"]
                if width < departures or w["departures_end_exclusive"] - 1 + 3600 > w["end"]:
                    raise ValueError("window cannot support fixed one-hour horizon")
                drng = HashRNG(f"departures|{cluster_id}|{w['id']}")
                offsets[w["id"]] = [i * width // departures + drng.below((i + 1) * width // departures - i * width // departures) for i in range(departures)]
            clusters.append({"cluster_id": cluster_id, "stage": stage, "origin": origin,
                "destination": destination, "unordered_parent_pair": list(key),
                "construction_stratum": stratum, "construction_subtype": subtype,
                "straight_line_distance_m": round(dist, 3), "distance_band": ["under_3km", "3_to_10km", "over_10km"][band],
                "origin_modes": a["route_types"], "destination_modes": b["route_types"],
                "origin_geometric_nearby_count": a["nearby_stops_840m_geometric_proxy"],
                "destination_geometric_nearby_count": b["nearby_stops_840m_geometric_proxy"],
                "departure_offsets": offsets})
    # Split by full unordered parent OD cluster. These strata are model coverage,
    # not demand weighting; small stages may have random stratum imbalance.
    ordered = sorted(clusters, key=lambda c: digest(f"split|{SEED}|{c['cluster_id']}".encode()))
    ntune, nvalidation = (n, 0) if stage == "smoke" else (n // 2, n // 4)
    for i, c in enumerate(ordered):
        c["split"] = "tune" if i < ntune else "validation" if i < ntune + nvalidation else "test"
    return sorted(clusters, key=lambda c: c["cluster_id"])


def plan(args):
    if args.smoke_clusters < 4 or args.screen_clusters < 4 or args.full_clusters < 4 or args.final_clusters < 0 or args.departures < 1:
        raise ValueError("each stage needs >=4 clusters and >=1 departure")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    windows_source = read_json(args.window_plan)
    windows = windows_source["windows"]
    if len({w["id"] for w in windows}) != len(windows):
        raise ValueError("duplicate window ID")
    meta, groups, spatial = metadata_from_gtfs(args.gtfs_zip)
    metadata_hash = write_new(out / "stop-metadata.json", {"schema": "sg-stop-metadata-v1", "stops": [meta[s] for s in sorted(meta)],
        "limits": ["Coordinates and raw route topology are model metadata, not street paths.",
                   "840m density is geometric only, not eligible walking access or observed demand."]})
    used = set()
    stages = [("smoke", args.smoke_clusters), ("screen", args.screen_clusters), ("full", args.full_clusters)]
    if args.final_clusters:
        stages.append(("optional_holdout", args.final_clusters))
    clusters = []
    for stage, count in stages:
        clusters += build_clusters(stage, count, meta, groups, spatial, used, windows, 1 if stage == "smoke" else args.departures)
    counts = Counter((c["stage"], c["split"], c["construction_stratum"]) for c in clusters)
    obj = {"schema": SCHEMA, "seed": SEED, "protocol_version": "v2",
        "amendment": {"supersedes_plan_sha256": "2b2e1f825a08749a9a6d02986f6fba47fdd02279f14f5aec08e5c4107967a3d6",
            "reason": "Pre-tuning protocol correction: v1 arbitrary total2400 can bind despite user ten-minute per-block limit. Primary total3000 permits max4 boardings' at most5 walking blocks of600; role caps remain600. Keep2400 as separate binding-budget challenge. Preserve v1 smoke unsupported outcomes, not a speedup or constraint-relaxation optimization claim.",
            "endpoint_departure_split_policy": "unchanged SHA256 metadata sampling; no response-conditioned resampling"},
        "generator": "SHA256 counter stream with unbiased rejection; sorted metadata; no router outputs read",
        "generator_sha256": digest(Path(__file__).read_bytes()), "raw_gtfs_sha256": digest(Path(args.gtfs_zip).read_bytes()),
        "window_plan_sha256": digest(Path(args.window_plan).read_bytes()), "stop_metadata_sha256": metadata_hash,
        "parameters": {"smoke_clusters": args.smoke_clusters, "screen_clusters": args.screen_clusters, "full_clusters": args.full_clusters, "optional_holdout_clusters": args.final_clusters,
            "stages": [name for name, _ in stages], "smoke_departures_per_cluster_per_window": 1,
            "departures_per_cluster_per_window": args.departures, "max_boardings": 4, "max_legs": 1024,
            "transfer_buffer": 0, "ranking_transfer_penalty_seconds": 300, "display_primary_k": 3, "display_secondary_k": 5},
        "profiles": PROFILES, "windows": windows, "clusters": clusters,
        "strata_allocation_percent": dict(STRATA),
        "strata_split_counts": [{"stage": k[0], "split": k[1], "stratum": k[2], "clusters": v} for k, v in sorted(counts.items())],
        "leakage_policy": {"unit": "unordered parent-station OD pair; every departure/window/sensitivity stays together",
            "stage_overlap": "all stages parent OD clusters disjoint, including reversed pairs; smoke is train-only and non-evaluative",
            "holdout": "test outcomes must remain unavailable to optimizer until sources/configs frozen; query inputs alone are not labels",
            "limitations": "Transit infrastructure/corridor overlap remains; no wholly disjoint-network claim."},
        "scope": "stop-to-stop finite-model coverage; not empirical demand or true multi-origin passenger requests",
        "horizon_policy": "primary exactly3600 seconds after departure; sensitivity exactly7200 only where fully loaded; no clipping",
        "limitations": ["Source is deterministic frequency model, not exact timetable or real-world service.",
            "Weekend source may be service-empty: retain as source coverage limitation, not real-world unreachable.",
            "Strict known-edge pilot and OSM-enriched graph have distinct dataset bindings; do not mix outcomes.",
            "A no-result with finite horizon does not prove real-world unreachability."]}
    sha = write_new(out / "planned-workload.json", obj)
    commitment = {"schema": "sg-workload-commitment-v1", "planned_workload_sha256": sha,
        "stop_metadata_sha256": metadata_hash, "generator_sha256": obj["generator_sha256"],
        "source_hashes": {"raw_gtfs": obj["raw_gtfs_sha256"], "window_plan": obj["window_plan_sha256"]},
        "selected_without_routing_outcomes": True, "planned_main_records_per_stage": {stage: count * len(windows) * (1 if stage == "smoke" else args.departures) for stage, count in stages}}
    write_new(out / "HASH_COMMITMENT.json", commitment)
    print(json.dumps(commitment, sort_keys=True))


def query_record(plan_obj, cluster, window, profile_name, departure_index):
    profile = plan_obj["profiles"][profile_name]
    departure = window["departures_start"] + cluster["departure_offsets"][window["id"]][departure_index]
    arrival = departure + profile["horizon_seconds"]
    if arrival > window["end"]:
        return None
    qid = f"{cluster['cluster_id']}|{window['id']}|d{departure_index}|{profile_name}"
    q = {"id": qid, "origin": cluster["origin"], "destination": cluster["destination"],
        "departure": departure, "latest_arrival": arrival, "transfer_buffer": 0,
        "max_walk_seconds": profile["max_walk_seconds"], "max_boardings": 4,
        "max_legs": 1024, "accessible_only": False, "walking_limits": profile["walking_limits"]}
    return {"stratum": cluster["construction_stratum"], "query": q}


def bind(args):
    path = Path(args.plan)
    plan_obj = read_json(path)
    if plan_obj["schema"] != SCHEMA:
        raise ValueError("unsupported plan schema")
    commit_path = path.parent / "HASH_COMMITMENT.json"
    if not commit_path.exists() or read_json(commit_path)["planned_workload_sha256"] != digest(path.read_bytes()):
        raise ValueError("missing/mismatching hash commitment")
    bindings = read_json(args.datasets)
    if "datasets" in bindings:
        bindings = bindings["datasets"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    records, skips, files, missing = [], [], [], []
    for window in plan_obj["windows"]:
        dataset_path = bindings.get(window["id"])
        if not dataset_path:
            missing.append({"window": window["id"], "status": "not_bound_input_unavailable"})
            continue
        dataset_path = Path(dataset_path)
        data = dataset_path.read_bytes()
        dataset = json.loads(data)
        if not dataset.get("connections"):
            missing.append({"window": window["id"], "status": "unsupported_input_profile_no_service_connections",
                "reason": "Source service calendar has no loaded service; not a valid-empty route success", "dataset_sha256": digest(data)})
            continue
        if dataset["service_date"] != window["service_date"] or dataset["time_zone"] != "Asia/Singapore":
            raise ValueError(f"date/timezone mismatch: {window['id']}")
        if dataset["window"] != {"start": window["start"], "end": window["end"]}:
            raise ValueError(f"window mismatch: {window['id']}")
        stop_ids = {s["id"] for s in dataset["stops"]}
        dhash = digest(data)
        for stage in plan_obj["parameters"]["stages"]:
            for split in ("tune", "validation", "test"):
                clusters = [c for c in plan_obj["clusters"] if c["stage"] == stage and c["split"] == split]
                for profile in plan_obj["profiles"]:
                    items = []
                    for c in clusters:
                        if c["origin"] not in stop_ids or c["destination"] not in stop_ids:
                            raise ValueError(f"planned endpoint missing in bound input: {c['cluster_id']}")
                        for i in range(1 if stage == "smoke" else plan_obj["parameters"]["departures_per_cluster_per_window"]):
                            record = query_record(plan_obj, c, window, profile, i)
                            if record is None:
                                skips.append({"cluster_id": c["cluster_id"], "stage": stage, "split": split,
                                    "window": window["id"], "profile": profile, "departure_index": i,
                                    "status": "not_applicable_horizon_not_fully_loaded"})
                                continue
                            items.append(record)
                            records.append({"query_id": record["query"]["id"], "cluster_id": c["cluster_id"],
                                "split": split, "stage": stage, "window": window["id"], "profile": profile,
                                "stratum": c["construction_stratum"], "subtype": c["construction_subtype"],
                                "distance_band": c["distance_band"], "dataset_sha256": dhash})
                    if not items:
                        continue
                    filename = f"{window['id']}.{stage}.{split}.{profile}.json"
                    obj = {"seed": plan_obj["seed"], "method": "metadata-only precommitted stop-stop workload; see split-sidecar.json; no demand/physical walking claim",
                           "dataset_sha256": dhash, "items": items}
                    fhash = write_new(out / filename, obj)
                    query_meta = {"schema_version": "sg-coldstart-evalkit-v1", "dataset_sha256": dhash,
                        "queries_sha256": fhash, "items": []}
                    by_id = {c["cluster_id"]: c for c in clusters}
                    for record in items:
                        cid = record["query"]["id"].split("|", 1)[0]
                        c = by_id[cid]
                        query_meta["items"].append({"query_id": record["query"]["id"], "od_cluster": cid,
                            "split": split, "workload_cohort": "model_coverage",
                            "labels": [stage, window["id"], profile, c["construction_stratum"], c["distance_band"],
                                "non_evaluative_smoke" if stage == "smoke" else "precommitted_model_coverage"]})
                    mh = write_new(out / (filename.removesuffix(".json") + ".metadata.json"), query_meta)
                    files.append({"path": filename, "sha256": fhash, "window": window["id"], "stage": stage,
                        "split": split, "profile": profile, "queries": len(items), "dataset_sha256": dhash, "query_metadata_sha256": mh})
    sidehash = write_new(out / "split-sidecar.json", {"schema": "sg-workload-split-sidecar-v1",
        "plan_sha256": digest(path.read_bytes()), "records": records, "not_applicable": skips,
        "unavailable_windows": missing})
    result = {"schema": "sg-bound-workload-manifest-v1", "plan_sha256": digest(path.read_bytes()),
        "split_sidecar_sha256": sidehash, "binding_generator_sha256": digest(Path(__file__).read_bytes()), "files": files, "unavailable_windows": missing,
        "queries_bound": len(records), "sensitivity_not_applicable": len(skips),
        "note": "No routing was executed; test query inputs are not outcomes. All missing windows remain explicit."}
    write_new(out / "bound-manifest.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("plan", help="freeze endpoint clusters and queries using only raw metadata")
    p.add_argument("--gtfs-zip", required=True)
    p.add_argument("--window-plan", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--smoke-clusters", type=int, default=12)
    p.add_argument("--screen-clusters", type=int, default=120)
    p.add_argument("--full-clusters", type=int, default=600)
    p.add_argument("--final-clusters", type=int, default=0, help="optional additional untouched holdout-stage clusters; default disabled")
    p.add_argument("--departures", type=int, default=3)
    p.set_defaults(func=plan)
    p = subs.add_parser("bind", help="bind a frozen plan to exact normalized dataset hashes; no resampling")
    p.add_argument("--plan", required=True)
    p.add_argument("--datasets", required=True, help="JSON mapping window ID to normalized dataset path")
    p.add_argument("--out", required=True)
    p.set_defaults(func=bind)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as e:
        print(f"workload error: {e}", file=sys.stderr)
        raise SystemExit(1)
