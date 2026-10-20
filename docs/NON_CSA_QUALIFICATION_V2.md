# Non-CSA qualification v2 adapters

These opt-in experiments have distinct names and explicit configuration. The [instrumented aggregate report](../results/non-csa-qualification-v2/RESULTS_AND_STATUS.md)
records the fixed panel qualification and negative outcomes. These are artifact
measurements with no timing inheritance to the clean public binary. Confidence
intervals and general full-model/production qualification remain unmet.
Repository CI/workflow coverage is an unmet item. Tiny adapter tests, when run,
provide finite integration evidence; they are not a full-model result.

| Scoped algorithm | Synthetic config | Preparation and accepted output |
|---|---|---|
| `tp_source_domain_retained_fixed_caps_experimental_v1` | `testdata/scoped-config/tp-source-domain.json` | Explicit origin-domain retained exact-event TP, with every readiness group and lower sentinel for every declared origin, then full ordinary incidence finalization. Requires domain completion and false global completion. |
| `trex_fixed_transfer_cap_ranked_defined_probe_verified_experimental_v1` | `testdata/scoped-config/trex-fixed-cap-defined-probe.json` | Ranked T-REX customized for one exact transfer walking cap; whole-witness original-query replay and a fresh complete independent prepared raw enumeration/frontier equality gate run online. |

Both return supported **unranked 2D arrival/boarding representatives**. Neither
claims strict identity top-k, every tied itinerary or a 3D walking frontier.
They retain the original dataset/window, walking roles, resources, transfer versus
staying-aboard rules, pickup/dropoff, absorbing destination and identity bindings.
No ordinary TB or verifier output supplies a fallback result.

Use `familybench -algorithm <name> -scoped-config <path>` with the normal
source-bound build and frozen input flags. Exactly one algorithm configuration
is required. `source_domain_patterns` belongs only to the new TP name.
`trex_fixed_transfer_cap` and `verification_preparation` belong only to the new
T-REX name, which also requires `trex` and positive `verification` limits.
Old adapter names reject these new fields. The historical reproduction script
continues to exercise its original names; it does not qualify these additions.

The TP origin list is a declared construction domain, independent of individual
query departure records. Domain completion certifies that entire declared scope
on the supplied network. It does not make the legacy global TP index complete,
including when the declared domain is large. Missing origins, changed
destination/walking class or unsupported window/resources decline. Compact cost
output exposes `domain_complete`, false `global_complete` and finalization.
Partial construction cannot serve queries.

The T-REX transfer cap binds before ranked customization; every query must match
it exactly. `raw_verifier_preparation` separately records row visits, construction
work, a defined retained payload count and an ordered raw-input digest.
`certificate_preparation_ns` measures the whole certificate preparation call,
including replay-checker and raw-verifier preparation; it is not an isolated
raw-index-only timer. Row/work/payload limits must be positive. Payload units
count UTF-8 strings, integers and booleans as defined by the routing API and
exclude Go map/slice/allocator overhead. Physical live heap and peak process
memory require separate measurement.

For this new T-REX name, `verification.max_scans` bounds the separately defined
candidate-row/rule/index-lookup probe meter, including misses, plus the charged
frontier projection work. It does **not** count all physical reads. Enumeration
state and retained-journey limits remain separate. Ranked search and replay use
their own native ranked work budget. The native method/policy strings containing
`actual_probe` are opaque identifiers for that precise cost model; the name does
not establish physical-read accounting. Excluded work includes repeated
onboard/prior/lastRide raw ordinal accesses, scalar comparisons/reuse, hash-byte
processing, allocator operations and leg-copy work. Enumeration states and
retained journeys have separate bounds; copied-leg counts are exposed separately
and constrained by those state/journey and query-leg bounds rather than charged
as probes. This meter does not bound every raw-memory access or CPU instruction.

Shadow legacy scans are diagnostic only. Checked arithmetic stores the total
saturated at MaxInt64 and keeps a sticky saturation flag when the mathematical
total is strictly larger. Saturation makes WouldDecline true, including at a
MaxInt64 numerical ceiling. Exact complete legacy reporting requires the full
declared enumeration/projection scope and an unsaturated total. Partial or
saturated values are lower bounds, never exact complete legacy counts. These
units, cancellation boundaries and acceptance budgets are not equivalent to the
unchanged legacy logical full-scan control or its historical four-million limit.

Accepted output requires `Complete`, `Certificate.Accepted` and
`VerificationComplete`. Frontier mismatch is `correctness_mismatch`; exact-cap
mismatch is `unsupported_semantics`; infeasible ranked witnesses are
`unsupported_cap_certificate`; exhausted ranked/replay work is
`incomplete_ranked_work`; bounded verifier/projection exhaustion is
`incomplete_verification`. Declines clear returned journeys. Positive raw
preparation exhaustion is an expected `incomplete_budget` preparation skip;
malformed or unknown preparation failures remain fatal. All offered/not-run
slots retain the normal harness accounting.

The linked report preserves the exact instrumented campaign identities. Any further report must
bind exact source, vendor/lock, binary, protocol, roster/domain and raw-result
identities; preserve failed, declined and not-run denominators; distinguish
preparation, ranked search, certification, validation, projection and encoding;
and report the applicable sample size and interval method. Full-model agreement
between methods remains corroboration, not an independent exhaustive optimum
proof. Unofficial frequency-derived transit and approximate walking remain
model limitations.
