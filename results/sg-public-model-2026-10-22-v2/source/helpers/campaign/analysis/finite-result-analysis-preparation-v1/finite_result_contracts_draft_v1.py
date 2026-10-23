"""Unexecuted pure source draft. No I/O, model, evaluator, router or launcher.

These primitives can only check supplied typed ledgers or count serialization
bytes. They neither qualify their caller's evidence nor grant an admission.
No source below has been imported, compiled, tested or hashed in preparation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import json
import math
from typing import Any, Iterable, Literal, Mapping


WINDOWS = (
    "weekday-morning-20261020",
    "weekday-midday-20261020",
    "weekday-evening-20261020",
    "weekday-overnight-20261020",
)
RUNTIMES = frozenset((gc, limit) for gc in ("50", "100", "200")
                     for limit in ("4GiB", "7GiB"))
RESERVE_BYTES = 1_000_000_000
PROSPECTIVE_DISK_FLOOR_BYTES = 3_100_000_000
GZIP_CHUNK_BYTES = 1_048_576
OTHER_V4_FILES = frozenset((
    "CANDIDATE_DELIVERY_CONTRACT_ROWS.jsonl", "ORACLE_COMPARISONS.json",
    "QUALITY_ROWS.jsonl", "QUALITY_AGGREGATE.json",
    "INDEPENDENT_ORACLE_SLOTS.json", "NATIVE_COUNTEREXAMPLES.json",
    "VALIDATION_ERRORS.json", "REPORT.json", "FEASIBLE_REFERENCE_IMPORT.json",
    "FEASIBLE_REFERENCE_PROVENANCE.json",
))


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def natural(value: int, name: str) -> int:
    need(type(value) is int and value >= 0, "unknown/invalid " + name)
    return value


def finite_json(value: Any) -> None:
    """Reject unbounded/non-JSON tokens; do not round int/float identities."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        need(math.isfinite(value), "nonfinite numeric token")
        return
    if type(value) is list:
        for item in value:
            finite_json(item)
        return
    if type(value) is dict:
        need(all(type(key) is str for key in value), "non-string object key")
        for item in value.values():
            finite_json(item)
        return
    raise ValueError("unsupported JSON token type: " + type(value).__name__)


class NativeClaim(str, Enum):
    PREPARATION_UNAVAILABLE = "not_run_preparation_unavailable"
    LABEL_LIMIT = "internal_label_limit"
    COMPLETE_NONEMPTY = "native_claimed_complete_nonempty"
    COMPLETE_EMPTY = "native_claimed_complete_empty"
    UNKNOWN = "unknown_native_evidence"


class IndependentState(str, Enum):
    UNKNOWN = "not_independently_accepted"
    REJECTED = "independent_validation_or_contract_rejected"
    COMPLETE_NONEMPTY = "independently_complete_nonempty"
    COMPLETE_EMPTY = "independently_complete_empty"


@dataclass(frozen=True, order=True)
class OfferKey:
    campaign: str
    run_id: str
    model_sha256: str
    query_id: str


@dataclass(frozen=True)
class CapOffer:
    key: OfferKey
    window: str
    native_claim: NativeClaim
    independent_state: IndependentState
    observed_response_ns: int | None
    accepted_response_ns: int | None
    native_publication_marker: bool


def cap_native_claim_census(
    rows: Iterable[CapOffer], expected_keys: frozenset[OfferKey]
) -> dict[str, Any]:
    """Full cap5760 only. Native claims do not become quality acceptance."""
    rows = tuple(rows)
    keys = [row.key for row in rows]
    need(len(keys) == len(set(keys)), "duplicate offered cap key")
    need(set(keys) == expected_keys and len(keys) == 5760,
         "missing/extra cap offer or wrong full offered census")
    windows = Counter(row.window for row in rows)
    need(windows == Counter({window: 1440 for window in WINDOWS}),
         "cap window denominator changed")
    states = Counter(row.native_claim for row in rows)
    need(states == Counter({
        NativeClaim.PREPARATION_UNAVAILABLE: 840,
        NativeClaim.LABEL_LIMIT: 276,
        NativeClaim.COMPLETE_NONEMPTY: 3172,
        NativeClaim.COMPLETE_EMPTY: 1472,
    }), "cap native-claim source audit reconciliation differs")
    complete_native = {NativeClaim.COMPLETE_NONEMPTY, NativeClaim.COMPLETE_EMPTY}
    complete_independent = {
        IndependentState.COMPLETE_NONEMPTY, IndependentState.COMPLETE_EMPTY
    }
    for row in rows:
        need(isinstance(row.native_claim, NativeClaim), "untyped native claim")
        need(isinstance(row.independent_state, IndependentState),
             "untyped independent state")
        need(type(row.native_publication_marker) is bool, "untyped native marker")
        if row.observed_response_ns is not None:
            natural(row.observed_response_ns, "observed response")
        if row.independent_state in complete_independent:
            need(row.native_claim in complete_native,
                 "independent completion cannot promote incomplete native offer")
        if row.accepted_response_ns is not None:
            natural(row.accepted_response_ns, "accepted response")
            need(row.independent_state in complete_independent,
                 "unknown/rejected offer has accepted latency")
            need(row.observed_response_ns == row.accepted_response_ns,
                 "accepted clock differs from exact observed clock")
        if row.native_claim == NativeClaim.PREPARATION_UNAVAILABLE:
            need(row.accepted_response_ns is None,
                 "preparation placeholder has accepted clock")
        if row.native_publication_marker:
            need(row.native_claim in complete_native,
                 "native marker attached to incomplete native offer")
    # First-marker identity/stream/clock acceptance is an independent receipt,
    # not inferable from this per-row native boolean.
    marker_count = sum(row.native_publication_marker for row in rows)
    need(marker_count == 82, "native marker count changed")
    marker_runs = Counter((row.key.campaign, row.key.run_id) for row in rows
                          if row.native_publication_marker)
    need(len(marker_runs) == 82 and all(count == 1 for count in marker_runs.values()),
         "duplicate native marker process or wrong marker-process census")
    return {
        "status": "NATIVE_CLAIM_CENSUS_ONLY_NOT_QUALITY_OR_TIMING_ACCEPTANCE",
        "offered": len(rows),
        "native_claim_states": {key.value: value for key, value in states.items()},
        "independent_states": dict(Counter(row.independent_state.value for row in rows)),
        "native_markers": marker_count,
        "missing_accepted_response_clocks": sum(
            row.accepted_response_ns is None for row in rows
        ),
        "homogeneous96_or_paired_same_envelope_timing_claim": False,
    }


NativeKind = Literal["range_profile", "tad", "corech_graph", "bare_tb", "scoped_tp"]


@dataclass(frozen=True)
class NativePosition:
    campaign: str
    run_id: str
    original_contract_id: str
    kind: NativeKind
    window: str
    block: int
    position: int
    gogc: str
    gomemlimit: str
    terminal_state: str


def native_process_census(
    rows: Iterable[NativePosition],
    exact_new_campaigns: Mapping[int, str],
    expected_new_ids: frozenset[str],
    original68_ids: frozenset[str],
    selected18_ids: frozenset[str],
    original_contract_metadata: Mapping[str, tuple[NativeKind, str]],
    accepted_terminal_states: frozenset[str],
) -> dict[str, Any]:
    """No native request-unit pooling or aliasing into original native960."""
    rows = tuple(rows)
    need(len(original68_ids) == 68 and len(selected18_ids) == 18
         and selected18_ids <= original68_ids, "original native scope changed")
    need(set(original_contract_metadata) == selected18_ids,
         "selected original contract metadata census changed")
    need(len(expected_new_ids) == 216 and len(rows) == 216,
         "new native process census incomplete")
    ids = [row.run_id for row in rows]
    need(len(ids) == len(set(ids)) and set(ids) == expected_new_ids,
         "missing/extra/duplicate new native ID")
    need(set(exact_new_campaigns) == {0, 1}, "two actual native campaigns required")
    need(accepted_terminal_states, "terminal-state authority missing")
    for row in rows:
        need(row.block in (0, 1) and row.campaign == exact_new_campaigns[row.block],
             "actual new campaign/block identity changed")
        need(row.original_contract_id in selected18_ids,
             "nonselected original contract received a new offer")
        need((row.kind, row.window) == original_contract_metadata[row.original_contract_id],
             "typed contract/window alias differs from exact original")
        need(row.run_id != row.original_contract_id, "new run forged as original ID")
        need((row.gogc, row.gomemlimit) in RUNTIMES, "undeclared runtime cell")
        need(row.window in WINDOWS, "unexpected original window")
        natural(row.position, "native position")
        need(row.terminal_state in accepted_terminal_states,
             "nonterminal/missing native outcome")
    for block in (0, 1):
        positions = [row.position for row in rows if row.block == block]
        need(len(positions) == 108 and set(positions) == set(range(108)),
             "missing/duplicate native block position")
    products = Counter((row.original_contract_id, row.block,
                        row.gogc, row.gomemlimit) for row in rows)
    expected = Counter({(cid, block, gc, limit): 1 for cid in selected18_ids
                        for block in (0, 1) for gc, limit in RUNTIMES})
    need(products == expected, "original18 x runtime6 x reverse-block2 changed")
    kinds = Counter(row.kind for row in rows)
    need(kinds == Counter(range_profile=96, tad=48, corech_graph=48,
                          bare_tb=12, scoped_tp=12), "native typed partition differs")
    windows = Counter(row.window for row in rows)
    need(windows == Counter({window: (72 if "overnight" in window else 48)
                             for window in WINDOWS}), "native window partition differs")
    need(all("overnight" in row.window for row in rows
             if row.kind in ("bare_tb", "scoped_tp")),
         "point subset outside frozen overnight scope")
    return {
        "status": "PROCESS_LEDGER_ONLY_NO_COMMON_NATIVE_UNIT_OR_QUALITY_PERCENT",
        "new_processes": 216, "original_contracts": 68, "selected_contracts": 18,
        "other_original_contracts_with_zero_new_offers": 50,
        "typed_processes": dict(kinds), "window_processes": dict(windows),
        "terminal_states": dict(Counter(row.terminal_state for row in rows)),
        "original_native960_replaced": False,
    }


def original_reference_census(
    scalar_offered: int, scalar_complete: int, scalar_unknown: int,
    native_offered: int, native_source_complete: int, native_prep_unavailable: int,
) -> dict[str, int]:
    actual = (scalar_offered, scalar_complete, scalar_unknown,
              native_offered, native_source_complete, native_prep_unavailable)
    for value in actual:
        natural(value, "original reference count")
    need(actual == (432, 414, 18, 960, 780, 180),
         "original scalar/native reference ledger changed or repeated totals summed")
    return dict(scalar_offered=432, scalar_complete=414, scalar_unknown=18,
                native_offered=960, native_source_complete=780,
                native_bare_tb_preparation_unavailable=180)


def v4_array_serialized_bytes(records: Iterable[dict[str, Any]]) -> int:
    """Exact unchanged sink encoding, not compact bytes times newline ratio."""
    encoder = json.JSONEncoder(indent=2, sort_keys=True)
    count, body = 0, 0
    for record in records:
        finite_json(record)
        for chunk in encoder.iterencode(record):
            body += len(chunk.replace("\n", "\n  ").encode("utf-8"))
        count += 1
    return body + 4 * count + 3 if count else 3


Serializer = Literal["v4-array", "v4-jsonl", "v4-document", "native-canonical-jsonl"]


def jsonl_record_serialized_bytes(record: dict[str, Any], *, native: bool = False) -> int:
    finite_json(record)
    if native:
        text = json.dumps(record, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    else:
        text = json.dumps(record, separators=(",", ":"))
    return len((text + "\n").encode("utf-8"))


def v4_document_serialized_bytes(document: Any) -> int:
    finite_json(document)
    return len((json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def gzip_additional_workspace_bytes(raw_bytes: int) -> int:
    raw_bytes = natural(raw_bytes, "raw gzip input bytes")
    return raw_bytes + raw_bytes // 100 + GZIP_CHUNK_BYTES


@dataclass(frozen=True)
class FileUpperBound:
    name: str
    serializer: Serializer
    upper_bytes: int
    source_and_field_census_binding: str
    complete_field_bound: bool


@dataclass(frozen=True)
class WindowDiskTerms:
    window: str
    metrics: FileUpperBound
    other_ten_outputs: tuple[FileUpperBound, ...]
    original_path_restore_peak_bytes: int
    projection_peak_bytes: int
    partial_log_control_verification_peak_bytes: int
    observed_free_bytes: int


def disk_forecast_projection(terms: WindowDiskTerms) -> dict[str, Any]:
    """Numeric projection only. No acceptance/restore/archive/admission API."""
    need(terms.window in WINDOWS, "unfrozen window")
    need(terms.metrics.name == "METRICS_BY_RUN.json"
         and terms.metrics.serializer == "v4-array", "wrong METRICS serializer")
    names = [bound.name for bound in terms.other_ten_outputs]
    need(len(names) == len(set(names)) == 10 and set(names) == OTHER_V4_FILES,
         "missing/extra/duplicate V4 output bound")
    for bound in (terms.metrics, *terms.other_ten_outputs):
        natural(bound.upper_bytes, "file upper bytes")
        need(bound.complete_field_bound and bound.source_and_field_census_binding,
             "unresolved serializer/field bound: " + bound.name)
    restore = natural(terms.original_path_restore_peak_bytes, "restore peak")
    projection = natural(terms.projection_peak_bytes, "projection peak")
    temp = natural(terms.partial_log_control_verification_peak_bytes, "temporary peak")
    free = natural(terms.observed_free_bytes, "observed free bytes")
    metrics = terms.metrics.upper_bytes
    other = sum(bound.upper_bytes for bound in terms.other_ten_outputs) + projection
    workspace = gzip_additional_workspace_bytes(metrics)
    peak = restore + metrics + other + workspace + temp + RESERVE_BYTES
    required = max(PROSPECTIVE_DISK_FLOOR_BYTES, peak)
    return {
        "status": "FORECAST_PROJECTION_ONLY_NOT_ADMISSION_OR_READER_QUALIFICATION",
        "window": terms.window, "metrics_upper_bytes": metrics,
        "restore_peak_bytes": restore, "other_outputs_and_projection_bytes": other,
        "gzip_additional_workspace_bytes": workspace, "temporary_peak_bytes": temp,
        "reserve_bytes": RESERVE_BYTES, "calculated_peak_additional_bytes": peak,
        "original_prospective_gate_floor_bytes": PROSPECTIVE_DISK_FLOOR_BYTES,
        "required_free_bytes": required, "observed_free_bytes": free,
        "arithmetic_fit_only": free >= required,
        "analysis_launch_authorized": False,
    }
