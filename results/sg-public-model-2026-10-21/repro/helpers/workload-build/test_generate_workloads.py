import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import generate_workloads as g


class WorkloadTests(unittest.TestCase):
    def test_hash_rng_repeat_and_bounds(self):
        a, b = g.HashRNG("unit"), g.HashRNG("unit")
        self.assertEqual([a.below(103) for _ in range(200)], [b.below(103) for _ in range(200)])
        with self.assertRaises(ValueError):
            a.below(0)

    def test_allocations(self):
        for n in range(1, 71):
            self.assertEqual(n, sum(g.allocation(n).values()))

    def test_pipeline_and_commitment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [f"S{i},Stop{i},1.3,{103.6 + (i//6)*.15 + (i%6)*.005},0," for i in range(18)]
            zpath = root / "source.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n" + "\n".join(rows))
                z.writestr("routes.txt", "route_id,route_type\nR,3\n")
                z.writestr("trips.txt", "trip_id,route_id\nT,R\n")
                z.writestr("frequencies.txt", "trip_id,headway_secs\nT,600\n")
                z.writestr("stop_times.txt", "trip_id,stop_id,stop_sequence\n" + "\n".join(f"T,S{i},{i}" for i in range(18)))
            windows = [{"id": x, "service_date": "2026-10-20", "start": 0, "end": 10800,
                        "departures_start": 0, "departures_end_exclusive": 7200} for x in ("active", "empty")]
            wp = root / "windows.json"
            wp.write_text(json.dumps({"windows": windows}))
            args = argparse.Namespace(gtfs_zip=str(zpath), window_plan=str(wp), out=str(root / "plan1"),
                                      smoke_clusters=4, screen_clusters=4, full_clusters=4, final_clusters=0, departures=3)
            with contextlib.redirect_stdout(io.StringIO()):
                g.plan(args)
                args.out = str(root / "plan2")
                g.plan(args)
            self.assertEqual((root / "plan1/planned-workload.json").read_bytes(), (root / "plan2/planned-workload.json").read_bytes())
            plan = g.read_json(root / "plan1/planned-workload.json")
            pairs = [tuple(c["unordered_parent_pair"]) for c in plan["clusters"]]
            self.assertEqual(len(pairs), len(set(pairs)))
            self.assertTrue(all(c["split"] == "tune" for c in plan["clusters"] if c["stage"] == "smoke"))
            for c in plan["clusters"]:
                for w in windows:
                    n = 1 if c["stage"] == "smoke" else 3
                    for i in range(n):
                        rec = g.query_record(plan, c, w, "primary_1h_walk600", i)
                        q = rec["query"]
                        self.assertEqual(3600, q["latest_arrival"] - q["departure"])
                        self.assertEqual(4, q["max_boardings"])
                        self.assertEqual(3000, q["max_walk_seconds"])
                        self.assertEqual({600}, set(q["walking_limits"].values()))
                        long = g.query_record(plan, c, w, "long_horizon_2h_walk600", i)
                        if long:
                            self.assertEqual(7200, long["query"]["latest_arrival"] - q["departure"])
                        else:
                            self.assertGreater(q["departure"] + 7200, w["end"])
            paths = {}
            for w in windows:
                d = {"service_date": w["service_date"], "time_zone": "Asia/Singapore", "window": {"start": 0, "end": 10800},
                     "stops": [{"id": f"S{i}"} for i in range(18)], "connections": [{}] if w["id"] == "active" else []}
                p = root / (w["id"] + ".json")
                p.write_bytes(g.canonical(d))
                paths[w["id"]] = str(p)
            bindings = root / "bindings.json"
            bindings.write_text(json.dumps(paths))
            with contextlib.redirect_stdout(io.StringIO()):
                g.bind(argparse.Namespace(plan=str(root / "plan1/planned-workload.json"), datasets=str(bindings), out=str(root / "bound")))
            manifest = g.read_json(root / "bound/bound-manifest.json")
            self.assertEqual("unsupported_input_profile_no_service_connections", manifest["unavailable_windows"][0]["status"])
            self.assertTrue(all(f["queries"] > 0 for f in manifest["files"]))
            for f in manifest["files"]:
                p = root / "bound" / f["path"]
                data = g.read_json(p)
                self.assertEqual({"seed", "method", "dataset_sha256", "items"}, set(data))
                meta = g.read_json(str(p).removesuffix(".json") + ".metadata.json")
                self.assertEqual(g.digest(p.read_bytes()), meta["queries_sha256"])
                self.assertEqual({x["query"]["id"] for x in data["items"]}, {x["query_id"] for x in meta["items"]})
            # A changed plan fails before writing output: no silent regeneration.
            changed = g.read_json(root / "plan1/planned-workload.json")
            changed["seed"] = 42
            (root / "plan1/planned-workload.json").write_bytes(g.canonical(changed))
            with self.assertRaises(ValueError):
                g.bind(argparse.Namespace(plan=str(root / "plan1/planned-workload.json"), datasets=str(bindings), out=str(root / "tampered")))


if __name__ == "__main__":
    unittest.main()
