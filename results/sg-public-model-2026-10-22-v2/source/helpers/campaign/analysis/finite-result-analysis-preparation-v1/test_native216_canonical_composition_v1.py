"""SOURCE ONLY: focused synthetic canonical composition tests, never run here.

Future execution reads only inert source and temporary synthetic fixtures. The
real resolver, InventoryProxy, and frontier source APIs are injected, with the
existing synthetic inventory fixture. No actual canonical map, campaign payload,
model, archive operator, restoration, module monkeypatch, or scorer is used.
The tiny regular_reader below is a synthetic test dependency, not a replacement
or qualification claim for the independently qualified production reader.
"""
import contextlib
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
FRONTIER = HERE.parent / "native216-frontier-preparation-v1"


def source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canonical = source_module("canonical_native216_orchestration_test", HERE / "native216_orchestrator_v2_canonical.py")
composition = source_module("native216_composition_test", HERE / "native216_canonical_composition_v1.py")
resolver_module = source_module("native216_resolver_composition_test", FRONTIER / "canonical_json_resolver_v1.py")
transport = source_module("native216_inventory_composition_test", FRONTIER / "native_inventory_transport_v1.py")
frontier = source_module("native216_frontier_composition_test", FRONTIER / "native216_frontier_v1.py")
fixtures = source_module("native216_v2_synthetic_fixtures", HERE / "test_native216_orchestrator_v2.py")


@contextlib.contextmanager
def regular_reader(path):
    with Path(path).open("rb") as stream:
        yield stream, None


def pin(path, data):
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


class SyntheticBase:
    """Keep all fixture metadata injected; the one summary uses real temp bytes."""
    def __init__(self, base, summary_path):
        self.base = base
        self.summary_path = str(summary_path)
        self.bindings = base.bindings
        self.summary_reads = 0

    def read_path(self, path, expected_sha=None):
        path = str(path)
        if path != self.summary_path:
            return self.base.read_path(path, expected_sha=expected_sha)
        with regular_reader(Path(path)) as (stream, _):
            data = stream.read()
        actual = pin(path, data)
        if expected_sha is not None and actual["sha256"] != expected_sha:
            raise ValueError("synthetic summary SHA differs")
        self.bindings[path] = actual["sha256"]
        self.summary_reads += 1
        return json.loads(data)

    def read_ref(self, reference):
        if reference["path"] != self.summary_path:
            return self.base.read_ref(reference)
        value = self.read_path(reference["path"], expected_sha=reference["sha256"])
        if "bytes" in reference and Path(reference["path"]).stat().st_size != reference["bytes"]:
            raise ValueError("synthetic summary size differs")
        return value

    def file_ref(self, path):
        if str(path) != self.summary_path:
            return self.base.file_ref(path)
        with regular_reader(Path(path)) as (stream, _):
            return pin(path, stream.read())


class SyntheticInventory(fixtures.FakeInventory):
    def preparation_diagnosis(self, summary, driver, state):
        return {"classification": None, "synthetic_state": state}

    def classify_failure(self, summary, result, state, statuses):
        return "synthetic_native_evidence_only_not_acceptance"


class RecordingProxy(transport.InventoryProxy):
    def __init__(self, inv, io, native):
        super().__init__(inv, io, native)
        self.received_binding_maps = []

    def inspect_run(self, campaign, spec, freeze, bindings):
        self.received_binding_maps.append(bindings)
        return super().inspect_run(campaign, spec, freeze, bindings)

    def load_passes(self, summary, artifact, expected, driver, argv, algorithm, bindings):
        self.received_binding_maps.append(bindings)
        return super().load_passes(summary, artifact, expected, driver, argv, algorithm, bindings)


class Native216CanonicalCompositionTests(unittest.TestCase):
    def fixture(self, *, present=False, approved=True, timed_out=False):
        temp = tempfile.TemporaryDirectory(prefix="native216-composition-synthetic-")
        self.addCleanup(temp.cleanup)
        f = fixtures.Fixture(temp.name)
        f.inv = SyntheticInventory()
        f.inv.payloads = f.io.values
        f.binding["window"] = canonical.WINDOWS[3]
        campaign, spec, _, payload = f.launch(kind="bare_tb")
        if timed_out:
            payload["records"][0]["timed_out"] = True
        artifact = campaign / spec["id"] / "artifact"
        summary_path = artifact / "summary.json"
        document = json.dumps(f.io.values[str(summary_path)], sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode()
        if present:
            summary_path.write_bytes(document)
        else:
            summary_path.unlink()  # Only a newly made synthetic fixture, never a real raw payload.
        f.io.add(artifact / "ordinary.json.io.json", {"sha256": fixtures.SHA,
            "serialization_ns": 2, "write_ns": 3, "bytes": 1, "scope": frontier.IO_SCOPE})
        entries = []
        if approved:
            archive_path = artifact / "summary.json.gz"
            compressed = gzip.compress(document, mtime=0)
            archive_path.write_bytes(compressed)
            raw_ref, archive_ref = pin(summary_path, document), pin(archive_path, compressed)
            manifest = {"schema": "prospective-lossless-storage-v1",
                "kind": "immutable-lossless-archive-manifest", "raw_path": raw_ref["path"],
                "raw_sha256": raw_ref["sha256"], "raw_bytes": raw_ref["bytes"],
                "archive_path": archive_ref["path"], "gzip_sha256": archive_ref["sha256"],
                "gzip_bytes": archive_ref["bytes"], "reconstruction_verified_sha256": raw_ref["sha256"],
                "reconstruction_verified_bytes": raw_ref["bytes"]}
            manifest_path = artifact / "summary.json.archive.json"
            manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            manifest_path.write_bytes(manifest_bytes)
            entries.append({"raw": raw_ref, "archive": archive_ref,
                            "manifest": pin(manifest_path, manifest_bytes)})
        base = SyntheticBase(f.io, summary_path)
        audit = fixtures.FakeAudit()
        wrapped = composition.Native216CanonicalComposition(
            base_io=base, approved_entries=entries,
            resolver_class=resolver_module.CanonicalJSONResolver,
            regular_reader=regular_reader, inventory_proxy_class=RecordingProxy,
            frontier_module=frontier, inv=f.inv, audit=audit, orchestration=canonical)
        out = f.root / "canonical-output"
        out.mkdir()
        return f, spec, summary_path, wrapped, out, audit

    def run_fixture(self, **kwargs):
        f, spec, summary_path, wrapped, out, audit = self.fixture(**kwargs)
        report = wrapped.run_native_window(f.binding, out)
        offers = [json.loads(line) for line in (out / "OFFERED_NATIVE_ROWS.jsonl").read_text().splitlines()]
        offer = next(row for row in offers if row["run_id"] == spec["id"])
        return f, spec, summary_path, wrapped, out, audit, report, offer

    def test_registered_retired_canonical_summary_is_consumed_without_raw_creation(self):
        f, spec, path, wrapped, out, audit, report, offer = self.run_fixture()
        self.assertFalse(path.exists())
        self.assertTrue(wrapped.io.is_approved_archive_path(str(path)))
        self.assertTrue(offer["native_row_present_and_validated"])
        self.assertTrue(offer["native_complete"])
        self.assertEqual(report["typed_offer_counts"]["bare_tb"]["native_complete_rows"], 1)
        self.assertEqual(wrapped.io.transport_bindings[str(path)]["transport"], "exact-approved-gzip")
        self.assertTrue(wrapped.io.transport_bindings[str(path)]["full_eof_crc_and_raw_identity_verified"])
        self.assertEqual(offer["run_id"], spec["id"])
        self.assertNotEqual(offer["run_id"], offer["original_native_contract_id"])
        self.assertEqual(report["model_count"], 0)
        self.assertEqual(audit.model_loads, 0)

    def test_unregistered_missing_summary_stays_unknown_without_discovery(self):
        f, spec, path, wrapped, out, audit, report, offer = self.run_fixture(approved=False)
        self.assertFalse(path.exists())
        self.assertFalse(wrapped.io.is_approved_archive_path(str(path)))
        self.assertFalse(offer["native_row_present_and_validated"])
        self.assertFalse(offer["native_complete"])
        self.assertEqual(offer["status"], "unavailable_missing_or_unbound_native_row")
        self.assertIsNone(offer["native_response_ns"])
        self.assertIsNone(offer["accepted_response_ns"])
        self.assertEqual(report["typed_offer_counts"]["bare_tb"]["native_complete_rows"], 0)
        self.assertEqual(wrapped.io.transport_bindings, {})

    def test_unchanged_raw_present_path_works_without_an_approved_archive_entry(self):
        f, spec, path, wrapped, out, audit, report, offer = self.run_fixture(present=True, approved=False)
        self.assertTrue(path.exists())
        self.assertFalse(wrapped.io.is_approved_archive_path(str(path)))
        self.assertTrue(offer["native_complete"])
        self.assertEqual(offer["native_response_ns"], 9)
        self.assertGreater(wrapped.base_io.summary_reads, 0)
        self.assertEqual(wrapped.io.transport_bindings, {})
        self.assertEqual(report["accepted_clocks"], 0)

    def test_complete_timed_out_remains_false_after_canonical_transport(self):
        f, spec, path, wrapped, out, audit, report, offer = self.run_fixture(timed_out=True)
        self.assertFalse(path.exists())
        self.assertTrue(offer["native_row_present_and_validated"])
        self.assertFalse(offer["native_complete"])
        self.assertTrue(offer["native_completion_contradiction"])
        self.assertEqual(offer["status"], "native_claimed_complete_contradiction")
        self.assertIs(offer["native_completion_evidence"]["claim_value"], True)
        self.assertIs(offer["native_completion_evidence"]["row_flags"]["timed_out"], True)
        self.assertEqual(report["typed_offer_counts"]["bare_tb"]["native_complete_rows"], 0)
        self.assertEqual(report["native_completion_contradiction_rows"], 1)
        self.assertEqual(offer["native_response_ns"], 9)
        self.assertIsNone(offer["accepted_response_ns"])
        self.assertFalse(offer["clock_qualification"]["complete_native_row_clock_eligible"])
        self.assertEqual(report["accepted_clocks"], 0)

    def test_composition_passes_the_exact_same_bindings_map_to_the_real_proxy(self):
        f, spec, path, wrapped, out, audit, report, offer = self.run_fixture()
        self.assertIs(wrapped.io.bindings, f.io.bindings)
        self.assertIs(wrapped.io.bindings, wrapped.base_io.bindings)
        self.assertIs(wrapped.inventory.io, wrapped.io)
        self.assertIs(wrapped.inventory.inv, f.inv)
        self.assertIs(wrapped.inventory.native, frontier)
        self.assertIs(wrapped.audit, audit)
        self.assertIs(wrapped.orchestration, canonical)
        self.assertTrue(wrapped.inventory.received_binding_maps)
        self.assertTrue(all(value is wrapped.io.bindings for value in wrapped.inventory.received_binding_maps))
        self.assertIn(str(path), wrapped.io.bindings)


if __name__ == "__main__":
    unittest.main()
