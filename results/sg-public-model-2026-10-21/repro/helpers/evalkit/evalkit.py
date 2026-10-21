#!/usr/bin/env python3
"""Source-bound static-timetable quality scorecards. Python 3.10+, stdlib only."""
from __future__ import annotations
import argparse
import collections
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import sys
from datetime import date
from zoneinfo import ZoneInfo

VERSION = "sg-coldstart-evalkit-v1"
MAX_SECOND = 7 * 86400
STAGES = ("raw", "candidates", "displayed", "displayed_secondary")
METRICS = ("arrival", "boardings", "transfers", "walking_seconds", "leg_count",
           "access_walking_seconds", "transfer_walking_seconds", "egress_walking_seconds", "direct_walking_seconds")
DEFAULT_CONFIG = {
    "schema_version": VERSION,
    "display": {"source": "display_options", "k": 3, "transfer_penalty_seconds": 300},
    "secondary_display_k": 5,
    "profiles": [{"id": f"t{t}_w{w}", "transfer_seconds": t, "extra_walk_weight": w}
                 for t in (0, 150, 300, 600, 900) for w in (0, 1, 2, 4)],
    "coverage_tolerance_seconds": 0,
    "alternative_epsilon_seconds": 300,
    "bootstrap": {"seed": 20261020, "replicates": 2000, "confidence": 0.95},
}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def integer(value, name, low=0, high=None):
    require(isinstance(value, int) and not isinstance(value, bool), f"{name}: integer required")
    require(value >= low and (high is None or value <= high), f"{name}: out of range")
    return value


def dumps(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def read_json(path):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, f"{path}: duplicate JSON key {k}")
            out[k] = v
        return out
    raw = Path(path).read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValidationError(f"nonfinite JSON: {x}")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError(f"{path}: {exc}") from exc
    return value, hashlib.sha256(raw).hexdigest()


def distribution(values):
    xs = sorted(values)
    n = len(xs)
    return {"count": n, "mean": statistics.fmean(xs) if n else None,
            "p50": xs[math.ceil(n * .50) - 1] if n else None,
            "p90": xs[math.ceil(n * .90) - 1] if n else None,
            "p95": xs[math.ceil(n * .95) - 1] if n else None,
            "p99": xs[math.ceil(n * .99) - 1] if n else None,
            "max": xs[-1] if n else None,
            "quantiles": "empirical nearest rank; not population tail or SLA"}


def validate_config(cfg):
    require(cfg.get("schema_version") == VERSION, "config schema_version mismatch")
    profiles = cfg.get("profiles")
    require(isinstance(profiles, list) and 1 <= len(profiles) <= 128, "1..128 finite profiles required")
    seen = set()
    for p in profiles:
        require(isinstance(p.get("id"), str) and p["id"] and p["id"] not in seen, "unique profile id required")
        seen.add(p["id"])
        integer(p.get("transfer_seconds"), "transfer_seconds", high=MAX_SECOND)
        integer(p.get("extra_walk_weight"), "extra_walk_weight", high=1000)
    integer(cfg.get("secondary_display_k"), "secondary_display_k", low=1)
    display = cfg["display"]
    require(display.get("source") in ("display_options", "finite_preferences", "pattern_anchors"), "unsupported display source")
    integer(display.get("k"), "display k", low=1)
    if display["source"] == "display_options":
        integer(display.get("transfer_penalty_seconds"), "display transfer_penalty_seconds", high=MAX_SECOND)
    if display["source"] == "finite_preferences":
        require(display.get("group") and display.get("method"), "finite_preferences needs group and method")
    if display["source"] == "pattern_anchors":
        integer(display.get("envelope_seconds"), "envelope_seconds")
    integer(cfg.get("coverage_tolerance_seconds"), "coverage_tolerance_seconds")
    integer(cfg.get("alternative_epsilon_seconds"), "alternative_epsilon_seconds")
    boot = cfg["bootstrap"]
    integer(boot.get("seed"), "bootstrap seed")
    integer(boot.get("replicates"), "bootstrap replicates", low=1, high=100000)
    require(isinstance(boot.get("confidence"), (float, int)) and 0 < boot["confidence"] < 1, "bootstrap confidence in (0,1)")
    return cfg


class Checker:
    """Reconstructs static model 0.1/0.2 witnesses without importing router code.

    Independent implementation, but deliberately shares the declared model, so
    this is no assertion of independent source truth or search completeness.
    """
    def __init__(self, dataset):
        self.d = dataset
        require(dataset.get("schema_version") in ("0.1", "0.2"), "unsupported dataset schema")
        require(dataset.get("id"), "dataset id required")
        ZoneInfo(dataset["time_zone"])
        require(dataset["time_zone"] != "Local", "explicit timezone required")
        require(date.fromisoformat(dataset["service_date"]).isoformat() == dataset["service_date"], "strict ISO service_date required")
        self.stops = self.index("stops")
        self.trips = self.index("trips")
        self.rides = self.index("connections")
        self.walks = self.index("footpaths")
        require(self.stops, "empty stops")
        for stop in self.stops.values():
            require(stop.get("accessible") in ("yes", "no", "unknown"), "invalid stop accessibility")
            integer(stop.get("location_type", 0), "location_type", high=4)
            require(not stop.get("parent_station") or stop["parent_station"] in self.stops, "unknown parent station")
        for trip in self.trips.values():
            require(trip.get("accessible") in ("yes", "no", "unknown"), "invalid trip accessibility")
        chains = collections.defaultdict(list)
        for ride in self.rides.values():
            self.endpoints(ride)
            require(ride["trip_id"] in self.trips, "unknown ride trip")
            integer(ride["sequence"], "sequence")
            integer(ride["departure"], "departure", high=MAX_SECOND)
            integer(ride["arrival"], "arrival", low=ride["departure"], high=MAX_SECOND)
            require(type(ride.get("pickup")) is bool and type(ride.get("dropoff")) is bool, "pickup/dropoff booleans required")
            chains[ride["trip_id"]].append(ride)
        for rides in chains.values():
            rides.sort(key=lambda r: r["sequence"])
            for i, r in enumerate(rides):
                require(r["sequence"] == i, "noncontiguous trip sequence")
                require(not i or (rides[i-1]["to"] == r["from"] and rides[i-1]["arrival"] <= r["departure"]), "discontinuous trip events")
        for walk in self.walks.values():
            self.endpoints(walk)
            integer(walk["duration"], "walk duration", low=1, high=MAX_SECOND)
            require(walk.get("accessible") in ("yes", "no", "unknown"), "invalid walk accessibility")
        self.rules = dataset.get("transfers", [])
        rule_ids, selectors = set(), set()
        sources = {}
        for trip in self.trips.values():
            source_id = trip.get("source_id") or trip["id"]
            require(source_id not in sources or sources[source_id].get("route_id", "") == trip.get("route_id", ""), "source trip inconsistent route")
            sources[source_id] = trip
        routes = {t.get("route_id", "") for t in self.trips.values()}
        for r in self.rules:
            require(r.get("id") and r["id"] not in rule_ids, "duplicate/empty transfer id")
            rule_ids.add(r["id"])
            require(r["from_stop"] in self.stops and r["to_stop"] in self.stops, "unknown transfer stop")
            require(r.get("type") in (0, 2, 3), "unsupported transfer type")
            integer(r.get("min_seconds", 0), "min_seconds", high=MAX_SECOND)
            require(r["type"] == 2 or r.get("min_seconds", 0) == 0, "unexpected transfer minimum")
            key = tuple(r.get(k, "") for k in ("from_stop", "to_stop", "from_trip", "to_trip", "from_route", "to_route"))
            require(key not in selectors, "duplicate transfer selector")
            selectors.add(key)
            for side in ("from", "to"):
                tid, route = r.get(side + "_trip", ""), r.get(side + "_route", "")
                require(not tid or tid in sources, "unknown source trip selector")
                require(not route or route in routes, "unknown route selector")
                require(not tid or not route or sources[tid].get("route_id", "") == route, "inconsistent trip/route selector")
        if dataset.get("window"):
            integer(dataset["window"]["start"], "window start", high=MAX_SECOND)
            integer(dataset["window"]["end"], "window end", low=dataset["window"]["start"], high=MAX_SECOND)

    def index(self, table):
        rows = self.d.get(table, [])
        require(isinstance(rows, list), f"{table}: array required")
        out = {}
        for row in rows:
            require(isinstance(row.get("id"), str) and row["id"] and row["id"] not in out, f"duplicate/empty {table} id")
            out[row["id"]] = row
        return out

    def endpoints(self, obj):
        require(obj["from"] in self.stops and obj["to"] in self.stops, "unknown edge endpoint")

    def query(self, q):
        require(q.get("id") and q.get("origin") in self.stops and q.get("destination") in self.stops, "invalid query id/endpoints")
        for key in ("departure", "transfer_buffer", "max_walk_seconds"):
            integer(q[key], key, high=MAX_SECOND)
        integer(q["latest_arrival"], "latest_arrival", low=q["departure"], high=MAX_SECOND)
        integer(q["max_legs"], "max_legs", high=1024)
        integer(q["max_boardings"], "max_boardings", high=q["max_legs"])
        require(type(q["accessible_only"]) is bool, "accessible_only boolean required")
        if q.get("walking_limits"):
            for key in ("access_seconds", "egress_seconds", "transfer_seconds", "direct_seconds"):
                integer(q["walking_limits"][key], key, high=MAX_SECOND)
        if self.d.get("window"):
            require(q["departure"] >= self.d["window"]["start"] and q["latest_arrival"] <= self.d["window"]["end"], "query outside dataset window")

    def transfer(self, incoming, outgoing, fallback):
        a, b = self.trips[incoming["trip_id"]], self.trips[outgoing["trip_id"]]
        candidates = []
        def stop_match(selector, actual):
            return selector == actual or (self.stops[selector].get("location_type", 0) == 1 and self.stops[actual].get("parent_station") == selector)
        for r in self.rules:
            if not stop_match(r["from_stop"], incoming["to"]) or not stop_match(r["to_stop"], outgoing["from"]):
                continue
            priority = 0
            for side, trip in (("from", a), ("to", b)):
                tid, route = r.get(side+"_trip"), r.get(side+"_route")
                if tid and tid != (trip.get("source_id") or trip["id"]):
                    break
                if route and route != trip.get("route_id", ""):
                    break
                priority += 3 if tid else 1 if route else 0
            else:
                candidates.append((priority, r))
        if not candidates:
            return True, fallback
        top = max(p for p, _ in candidates)
        winners = [r for p, r in candidates if p == top]
        require(len(winners) == 1, "ambiguous maximum-specificity transfer rules")
        winner = winners[0]
        return winner["type"] != 3, winner.get("min_seconds", 0) if winner["type"] == 2 else 0

    def check(self, q, obj):
        claim = obj if "journey" in obj else None
        j = obj["journey"] if claim else obj
        legs = j["legs"]
        require(isinstance(legs, list) and len(legs) <= q["max_legs"], "leg budget/array")
        accessible = lambda stop: not q["accessible_only"] or self.stops[stop]["accessible"] == "yes"
        require(accessible(q["origin"]) and accessible(q["destination"]), "endpoint accessibility unknown/prohibited")
        at, now, boardings, walk_total, block = q["origin"], q["departure"], 0, 0, 0
        prev = last_ride = None
        last_alight = 0
        m = {key: 0 for key in METRICS}
        m["leg_count"] = len(legs)
        tokens, pattern = [], []
        for i, leg in enumerate(legs):
            can_alight = prev is None or (prev["dropoff"] and accessible(prev["to"]))
            require(not (at == q["destination"] and can_alight), f"leg {i} leaves absorbing destination")
            dep, arr = leg["departure"], leg["arrival"]
            integer(dep, "leg departure", low=now, high=MAX_SECOND)
            integer(arr, "leg arrival", low=dep, high=q["latest_arrival"])
            tokens.append({"kind": leg["kind"], "ref": leg["ref"]})
            if leg["kind"] == "ride":
                require(leg["ref"] in self.rides, "unknown connection")
                r = self.rides[leg["ref"]]
                require(r["from"] == at and dep == r["departure"] and arr == r["arrival"], "connection direction/times mismatch")
                staying = prev is not None and prev["trip_id"] == r["trip_id"] and r["sequence"] == prev["sequence"]+1
                if not staying:
                    require(can_alight, "cannot alight previous vehicle")
                    if prev:
                        last_alight = prev["arrival"]
                    require(r["pickup"] and accessible(r["from"]), "boarding prohibited")
                    require(not q["accessible_only"] or self.trips[r["trip_id"]]["accessible"] == "yes", "trip accessibility unknown/prohibited")
                    if q.get("walking_limits"):
                        cap = q["walking_limits"]["access_seconds" if boardings == 0 else "transfer_seconds"]
                        require(block <= cap, "access/transfer walking block budget")
                    if boardings:
                        allow, minimum = self.transfer(last_ride, r, q["transfer_buffer"])
                        require(allow and dep >= last_alight+minimum, "transfer rule/minimum violated")
                        m["transfer_walking_seconds"] += block
                    else:
                        m["access_walking_seconds"] = block
                    boardings += 1
                    trip = self.trips[r["trip_id"]]
                    pattern.append({"kind": "ride", "route": trip.get("route_id") or "trip:"+trip["id"],
                                    "missing_route": not bool(trip.get("route_id")), "stops": [r["from"], r["to"]]})
                else:
                    pattern[-1]["stops"].append(r["to"])
                at, now, prev, last_ride, block = r["to"], arr, r, r, 0
            elif leg["kind"] == "walk":
                require(leg["ref"] in self.walks, "unknown footpath")
                w = self.walks[leg["ref"]]
                require(can_alight, "cannot alight before walking")
                if prev:
                    last_alight = prev["arrival"]
                require(w["from"] == at and dep == now and arr == now+w["duration"], "walking direction/times mismatch")
                require(accessible(w["from"]) and accessible(w["to"]) and (not q["accessible_only"] or w["accessible"] == "yes"), "walking accessibility unknown/prohibited")
                walk_total += w["duration"]
                block += w["duration"]
                at, now, prev = w["to"], arr, None
                pattern.append({"kind": "walk", "footpath": w["id"]})
            else:
                raise ValidationError("unknown leg kind")
            require(boardings <= q["max_boardings"] and walk_total <= q["max_walk_seconds"], "boarding/walking resource budget")
        require(at == q["destination"] and (prev is None or (prev["dropoff"] and accessible(prev["to"]))), "ineligible terminal destination")
        role = "direct" if not boardings else "egress"
        if q.get("walking_limits"):
            require(block <= q["walking_limits"][role+"_seconds"], f"{role} walking budget")
        m[role+"_walking_seconds"] = block
        m.update(arrival=now, boardings=boardings, transfers=max(0, boardings-1), walking_seconds=walk_total)
        # Identity equality is parsed semantically: Go's HTML escaping does not alter JSON identity.
        identity = json.dumps(tokens, separators=(",", ":"), ensure_ascii=False)
        if claim:
            try:
                require(json.loads(claim["identity"]) == tokens, "claimed identity mismatch")
            except (KeyError, ValueError, TypeError) as exc:
                raise ValidationError("malformed claimed identity") from exc
            require(claim.get("metrics") == m, "claimed metrics mismatch")
        return {"identity": identity, "pattern": dumps(pattern), "metrics": m,
                "duration_seconds": now-q["departure"], "journey": j}


def score(j, p):
    m = j["metrics"]
    return j["duration_seconds"] + p["transfer_seconds"]*m["transfers"] + p["extra_walk_weight"]*m["walking_seconds"]


def vector(j):
    return (j["duration_seconds"], j["metrics"]["transfers"], j["metrics"]["walking_seconds"])


def dominates(a, b):
    va, vb = vector(a), vector(b)
    return va != vb and all(x <= y for x, y in zip(va, vb))


def unique_journeys(js):
    out = {}
    for j in js:
        prior = out.get(j["identity"])
        require(prior is None or prior == j, "identity has inconsistent reconstruction")
        out[j["identity"]] = j
    return list(out.values())


def legitimate_alternatives(pool, profiles, epsilon):
    """Operational definition: nondominated AND epsilon-near-optimal for >=1 profile.

    This is a finite synthetic-score opportunity set, not preference ground truth.
    Equal vectors with distinct route/stop/walk patterns remain legitimate.
    """
    if not pool:
        return []
    best = {p["id"]: min(score(j, p) for j in pool) for p in profiles}
    return [j for j in pool if not any(dominates(o, j) for o in pool)
            and any(score(j, p) <= best[p["id"]]+epsilon for p in profiles)]


def go_identity_string(identity):
    # Go encoding/json escapes HTML metacharacters and U+2028/U+2029 by default.
    value = json.dumps([{"kind": t["kind"], "ref": t["ref"]} for t in json.loads(identity)], ensure_ascii=False, separators=(",", ":"))
    for char, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"), ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        value = value.replace(char, escaped)
    return value


def presentation_key(claim, departure, penalty):
    m = claim["metrics"]
    return (m["arrival"]-departure+penalty*m["transfers"], m["arrival"], m["transfers"],
            m["walking_seconds"], m["leg_count"], go_identity_string(claim["identity"]))


def display_objects(row, cfg, secondary=False):
    d = dict(cfg["display"])
    if secondary:
        d["k"] = cfg["secondary_display_k"]
    if d["source"] == "display_options":
        options = row.get("display_options", {}).get(str(d["k"]))
        require(options is not None, "requested display k absent")
        require(options.get("k") == d["k"], "display k metadata mismatch")
        require(options.get("candidate_count") == len(row.get("final", [])), "display candidate_count mismatch")
        penalty = integer(options.get("ranking_transfer_penalty_seconds"), "display transfer penalty", high=MAX_SECOND)
        require(penalty == d["transfer_penalty_seconds"], "display transfer penalty differs from frozen common policy")
        require(type(options.get("global_optimality_claim")) is bool, "display global claim boolean required")
        if options["global_optimality_claim"]:
            cert = row.get("certificates", {})
            require(row.get("completed") and cert.get("score_top_k") and cert.get("score_certified_through_k", 0) >= d["k"], "display global claim exceeds source score-top-k certificate")
        observed = []
        departure = row["query"]["departure"]
        for o in options.get("options", []):
            j, m = o["journey"], o["journey"]["metrics"]
            duration, cost = m["arrival"]-departure, penalty*m["transfers"]
            require(o.get("actual_duration_seconds") == duration and o.get("transfer_penalty_cost_seconds") == cost and o.get("generalized_score_seconds") == duration+cost, "display score metadata mismatch")
            observed.append(j)
        expected = sorted(row.get("final", []), key=lambda j: presentation_key(j, departure, penalty))[:d["k"]]
        require([go_identity_string(j["identity"]) for j in observed] == [go_identity_string(j["identity"]) for j in expected], "display is not declared deterministic pool ranking")
        return observed
    quality = row.get("recommendation_quality") or {}
    selected = None
    if d["source"] == "finite_preferences":
        choices = quality.get("choices") or {}
        require(choices.get("complete") is True, "finite-preference selection incomplete/absent")
        for g in choices.get("groups", []):
            if g.get("group", {}).get("name") == d["group"]:
                for s in g.get("selections", []):
                    if s.get("method") == d["method"] and s.get("limit") == d["k"]:
                        require(s.get("complete") is True, "selection incomplete")
                        selected = s["selected"]
    else:
        for s in quality.get("selections", []):
            if s.get("limit") == d["k"] and s.get("score_envelope_seconds") == d["envelope_seconds"]:
                selected = s["selected"]
    require(selected is not None, "requested recommendation selection absent")
    by_id = {dumps(json.loads(o["identity"])): o for o in row.get("final", [])}
    out = []
    for identity in selected:
        key = dumps(json.loads(identity))
        require(key in by_id, "selected identity absent from candidate pool")
        out.append(by_id[key])
    return out


def reconstruct_record(row, checker, expected, cfg):
    q = row.get("query", {})
    require(q.get("id") in expected, "unknown query id")
    require(q == expected[q["id"]]["query"], "query differs from frozen workload")
    require(row.get("stratum") == expected[q["id"]].get("stratum"), "stratum differs from frozen workload")
    errors, stages, duplicate_counts, slot_counts = [], {}, {}, {}
    for key in ("attempted", "completed", "valid_empty", "transit"):
        require(type(row.get(key)) is bool, f"{key} boolean required")
    require(isinstance(row.get("status"), str), "status required")
    if row["completed"]:
        require(row["attempted"] and row["status"] == "complete", "inconsistent complete status")
    certificates = row.get("certificates", {})
    require(isinstance(certificates, dict), "certificates object required")
    for field in ("earliest_arrival", "arrival_boardings", "arrival_boardings_walking", "best_score", "arrival_top_k", "score_top_k"):
        if field in certificates:
            require(type(certificates[field]) is bool, f"certificate {field} boolean required")
    for field in ("arrival_certified_through_k", "score_certified_through_k"):
        if field in certificates:
            integer(certificates[field], "certificate "+field)
    if certificates.get("arrival_boardings_walking") and not certificates.get("arrival_boardings"):
        errors.append({"stage": "certificates", "error": "3D completeness lacks declared 2D projection"})
    for name, count in (("arrival_top_k", "arrival_certified_through_k"), ("score_top_k", "score_certified_through_k")):
        if certificates.get(name) and certificates.get(count, 0) < 1:
            errors.append({"stage": "certificates", "error": name+" lacks positive certified-through-k"})
    if not row["completed"] and any(v is True or (isinstance(v, int) and not isinstance(v, bool) and v > 0) for v in certificates.values()):
        errors.append({"stage": "certificates", "error": "incomplete request carries positive completeness certificate"})
    for stage in STAGES:
        slot_counts[stage] = 0
        if stage.startswith("displayed") and cfg["display"]["source"] == "display_options":
            k = cfg["secondary_display_k"] if stage == "displayed_secondary" else cfg["display"]["k"]
            slots = row.get("display_options", {}).get(str(k), {}).get("options", [])
            if isinstance(slots, list):
                slot_counts[stage] = len(slots)
        try:
            objects = row.get("raw", []) if stage == "raw" else row.get("final", []) if stage == "candidates" else display_objects(row, cfg, secondary=stage == "displayed_secondary")
            require(isinstance(objects, list), stage+" must be array")
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            # Missing display is normal on failed requests, not an invalid itinerary.
            if row["completed"]:
                errors.append({"stage": stage, "error": str(exc)})
            stages[stage], duplicate_counts[stage] = [], 0
            continue
        slot_counts[stage] = len(objects)
        valid = []
        for index, obj in enumerate(objects):
            try:
                valid.append(checker.check(q, obj))
            except (ValidationError, KeyError, TypeError, ValueError) as exc:
                errors.append({"stage": stage, "index": index, "error": str(exc)})
        stages[stage] = unique_journeys(valid)
        duplicate_counts[stage] = len(valid)-len(stages[stage])
        if duplicate_counts[stage] and stage != "raw":
            errors.append({"stage": stage, "error": "duplicate validated/displayed identity; cannot pad alternatives"})
    candidate_ids = {j["identity"] for j in stages["candidates"]}
    if any(j["identity"] not in candidate_ids for j in stages["displayed"]):
        errors.append({"stage": "displayed", "error": "display witness absent from final candidates"})
    for stage, k in (("displayed", cfg["display"]["k"]), ("displayed_secondary", cfg["secondary_display_k"])):
        if any(j["identity"] not in candidate_ids for j in stages[stage]):
            errors.append({"stage": stage, "error": "display witness absent from final candidates"})
        if slot_counts[stage] > k:
            errors.append({"stage": stage, "error": "display exceeds requested k"})
    if row["valid_empty"] != (row["completed"] and len(stages["candidates"]) == 0):
        errors.append({"stage": "outcome", "error": "valid_empty flag mismatch"})
    if row["transit"] != (row["completed"] and any(j["metrics"]["boardings"] for j in stages["candidates"])):
        errors.append({"stage": "outcome", "error": "transit flag mismatch"})
    for timing in ("response_ns", "quality_ns", "validation_rank_ns"):
        require(timing in row, timing+" required in familybench row")
        integer(row[timing], timing)
    if row.get("core_ns") is not None:
        integer(row["core_ns"], "core_ns")
    response, validation, quality = row.get("response_ns", 0), row.get("validation_rank_ns", 0), row.get("quality_ns", 0)
    if not quality <= validation <= response:
        errors.append({"stage": "timing", "error": "quality_ns <= validation_rank_ns <= response_ns violated"})
    if row.get("core_ns") is not None and row["core_ns"]+validation > response:
        errors.append({"stage": "timing", "error": "individual core_ns + validation_rank_ns exceeds response_ns"})
    offset_keys = ("service_start_offset_ns", "search_done_offset_ns", "validation_start_offset_ns")
    if any(key in row for key in offset_keys):
        require(all(key in row for key in offset_keys), "partial timing offset metadata")
        offsets = [integer(row[key], key) for key in offset_keys]
        if offsets != sorted(offsets) or offsets[-1] > response:
            errors.append({"stage": "timing", "error": "service/search/validation offsets not monotone within response"})
        if validation != response-offsets[-1]:
            errors.append({"stage": "timing", "error": "validation_rank_ns differs from response minus validation-start offset"})
        if row.get("core_ns") is not None and row["core_ns"] > offsets[1]-offsets[0]:
            errors.append({"stage": "timing", "error": "individual core_ns exceeds search interval"})
    meta = expected[q["id"]].get("evaluation_metadata", {})
    cohort = "invalid_output" if errors else ("completed_transit" if row["transit"] else "completed_all_walk" if stages["candidates"] else "completed_valid_empty") if row["completed"] else ("not_run" if not row["attempted"] else "incomplete_with_feasible_output" if stages["candidates"] or stages["raw"] else "incomplete_no_feasible_output")
    return {"query_id": q["id"], "od_cluster": meta.get("od_cluster", dumps([q["origin"], q["destination"]])),
            "split": meta.get("split", "unspecified"), "workload_cohort": meta.get("workload_cohort", "unspecified_model_coverage"),
            "labels": meta.get("labels", []), "outcome_cohort": cohort,
            "stratum": row["stratum"], "query": q, "attempted": row["attempted"],
            "completed": row["completed"], "success": row["completed"] and not errors,
            "status": "invalid_output" if errors else row["status"], "source_status": row["status"],
            "errors": errors, "source_certificates": certificates,
            "certificate_validation": "source claims preserved; mathematical completeness not recertified by evalkit",
            "stages": stages, "source_slot_counts": slot_counts, "duplicates_removed": duplicate_counts,
            "response_ns": row.get("response_ns"), "core_ns": row.get("core_ns"),
            "quality_ns": row.get("quality_ns"), "batch": row.get("batch")}


def load_run(directory, checker, expected, dataset_sha, queries_sha, cfg):
    root = Path(directory)
    summary, summary_sha = read_json(root/"summary.json")
    require(summary.get("dataset_sha256") == dataset_sha, "run dataset SHA256 mismatch")
    require(summary.get("queries_sha256") == queries_sha, "run workload SHA256 mismatch")
    algorithm = summary.get("algorithm")
    require(isinstance(algorithm, str) and algorithm, "algorithm id required")
    provenance = summary.get("provenance")
    require(isinstance(provenance, dict) and provenance, "run provenance absent")
    require(provenance.get("runtime_matches_build") is True and provenance.get("source_binding") == "embedded_build_source", "run is not source-bound to embedded build")
    for key in ("routing_source_sha256", "executable_sha256", "build_source_sha256", "runtime_tree_sha256"):
        digest = provenance.get(key, "")
        require(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), f"invalid provenance {key}")
    require(provenance["build_source_sha256"] == provenance["runtime_tree_sha256"], "runtime/build source mismatch")
    rows, passes, pass_hashes, reps = [], [], {}, set()
    for entry in summary.get("passes", []):
        if entry.get("warmup") or entry.get("forced"):
            continue
        require(entry.get("file") and Path(entry["file"]).name == entry["file"], "unsafe pass filename")
        raw, digest = read_json(root/entry["file"])
        require(digest == entry.get("sha256"), "pass artifact SHA256 mismatch")
        require(raw.get("algorithm") == algorithm and raw.get("warmup") is False, "pass algorithm/warmup mismatch")
        repetition = raw.get("repetition")
        integer(repetition, "repetition")
        require(repetition == entry.get("repetition") and repetition not in reps, "duplicate/mismatched repetition")
        reps.add(repetition)
        records = raw.get("records")
        require(isinstance(records, list), "records array required")
        seen, current = set(), []
        for record in records:
            item = reconstruct_record(record, checker, expected, cfg)
            require(item["query_id"] not in seen, "duplicate query in pass")
            seen.add(item["query_id"])
            item.update(algorithm=algorithm, repetition=repetition, pass_sha256=digest)
            current.append(item)
        require(seen == set(expected), "pass missing frozen query slots; failures must be explicit rows")
        require(entry.get("requested") == len(expected), "summary requested denominator mismatch")
        pass_hashes[entry["file"]] = digest
        makespan = integer(entry.get("makespan_ns"), "pass makespan_ns", low=1)
        require(all(r["response_ns"] is None or r["response_ns"] <= makespan for r in current), "pass makespan shorter than a recorded batch-relative response")
        batches = raw.get("batches", [])
        if batches:
            seen_batches = set()
            batch_total_ns = 0
            for batch in batches:
                bid = integer(batch.get("id"), "batch id")
                require(bid not in seen_batches, "duplicate batch id")
                seen_batches.add(bid)
                members = [r for r in current if r["batch"] == bid]
                require(set(batch.get("query_ids", [])) == {r["query_id"] for r in members} and len(batch.get("query_ids", [])) == len(members), "batch query membership mismatch")
                batch_ns = integer(batch.get("makespan_ns"), "batch makespan_ns")
                core_ns = integer(batch.get("core_ns"), "batch core_ns")
                require(core_ns <= batch_ns and all(r["response_ns"] <= batch_ns for r in members), "batch makespan shorter than recorded work/response")
                require(type(batch.get("shared_search")) is bool, "shared_search boolean required")
                if batch["shared_search"]:
                    require(all(r["core_ns"] is None for r in members), "shared per-query core_ns must remain null")
                batch_total_ns += batch_ns
            require(seen_batches == {r["batch"] for r in current}, "record refers to absent batch")
            require(batch_total_ns <= makespan, "pass makespan shorter than sequential batch makespans")
        passes.append({"repetition": repetition, "makespan_ns": makespan,
                       "requested": len(current), "successes": sum(r["success"] for r in current),
                       "completed_qps": sum(r["success"] for r in current)*1e9/makespan})
        rows.extend(current)
    require(passes, "no measured non-forced passes")
    return {"algorithm": algorithm, "summary": summary, "summary_sha256": summary_sha,
            "source_directory": str(root.resolve()), "passes": passes, "pass_sha256": pass_hashes,
            "rows": rows}


def stage_quality(js, pool, alternatives, profiles, success, cfg, context=None):
    pool_ids, observed_ids = {j["identity"] for j in pool}, {j["identity"] for j in js}
    pool_patterns = {j["pattern"] for j in alternatives}
    represented_patterns = {j["pattern"] for j in js}
    union_patterns = pool_patterns | represented_patterns
    context = context or {"best": {p["id"]: min((score(j, p) for j in pool), default=None) for p in profiles},
                          "dominated_ids": {j["identity"] for j in pool if any(dominates(o, j) for o in pool)}}
    scores = []
    for p in profiles:
        best = context["best"][p["id"]]
        partial = min((score(j, p) for j in js), default=None)
        actual = partial if success else None

        regret = actual-best if best is not None and actual is not None else None
        scores.append({"profile_id": p["id"], "pool_best_seconds": best,
                       "observed_best_seconds": actual, "pool_relative_regret_seconds": regret,
                       "partial_output_best_seconds": partial,
                       "partial_pool_relative_regret_seconds": partial-best if best is not None and partial is not None else None,
                       "eligible": best is not None, "missing": best is not None and actual is None,
                       "covered": regret is not None and regret <= cfg["coverage_tolerance_seconds"]})
    dominated = [j["identity"] for j in js if j["identity"] in context["dominated_ids"]]
    pattern_hits = pool_patterns & represented_patterns if success else set()
    eligible = sum(s["eligible"] for s in scores)
    return {"witness_count": len(js), "distinct_patterns": len(represented_patterns),
            "distinct_vectors": len({vector(j) for j in js}),
            "pool_dominated_count": len(dominated), "pool_dominated_identities": dominated,
            "pool_dominated_fraction": len(dominated)/len(js) if js else None,
            "pool_identity_fraction": len(pool_ids & observed_ids)/len(pool_ids) if pool_ids and success else 0 if pool_ids else None,
            "legitimate_pool_pattern_count": len(pool_patterns), "legitimate_pattern_hits": len(pattern_hits),
            "legitimate_pattern_overlap_fraction": len(pattern_hits)/len(pool_patterns) if pool_patterns else None,
            "pattern_jaccard": len(pattern_hits)/len(union_patterns) if union_patterns else None,
            "profile_eligible": eligible, "profiles_covered": sum(s["covered"] for s in scores),
            "profile_coverage": sum(s["covered"] for s in scores)/eligible if eligible else None,
            "profiles": scores,
            "worst_pool_relative_regret_seconds": max((s["pool_relative_regret_seconds"] for s in scores if s["pool_relative_regret_seconds"] is not None), default=None),
            "mean_pool_relative_regret_seconds": statistics.fmean([s["pool_relative_regret_seconds"] for s in scores if s["pool_relative_regret_seconds"] is not None]) if any(s["pool_relative_regret_seconds"] is not None for s in scores) else None}


def declared_2d_cap_projection(row, kind):
    """Exact integer cap vector for a declared complete source contract, not an oracle."""
    cert = row["source_certificates"]
    reason = None
    if not row["completed"] or not row["attempted"] or row["source_status"] != "complete":
        reason = "source_failed_incomplete_or_not_run"
    elif not row["success"]:
        reason = "rejected_after_independent_validation_or_certificate_counterexample"
    elif row["errors"]:
        reason = "independent_witness_metadata_or_timing_validation_failed"
    elif not cert.get("arrival_boardings"):
        reason = "source_does_not_declare_complete_arrival_boardings_frontier"
    elif kind not in ("pareto", "pareto_walking", "score_top_k"):
        reason = "unsupported_contract_projection; earliest/arrival-top-k alone does not imply 2D frontier"
    elif kind == "pareto_walking" and not cert.get("arrival_boardings_walking"):
        reason = "3D_contract_missing_declared_3D_certificate"
    elif kind == "score_top_k" and not (cert.get("score_top_k") and cert.get("score_certified_through_k", 0) > 0):
        reason = "cap_union_contract_missing_declared_score_top_k_certificate"
    eligible = reason is None
    caps = []
    if eligible:
        for b in range(row["query"]["max_boardings"]+1):
            best = min((j["metrics"]["arrival"] for j in row["stages"]["candidates"] if j["metrics"]["boardings"] <= b), default=None)
            caps.append({"max_boardings": b, "earliest_arrival": best,
                         "null_meaning": "no witness under cap within source-declared complete finite horizon; conditional source claim, NOT independently certified unreachable" if best is None else None})
    return {"eligible_declared_contract": eligible, "ineligible_reason": reason, "source_contract_kind": kind,
            "projection": "native_2D" if kind == "pareto" else "explicit_3D_to_2D_min_arrival_projection" if kind == "pareto_walking" else "explicit_complete_at_most_boarding_cap_union_to_2D_projection" if kind == "score_top_k" else None,
            "source_complete_declared": row["completed"], "reference_complete_certified_by_evalkit": False,
            "source_certificates": cert, "caps": caps,
            "limitation": "independent witness feasibility checked; completeness flags/source correctness are not a mathematical oracle proof"}


def cap_crosscheck(a, b):
    left = {(r["repetition"], r["query_id"]): r for r in a["rows"]}
    right = {(r["repetition"], r["query_id"]): r for r in b["rows"]}
    if set(left) != set(right):
        return {"baseline": a["algorithm"], "challenger": b["algorithm"], "status": "inconclusive",
                "reason": "identical offered query/repetition slots required; no silent intersection"}
    comparable, mismatches, falsified, skipped, strata = 0, [], [], collections.Counter(), collections.defaultdict(lambda: {"offered_pairs": 0, "comparable_pairs": 0, "mismatch_pairs": 0, "certificate_rejected_pairs": 0})
    offered_cap_pairs = compatible_cap_pairs = 0
    supported_individual_cap_slots = {a["algorithm"]: 0, b["algorithm"]: 0}
    for key in sorted(left):
        x, y = left[key], right[key]
        require(x["query"] == y["query"], "cap comparator query mismatch")
        strata[x["stratum"]]["offered_pairs"] += 1
        px, py = x["declared_2d_cap_projection"], y["declared_2d_cap_projection"]
        cap_count = x["query"]["max_boardings"]+1
        offered_cap_pairs += cap_count
        supported_individual_cap_slots[a["algorithm"]] += cap_count*px["eligible_declared_contract"]
        supported_individual_cap_slots[b["algorithm"]] += cap_count*py["eligible_declared_contract"]
        if x.get("certificate_counterexamples") or y.get("certificate_counterexamples"):
            strata[x["stratum"]]["certificate_rejected_pairs"] += 1
            falsified.append({"query_id": x["query_id"], "repetition": x["repetition"],
                              "baseline_counterexamples": x.get("certificate_counterexamples", []),
                              "challenger_counterexamples": y.get("certificate_counterexamples", []),
                              "baseline_observed_candidate_caps_diagnostic_only": x["observed_candidate_cap_values"],
                              "challenger_observed_candidate_caps_diagnostic_only": y["observed_candidate_cap_values"]})
        if not px["eligible_declared_contract"] or not py["eligible_declared_contract"]:
            skipped[dumps([px["ineligible_reason"], py["ineligible_reason"]])] += 1
            continue
        comparable += 1
        compatible_cap_pairs += cap_count
        strata[x["stratum"]]["comparable_pairs"] += 1
        fx = [c["earliest_arrival"] for c in px["caps"]]
        fy = [c["earliest_arrival"] for c in py["caps"]]
        if fx != fy:
            strata[x["stratum"]]["mismatch_pairs"] += 1
            mismatches.append({"query_id": x["query_id"], "repetition": x["repetition"], "stratum": x["stratum"],
                               "baseline_caps": px["caps"], "challenger_caps": py["caps"],
                               "baseline_projection": px["projection"], "challenger_projection": py["projection"],
                               "baseline_pass_sha256": x["pass_sha256"], "challenger_pass_sha256": y["pass_sha256"]})
    return {"baseline": a["algorithm"], "challenger": b["algorithm"], "offered_pairs": len(left),
            "comparable_declared_complete_pairs": comparable, "ineligible_pairs": len(left)-comparable,
            "offered_query_cap_pairs": offered_cap_pairs, "comparable_query_cap_pairs": compatible_cap_pairs,
            "ineligible_query_cap_pairs": offered_cap_pairs-compatible_cap_pairs,
            "supported_individual_query_cap_slots": supported_individual_cap_slots,
            "certificate_rejected_pairs": len(falsified), "certificate_counterexamples": falsified,
            "ineligible_reasons": dict(skipped), "mismatch_pairs": len(mismatches), "mismatches": mismatches,
            "strata": dict(strata),
            "status": "failed_certificate_counterexample" if falsified else "failed_counterexample" if mismatches else "partial_agreement_cross_corroboration_only" if comparable and comparable < len(left) else "agreement_cross_corroboration_only" if comparable else "inconclusive_no_eligible_complete_pairs",
            "truth_reference_selected": False,
            "limitation": "symmetric declared-complete claim crosscheck; agreements and all-null agreement are not optimality/unreachable proofs; failures/incomplete outputs never supply a complete reference"}


def certificate_counterexamples(row, pool):
    """Feasible witnesses can disprove a source completeness claim, never prove it."""
    if not row["completed"] or row["errors"]:
        return []
    cert, js, out = row["source_certificates"], row["stages"]["candidates"], []
    for field, fn in (("earliest_arrival", lambda j: j["metrics"]["arrival"]),
                      ("best_score", lambda j: j["duration_seconds"]+300*j["metrics"]["transfers"])):
        if cert.get(field):
            actual = min((fn(j) for j in js), default=None)
            improving = next((j for j in pool if actual is None or fn(j) < actual), None)
            if improving:
                out.append({"claim": field, "counterexample_identity": improving["identity"],
                            "reason": "independently feasible witness improves claimed complete objective"})
    for field, dimensions in (("arrival_boardings", ("arrival", "boardings")),
                              ("arrival_boardings_walking", ("arrival", "boardings", "walking_seconds"))):
        if cert.get(field):
            missing = next((j for j in pool if not any(all(a["metrics"][d] <= j["metrics"][d] for d in dimensions) for a in js)), None)
            if missing:
                out.append({"claim": field, "counterexample_identity": missing["identity"],
                            "reason": "pool has feasible objective vector not weakly dominated by any claimed complete frontier vector"})
    return out


def make_pool(runs):
    pools, sources = collections.defaultdict(list), collections.defaultdict(list)
    for run in runs:
        for row in run["rows"]:
            # Invalid rows are quarantined as a whole; failed but independently feasible partial outputs remain in pool.
            if row["errors"]:
                continue
            for stage, js in row["stages"].items():
                pools[row["query_id"]].extend(js)
                if js:
                    sources[row["query_id"]].append({"algorithm": row["algorithm"], "repetition": row["repetition"], "stage": stage,
                        "pass_sha256": row["pass_sha256"], "summary_sha256": run["summary_sha256"],
                        "configuration_sha256": sha(run["summary"].get("configuration")),
                        "source_reported_status": row["source_status"], "source_reported_completed": row["completed"], "attempted": row["attempted"]})
    return {qid: unique_journeys(js) for qid, js in pools.items()}, sources


def summarize_rows(rows):
    success = [r for r in rows if r["success"]]
    result = {"requested": len(rows), "attempted": sum(r["attempted"] for r in rows),
              "completed_valid": len(success), "failed_or_not_run": len(rows)-len(success),
              "completion_rate": len(success)/len(rows) if rows else None,
              "statuses": dict(sorted(collections.Counter(r["status"] for r in rows).items())),
              "completed_response_ns": distribution([r["response_ns"] for r in success if r["response_ns"] is not None]),
              "attempted_response_ns": distribution([r["response_ns"] for r in rows if r["attempted"] and r["response_ns"] is not None]),
              "completed_individual_core_ns": distribution([r["core_ns"] for r in success if r["core_ns"] is not None]),
              "outcome_cohorts": dict(sorted(collections.Counter(r["outcome_cohort"] for r in rows).items())),
              "stages": {}}
    for stage in STAGES:
        qualities = [r["quality"][stage] for r in rows]
        eligible = sum(q["profile_eligible"] for q in qualities)
        stage_types = collections.Counter(
            "completed_with_transit" if r["success"] and any(j["metrics"]["boardings"] for j in r["stages"][stage])
            else "completed_all_walk_only" if r["success"] and r["stages"][stage]
            else "completed_empty" if r["success"] else "failed_or_not_run" for r in rows)
        covered = sum(q["profiles_covered"] for q in qualities)
        regrets = [s["pool_relative_regret_seconds"] for q in qualities for s in q["profiles"] if s["pool_relative_regret_seconds"] is not None]
        eligible_patterns = sum(q["legitimate_pool_pattern_count"] for q in qualities)
        result["stages"][stage] = {
            "offered_request_output_types": dict(sorted(stage_types.items())),
            "eligible_query_profile_slots": eligible, "covered_query_profile_slots": covered,
            "missing_query_profile_slots": sum(s["missing"] for q in qualities for s in q["profiles"]),
            "pool_profile_coverage_including_failures": covered/eligible if eligible else None,
            "pool_relative_regret_seconds_observed_only": distribution(regrets),
            "eligible_legitimate_pool_pattern_slots": eligible_patterns,
            "legitimate_pattern_hits": sum(q["legitimate_pattern_hits"] for q in qualities),
            "legitimate_pattern_coverage_including_failures": sum(q["legitimate_pattern_hits"] for q in qualities)/eligible_patterns if eligible_patterns else None,
            "witnesses": sum(q["witness_count"] for q in qualities),
            "pool_dominated_witnesses": sum(q["pool_dominated_count"] for q in qualities),
            "profiles": [{"profile_id": pid,
                          "eligible": sum(s["eligible"] for q in qualities for s in q["profiles"] if s["profile_id"] == pid),
                          "covered": sum(s["covered"] for q in qualities for s in q["profiles"] if s["profile_id"] == pid),
                          "missing": sum(s["missing"] for q in qualities for s in q["profiles"] if s["profile_id"] == pid),
                          "pool_relative_regret_seconds_observed_only": distribution([s["pool_relative_regret_seconds"] for q in qualities for s in q["profiles"] if s["profile_id"] == pid and s["pool_relative_regret_seconds"] is not None])}
                         for pid in sorted({s["profile_id"] for q in qualities for s in q["profiles"]})],
        }
    return result


def percentile(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    x = (len(xs)-1)*p
    lo = int(math.floor(x))
    hi = int(math.ceil(x))
    return xs[lo] + (xs[hi]-xs[lo])*(x-lo)


def cluster_interval(values, boot, seed_offset=0):
    """values maps OD cluster -> observation values. Preserve all observations in sampled clusters."""
    keys = sorted(values)
    all_values = [x for k in keys for x in values[k]]
    out = {"point_estimate": statistics.fmean(all_values) if all_values else None,
           "observations": len(all_values), "od_clusters": len(keys),
           "method": "percentile paired OD-cluster bootstrap; empirical observation-weighted mean",
           "seed": boot["seed"]+seed_offset, "replicates": boot["replicates"], "confidence": boot["confidence"],
           "interval": None, "limitations": "conditional on fixed observed runs/pool; no demand-representativeness or production SLA claim"}
    if len(keys) < 2:
        out["reason"] = "at least two OD clusters required; point estimate only"
        return out
    rng = random.Random(out["seed"])
    estimates = []
    # Resampling cluster sums/counts is algebraically identical to expanding all
    # repeated query/repetition rows, without an O(rows * replicates) materialization.
    totals = {k: math.fsum(values[k]) for k in keys}
    counts = {k: len(values[k]) for k in keys}
    for _ in range(boot["replicates"]):
        sampled_keys = rng.choices(keys, k=len(keys))
        estimates.append(math.fsum(totals[k] for k in sampled_keys)/sum(counts[k] for k in sampled_keys))
    alpha = (1-boot["confidence"])/2
    out["interval"] = [percentile(estimates, alpha), percentile(estimates, 1-alpha)]
    return out


def repetition_interval(passes, boot):
    values = [p["completed_qps"] for p in passes]
    out = {"point_estimate": statistics.fmean(values), "repetitions": len(values),
           "sampling_unit": "whole measured pass", "interval": None,
           "method": "percentile bootstrap of mean completed_qps across repetitions", "seed": boot["seed"],
           "confidence": boot["confidence"], "replicates": boot["replicates"]}
    if len(values) < 2:
        out["reason"] = "at least two repetitions required; point estimate only"
        return out
    rng = random.Random(boot["seed"])
    samples = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(boot["replicates"])]
    alpha = (1-boot["confidence"])/2
    out["interval"] = [percentile(samples, alpha), percentile(samples, 1-alpha)]
    return out


def paired_comparison(a, b, cfg):
    index = lambda run: {(r["repetition"], r["query_id"]): r for r in run["rows"]}
    left, right = index(a), index(b)
    require(set(left) == set(right), "paired comparison requires identical measured repetition/query slots")
    metrics = {"success_rate_delta": collections.defaultdict(list), "completed_response_ns_delta": collections.defaultdict(list)}
    for stage in STAGES:
        metrics[stage+"_profile_coverage_delta"] = collections.defaultdict(list)
        metrics[stage+"_worst_regret_seconds_delta_joint_observed"] = collections.defaultdict(list)
    both_success = 0
    a_only = b_only = neither = 0
    for key in sorted(left):
        x, y = left[key], right[key]
        cluster = x["od_cluster"]
        require(cluster == y["od_cluster"], "paired OD mismatch")
        metrics["success_rate_delta"][cluster].append(int(y["success"])-int(x["success"]))
        both_success += x["success"] and y["success"]
        a_only += x["success"] and not y["success"]
        b_only += y["success"] and not x["success"]
        neither += not x["success"] and not y["success"]
        if x["success"] and y["success"] and x["response_ns"] is not None and y["response_ns"] is not None:
            metrics["completed_response_ns_delta"][cluster].append(y["response_ns"]-x["response_ns"])
        for stage in STAGES:
            qx, qy = x["quality"][stage], y["quality"][stage]
            if qx["profile_coverage"] is not None and qy["profile_coverage"] is not None:
                metrics[stage+"_profile_coverage_delta"][cluster].append(qy["profile_coverage"]-qx["profile_coverage"])
            if qx["worst_pool_relative_regret_seconds"] is not None and qy["worst_pool_relative_regret_seconds"] is not None:
                metrics[stage+"_worst_regret_seconds_delta_joint_observed"][cluster].append(qy["worst_pool_relative_regret_seconds"]-qx["worst_pool_relative_regret_seconds"])
    return {"baseline": a["algorithm"], "challenger": b["algorithm"], "direction": "challenger minus baseline",
            "requested_pairs": len(left), "both_success": both_success, "baseline_only_success": a_only,
            "challenger_only_success": b_only, "neither_success": neither,
            "metrics": {name: cluster_interval(v, cfg["bootstrap"], i) for i, (name, v) in enumerate(metrics.items())},
            "warning": "joint-observed latency/regret exclude failed pairs; always inspect success and coverage deltas alongside them"}


def evaluate(dataset_path, workload_path, run_dirs, cfg, metadata_path=None, reference_pool_path=None, input_manifest_path=None):
    validate_config(cfg)
    dataset, dataset_sha = read_json(dataset_path)
    workload, queries_sha = read_json(workload_path)
    require(workload.get("dataset_sha256") == dataset_sha, "workload dataset file SHA256 mismatch")
    checker = Checker(dataset)
    input_manifest_sha, source_input = None, None
    if input_manifest_path:
        input_manifest, input_manifest_sha = read_json(input_manifest_path)
        candidates = [entry for entry in input_manifest.get("inputs", []) if entry.get("dataset_sha256") == dataset_sha]
        require(len(candidates) == 1, "input manifest must bind exactly one entry to dataset SHA256")
        source_input = candidates[0]
        actual_counts = {table: len(dataset.get(table, [])) for table in ("stops", "trips", "connections", "footpaths", "transfers")}
        require(source_input.get("counts") == actual_counts, "input manifest normalized counts mismatch")
    input_coverage = "no_transit_source_coverage" if not checker.rides else "finite_normalized_events_only"
    expected = {}
    for item in workload.get("items", []):
        q = item["query"]
        checker.query(q)
        require(q["id"] not in expected, "duplicate workload query id")
        require(isinstance(item.get("stratum"), str) and item["stratum"], "explicit stratum required")
        expected[q["id"]] = item
    require(expected, "empty workload")
    metadata_sha = None
    if metadata_path:
        metadata, metadata_sha = read_json(metadata_path)
        require(metadata.get("schema_version") == VERSION, "query metadata schema mismatch")
        require(metadata.get("dataset_sha256") == dataset_sha and metadata.get("queries_sha256") == queries_sha, "query metadata binding mismatch")
        seen_meta = set()
        cluster_splits = {}
        for item in metadata.get("items", []):
            qid = item.get("query_id")
            require(qid in expected and qid not in seen_meta, "unknown/duplicate query metadata")
            seen_meta.add(qid)
            require(isinstance(item.get("od_cluster"), str) and item["od_cluster"], "metadata od_cluster required")
            require(item.get("split") in ("tune", "validation", "test", "diagnostic"), "explicit registered split required")
            require(item.get("workload_cohort") in ("model_coverage", "synthetic_stress", "historical_diagnostic"), "explicit workload_cohort required")
            require(isinstance(item.get("labels", []), list) and all(isinstance(x, str) for x in item.get("labels", [])), "labels must be strings")
            require(item["od_cluster"] not in cluster_splits or cluster_splits[item["od_cluster"]] == item["split"], "OD cluster crosses splits")
            cluster_splits[item["od_cluster"]] = item["split"]
            expected[qid]["evaluation_metadata"] = item
        require(seen_meta == set(expected), "metadata must cover every frozen query")
    # This adapter only handles stop-pair requests. Passenger wrappers must provide a separate adapter.
    require(workload.get("request_semantics", "independent_stop_pair") == "independent_stop_pair", "multi-origin/passenger workload unsupported by familybench adapter; do not relabel independent batches")
    runs = [load_run(p, checker, expected, dataset_sha, queries_sha, cfg) for p in run_dirs]
    require(len({r["algorithm"] for r in runs}) == len(runs), "duplicate algorithm; use separate invocation for configurations or unique algorithm ids")
    pools, sources = make_pool(runs)
    reference_sha, reference_pools, frozen_ledger = None, {}, None
    if reference_pool_path:
        reference, reference_sha = read_json(reference_pool_path)
        frozen_ledger = reference.get("source_runs")
        require(reference.get("schema_version") == VERSION, "reference pool schema mismatch")
        require(reference.get("dataset_sha256") == dataset_sha and reference.get("queries_sha256") == queries_sha, "reference pool binding mismatch")
        seen_reference = set()
        for entry in reference.get("queries", []):
            qid = entry.get("query_id")
            require(qid in expected and qid not in seen_reference, "unknown/duplicate reference query")
            seen_reference.add(qid)
            js = unique_journeys([checker.check(expected[qid]["query"], j) for j in entry.get("witnesses", [])])
            reference_pools[qid] = js
            pools[qid] = unique_journeys(pools.get(qid, [])+js)
            sources[qid].append({"frozen_reference_pool_file_sha256": reference_sha})
        require(seen_reference == set(expected), "reference pool must explicitly include every query, even empty")
        old_payload = {qid: sorted(reference_pools[qid], key=lambda j: j["identity"]) for qid in sorted(expected)}
        require(sha(old_payload) == reference.get("pool_sha256"), "reference pool content hash mismatch")
    pool_payload = {qid: sorted(pools.get(qid, []), key=lambda j: j["identity"]) for qid in sorted(expected)}
    pool_sha = sha(pool_payload)
    pool_manifest = {"schema_version": VERSION, "dataset_sha256": dataset_sha, "queries_sha256": queries_sha,
                     "pool_sha256": pool_sha, "frozen_reference_pool_file_sha256": reference_sha, "complete_reference": False, "global_optimality_claim": False,
                     "source_runs": [{"algorithm": r["algorithm"], "summary_sha256": r["summary_sha256"],
                                      "pass_sha256": r["pass_sha256"], "configuration": r["summary"].get("configuration"),
                                      "provenance": r["summary"]["provenance"], "seed": r["summary"].get("seed"),
                                      "batch_deadline_ns": r["summary"].get("batch_deadline_ns"),
                                      "preparation_deadline_ns": r["summary"].get("preparation_deadline_ns"),
                                      "candidate_k": r["summary"].get("candidate_k"), "source_directory": r["source_directory"]} for r in runs],
                     "frozen_reference_source_runs": frozen_ledger,
                     "pool_construction": "union of independently feasible raw/candidate/display witnesses from supplied measured passes, including valid partial failed outputs; invalid rows quarantined",
                     "queries": [{"query_id": qid, "witnesses": pool_payload[qid], "sources": sources.get(qid, [])} for qid in sorted(expected)]}
    contexts, alternatives_by_query = {}, {}
    for qid in expected:
        pool = pools.get(qid, [])
        dominated_ids = {j["identity"] for j in pool if any(dominates(o, j) for o in pool)}
        best = {p["id"]: min((score(j, p) for j in pool), default=None) for p in cfg["profiles"]}
        contexts[qid] = {"best": best, "dominated_ids": dominated_ids}
        alternatives_by_query[qid] = [j for j in pool if j["identity"] not in dominated_ids and any(score(j, p) <= best[p["id"]]+cfg["alternative_epsilon_seconds"] for p in cfg["profiles"])]
    all_rows, summaries = [], []
    for run in runs:
        for row in run["rows"]:
            pool = pools.get(row["query_id"], [])
            row["reference_pool_cohort"] = "pool_has_transit" if any(j["metrics"]["boardings"] for j in pool) else "pool_all_walk_only" if pool else "pool_empty_unknown"
            row["certificate_counterexamples"] = certificate_counterexamples(row, pool)
            if row["certificate_counterexamples"]:
                row["success"] = False
                row["status"] = "certificate_counterexample"
                row["outcome_cohort"] = "certificate_counterexample"
            row["observed_candidate_cap_values"] = [{"max_boardings": b,
                "earliest_observed_arrival": min((j["metrics"]["arrival"] for j in row["stages"]["candidates"] if j["metrics"]["boardings"] <= b), default=None),
                "null_meaning": "no observed candidate; not an unreachable claim"}
                for b in range(row["query"]["max_boardings"]+1)]
            row["declared_2d_cap_projection"] = declared_2d_cap_projection(row, run["summary"].get("kind"))
            alternatives = alternatives_by_query[row["query_id"]]
            row["quality"] = {stage: stage_quality(js, pool, alternatives, cfg["profiles"], row["success"], cfg, contexts[row["query_id"]])
                              for stage, js in row["stages"].items()}
            row["candidate_ranking_decomposition"] = []
            for i, p in enumerate(cfg["profiles"]):
                per_stage = {stage: row["quality"][stage]["profiles"][i] for stage in STAGES}
                candidate_best = per_stage["candidates"]["observed_best_seconds"]
                raw_best = per_stage["raw"]["observed_best_seconds"]
                item = {"profile_id": p["id"], "raw_discovery_gap_seconds": per_stage["raw"]["pool_relative_regret_seconds"],
                        "candidate_discovery_gap_seconds": per_stage["candidates"]["pool_relative_regret_seconds"],
                        "raw_to_candidate_loss_seconds": candidate_best-raw_best if candidate_best is not None and raw_best is not None else None}
                for stage in ("displayed", "displayed_secondary"):
                    display_best = per_stage[stage]["observed_best_seconds"]
                    item[stage+"_selection_loss_seconds"] = display_best-candidate_best if display_best is not None and candidate_best is not None else None
                row["candidate_ranking_decomposition"].append(item)
            if reference_pool_path:
                ref = reference_pools[row["query_id"]]
                row["frozen_reference_pool_diagnostics"] = {stage: [{
                    "profile_id": p["id"],
                    "signed_observed_minus_frozen_pool_seconds": min((score(j, p) for j in js), default=None)-min((score(j, p) for j in ref), default=None)
                        if js and ref else None,
                    "meaning": "negative = incomplete reference pool improved, not a routing failure; partial outputs diagnostic only"
                } for p in cfg["profiles"]] for stage, js in row["stages"].items()}
            row["pool_sha256"] = pool_sha
        # Certificate counterexamples are discovered against the common pool only now.
        # Recompute whole-pass successful throughput after those gates, not from pre-audit flags.
        for measured_pass in run["passes"]:
            offered = [r for r in run["rows"] if r["repetition"] == measured_pass["repetition"]]
            measured_pass["successes"] = sum(r["success"] for r in offered)
            measured_pass["completed_qps"] = measured_pass["successes"]*1e9/measured_pass["makespan_ns"]
        summary = summarize_rows(run["rows"])
        summary.update(algorithm=run["algorithm"], strata={s: summarize_rows([r for r in run["rows"] if r["stratum"] == s]) for s in sorted({r["stratum"] for r in run["rows"]})},
                       reference_pool_cohorts={s: summarize_rows([r for r in run["rows"] if r["reference_pool_cohort"] == s]) for s in sorted({r["reference_pool_cohort"] for r in run["rows"]})},
                       splits={s: summarize_rows([r for r in run["rows"] if r["split"] == s]) for s in sorted({r["split"] for r in run["rows"]})},
                       workload_cohorts={s: summarize_rows([r for r in run["rows"] if r["workload_cohort"] == s]) for s in sorted({r["workload_cohort"] for r in run["rows"]})},
                       aggregate_scope="unweighted descriptive offered-row mixture; not observed demand probability; inspect separate workload_cohorts and splits",
                       measured_passes=run["passes"], throughput=repetition_interval(run["passes"], cfg["bootstrap"]),
                       source_summary_sha256=run["summary_sha256"], source_pass_sha256=run["pass_sha256"],
                       source_provenance=run["summary"]["provenance"], source_configuration=run["summary"].get("configuration"))
        summaries.append(summary)
        all_rows.extend(run["rows"])
    comparisons, unavailable = [], []
    for a, b in itertools.combinations(runs, 2):
        try:
            comparisons.append(paired_comparison(a, b, cfg))
        except ValidationError as exc:
            unavailable.append({"baseline": a["algorithm"], "challenger": b["algorithm"], "reason": str(exc)})
    unsupported = [
        "global optimum, global regret, complete Pareto recall and strict identity top-k completeness: no independent certified complete reference supplied/implemented",
        "true no-path/unreachable classification: empty observed union is unknown, not certified unreachable",
        "human preference accuracy, preference probabilities, utility/welfare and real passenger demand representativeness: profiles are finite declared score hypotheses",
        "real-time reliability or missed-transfer probability: no calibrated stochastic delay model",
        "physical walking reachability/accessibility beyond explicit normalized source facts",
        "multi-origin/multi-destination candidate stop-pair passenger latency: familybench batches are independent stop-pair requests",
        "isolated process-cold first-request latency and cold cache guarantees: existing pass metadata has no process/cache isolation certificate",
        "per-query shared-search core latency: kept null, never divide batch makespan",
        "peak memory/retained heap and cross-hardware production/SLA tails from this scorecard: consult source resource artifacts separately",
    ]
    cap_crosschecks = [cap_crosscheck(a, b) for a, b in itertools.combinations(runs, 2)]
    report = {"schema_version": VERSION,
              "harness": {"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "python_version": sys.version.split()[0], "implementation": "Python stdlib independent static witness reconstruction; no router or oracle import"},
              "config": cfg, "config_sha256": sha(cfg),
              "binding": {"dataset_sha256": dataset_sha, "queries_sha256": queries_sha, "pool_sha256": pool_sha,
                          "input_manifest_sha256": input_manifest_sha, "query_metadata_sha256": metadata_sha, "frozen_reference_pool_file_sha256": reference_sha,
                          "service_date": dataset["service_date"], "time_zone": dataset["time_zone"], "data_kind": dataset.get("data_kind", "unspecified")},
              "input_coverage": {"status": input_coverage, "qualified_for_transit_evaluation": bool(checker.rides),
                                 "connection_count": len(checker.rides), "footpath_count": len(checker.walks),
                                 "source_manifest_entry": source_input,
                                 "warning": "zero loaded transit events is unavailable transit source coverage, not proof of physical unreachability; mathematical empty completions are not passenger-service successes" if not checker.rides else "normalized finite-model results do not establish physical coverage/source truth"},
              "request_semantics": "independent_stop_pair",
              "display_stage_labels": {"displayed": {"role": "primary", "k": cfg["display"]["k"]}, "displayed_secondary": {"role": "secondary", "k": cfg["secondary_display_k"]}},
              "cluster_policy": "explicit hash-bound metadata od_cluster" if metadata_path else "directed stop OD fallback; shared corridors/parent-stations/reversals may be correlated",
              "split_warning": None if metadata_path else "no registered split/cluster metadata supplied; no held-out generalization claim", "complete_reference": False,
              "global_optimality_claim": False, "profiles_are": "finite nonnegative score hypotheses, not learned/authenticated passenger preferences",
              "score_formula": "arrival - departure + transfer_seconds * transfers + extra_walk_weight * walking_seconds",
              "legitimate_alternative_definition": "union-pool nondominated in (duration, transfers, walking_seconds) AND within alternative_epsilon_seconds of pool best under at least one declared profile; pattern = route + visited stop sequence + explicit walk refs, consecutive same-vehicle rides merged",
              "reference_pool_cohort_policy": "shared query cohorts from frozen R*: pool_has_transit / pool_all_walk_only / pool_empty_unknown. Per-cohort offered outcomes/quality/latency are separate. Good all-walk-only pool scores do not establish transit discovery or physical reachability.",
              "failure_policy": "all frozen requested rows retained; failed/not-run/invalid/certificate-counterexample outputs have zero delivered coverage where pool eligible and null delivered regret; partial witnesses diagnostic only",
              "certificate_counterexample_scope": "feasible union witnesses may disprove source EA, default elapsed+300*transfers best-score, 2D or 3D Pareto claims. Absence of a counterexample does not prove completeness. Strict identity top-k certificate reconstruction not implemented.",
              "pool_warning": "pool-relative scores change if the observed union changes; compare only the same pool_sha256/config_sha256. Zero regret is not global optimality. Pool includes evaluated algorithms and is not held-out truth.",
              "algorithms": summaries,
              "declared_2d_cap_crosschecks": {"definition": "F[b] = earliest validated candidate arrival among actual boardings <= b; b=0 included",
                                              "reference_completeness": "source-declared only, independently feasible witnesses; no oracle completeness proof created",
                                              "comparisons": cap_crosschecks},
              "paired_comparisons": comparisons, "unavailable_paired_comparisons": unavailable,
              "unsupported_metrics": unsupported}
    return report, all_rows, pool_manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--query-metadata", type=Path)
    parser.add_argument("--reference-pool", type=Path)
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--write-default-config", type=Path)
    args = parser.parse_args(argv)
    if args.write_default_config:
        args.write_default_config.write_text(json.dumps(DEFAULT_CONFIG, indent=2)+"\n")
        return 0
    if not (args.dataset and args.queries and args.run and args.out):
        parser.error("--dataset, --queries, at least one --run and --out required")
    try:
        cfg = read_json(args.config)[0] if args.config else DEFAULT_CONFIG
        report, rows, pool = evaluate(args.dataset, args.queries, args.run, cfg, args.query_metadata, args.reference_pool, args.input_manifest)
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/"scorecard.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
        (args.out/"queries.jsonl").write_text("".join(dumps(r)+"\n" for r in rows))
        (args.out/"pool.json").write_text(json.dumps(pool, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
        artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.iterdir()}
        (args.out/"artifacts.json").write_text(json.dumps({"schema_version": VERSION, "files_sha256": artifacts}, indent=2)+"\n")
        print(dumps({"output": str(args.out), "algorithms": len(report["algorithms"]), "requested_rows": len(rows), "pool_sha256": pool["pool_sha256"], "complete_reference": False}))
        return 0
    except (ValidationError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"evalkit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
