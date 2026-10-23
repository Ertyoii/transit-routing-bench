package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/ertyoii/transit-routing-go/tripbased"
)

// The published fixture/config helpers keep these tests at adapter dispatch,
// not a mock status helper. A silently ignored new field or masked malformed
// budget would change which experiment was actually performed.
func TestQualificationV2ConfigurationIsolation(t *testing.T) {
	b := scopedFixture(t)
	for _, name := range []string{tpSourceDomainName, trexDefinedProbeName} {
		if !isScoped(name) {
			t.Fatalf("CLI cannot dispatch scoped adapter %s", name)
		}
	}
	for _, tc := range []struct {
		name, adapter, config, cause string
		change                       func(*scopedConfig)
	}{
		{"domain-under-old-name", "tp_destination_fixed_caps_experimental", "tp-source-domain", "source_domain_patterns requires", nil},
		{"fixed-cap-under-old-name", "trex_static_caps_mandatory_verified_experimental", "trex-fixed-cap-defined-probe", "require " + trexDefinedProbeName, nil},
		{"unused-raw-preparation", "trex_static_caps_mandatory_verified_experimental", "trex", "require " + trexDefinedProbeName, func(c *scopedConfig) {
			c.VerifyPreparation = scopedInput(t, "trex-fixed-cap-defined-probe").VerifyPreparation
		}},
		{"missing-domain", tpSourceDomainName, "tp", "source_domain_patterns configuration required", nil},
		{"missing-fixed-cap", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "configurations required", func(c *scopedConfig) { c.TFixedTransferCap = nil }},
		{"missing-verifier", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "configurations required", func(c *scopedConfig) { c.Verify = nil }},
		{"missing-verifier-preparation", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "configurations required", func(c *scopedConfig) { c.VerifyPreparation = nil }},
		{"two-algorithms", tpSourceDomainName, "tp-source-domain", "exactly one algorithm", func(c *scopedConfig) { c.TripBased = scopedInput(t, "tb").TripBased }},
		{"negative-fixed-cap", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "nonnegative", func(c *scopedConfig) { *c.TFixedTransferCap = -1 }},
		{"masked-retained-budget", tpSourceDomainName, "tp-source-domain", "positive retained", func(c *scopedConfig) {
			c.SourceDomainPatterns.Retained.Scope.Patterns.Profile.Limits.MaxStops = 1
			c.SourceDomainPatterns.Retained.MaxSourceSeeds = 0
		}},
		{"masked-raw-rows", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "positive raw verifier", func(c *scopedConfig) {
			c.TREX.Limits.MaxStops = 1
			c.VerifyPreparation.MaxRows = 0
		}},
		{"masked-raw-work", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "positive raw verifier", func(c *scopedConfig) {
			c.TREX.Limits.MaxStops = 1
			c.VerifyPreparation.MaxWork = 0
		}},
		{"masked-raw-payload", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "positive raw verifier", func(c *scopedConfig) {
			c.TREX.Limits.MaxStops = 1
			c.VerifyPreparation.MaxPayloadBytes = 0
		}},
		{"masked-query-verification", trexDefinedProbeName, "trex-fixed-cap-defined-probe", "positive verification", func(c *scopedConfig) {
			c.TREX.Limits.MaxStops = 1
			c.Verify.MaxScans = 0
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := scopedInput(t, tc.config)
			if tc.change != nil {
				tc.change(&c)
			}
			r, err := prepareScoped(context.Background(), b.Dataset, tc.adapter, c)
			if err == nil || r.single != nil || !strings.Contains(err.Error(), tc.cause) {
				t.Fatalf("configuration was not rejected at preparation: %v", err)
			}
			if _, fatal := preparationOutcome(err); !fatal {
				t.Fatalf("malformed configuration became an expected skip: %v", err)
			}
		})
	}
}

// Source-domain completion permits only the declared origins and exact class;
// flipping a legacy Complete bit or dispatching to global TP fails this flow.
func TestQualificationV2SourceDomainPublicFlow(t *testing.T) {
	b := scopedFixture(t)
	r, err := prepareScoped(context.Background(), b.Dataset, tpSourceDomainName, scopedInput(t, "tp-source-domain"))
	if err != nil {
		t.Fatal(err)
	}
	data, err := json.Marshal(r.cost())
	if err != nil {
		t.Fatal(err)
	}
	var cost struct {
		Domain struct {
			DomainComplete       bool `json:"domain_complete"`
			GlobalComplete       bool `json:"global_complete"`
			InnerGlobalComplete  bool `json:"inner_global_complete"`
			FinalizationComplete bool `json:"finalization_complete"`
		} `json:"domain"`
	}
	if err := json.Unmarshal(data, &cost); err != nil || !cost.Domain.DomainComplete || cost.Domain.GlobalComplete || cost.Domain.InnerGlobalComplete || !cost.Domain.FinalizationComplete {
		t.Fatalf("completion scope lost: %s (%v)", data, err)
	}
	for _, i := range []int{0, 2} {
		q := b.Queries[i]
		v := r.single(context.Background(), q)
		want := int64(30)
		if i == 2 {
			want = -1
		}
		if v.Err != nil || !v.Complete || bestArrival(t, b.Dataset, q, v.Journeys) != want {
			t.Fatalf("domain query %s: %+v", q.ID, v)
		}
	}
	for _, q := range []struct {
		origin string
		broad  bool
	}{{"A", false}, {"O", true}} {
		query := b.Queries[0]
		query.Origin = q.origin
		if q.broad {
			query = b.Queries[1]
		}
		v := r.single(context.Background(), query)
		if v.Complete || len(v.Journeys) != 0 || status(v.Err) != "unsupported_semantics" {
			t.Fatalf("query escaped domain/class: %+v", v)
		}
	}
	c := scopedInput(t, "tp-source-domain")
	c.SourceDomainPatterns.Retained.Scope.Patterns.MaxDirectEntries = 1
	r, err = prepareScoped(context.Background(), b.Dataset, tpSourceDomainName, c)
	if err == nil || r.single != nil || r.cost == nil || status(err) != "incomplete_budget" {
		t.Fatalf("partial domain acquired serving: %v", err)
	}
}

// These are literal answers on the original CC0 fixture. Every raw answer is
// independently replayed by bestArrival; the verifier never supplies journeys.
func TestQualificationV2FixedCapPublicFlow(t *testing.T) {
	b := scopedFixture(t)
	r, err := prepareScoped(context.Background(), b.Dataset, trexDefinedProbeName, scopedInput(t, "trex-fixed-cap-defined-probe"))
	if err != nil {
		t.Fatal(err)
	}
	for i, q := range b.Queries {
		v := r.single(context.Background(), q)
		if v.Err != nil || !v.Complete || bestArrival(t, b.Dataset, q, v.Journeys) != []int64{30, 20, -1}[i] {
			t.Fatalf("ranked/certificate query %s: %+v", q.ID, v)
		}
		detail, ok := v.Detail.(tripbased.TREXFixedTransferCapCandidateResult)
		if !ok || !detail.Certificate.Accepted || !detail.VerificationComplete || detail.Certificate.Method != tripbased.TREXFixedTransferCapCandidateMethod || detail.Certificate.FixedTransferWalkingCap != 10 {
			t.Fatalf("new mandatory certificate absent: %+v", v.Detail)
		}
	}
	data, err := json.Marshal(r.cost())
	if err != nil {
		t.Fatal(err)
	}
	var cost struct {
		Ranked              json.RawMessage `json:"ranked_index"`
		CertificatePrepared bool            `json:"certificate_prepared"`
		RawPreparation      struct {
			OrderedSHA256 string `json:"ordered_sha256"`
		} `json:"raw_verifier_preparation"`
	}
	if err := json.Unmarshal(data, &cost); err != nil || !cost.CertificatePrepared || cost.RawPreparation.OrderedSHA256 == "" || len(cost.Ranked) == 0 || string(cost.Ranked) == "null" {
		t.Fatalf("separate preparation evidence lost: %s (%v)", data, err)
	}
	q := b.Queries[1]
	walking := *q.Walking
	walking.Transfer++
	q.Walking = &walking
	v := r.single(context.Background(), q)
	if v.Complete || len(v.Journeys) != 0 || status(v.Err) != "unsupported_semantics" {
		t.Fatalf("fixed cap mismatch was not declined: %+v", v)
	}
}

// A real ranked answer exists, but either side's exhausted budget must clear
// it. This catches accidental TB/verifier fallback and a missing online gate.
func TestQualificationV2FixedCapDeclines(t *testing.T) {
	b := scopedFixture(t)
	for _, tc := range []struct {
		name, want string
		change     func(*scopedConfig)
	}{
		{"ranked-work", "incomplete_ranked_work", func(c *scopedConfig) { c.TREX.Limits.MaxQueryWork = 1 }},
		{"verifier-probes", "incomplete_verification", func(c *scopedConfig) { c.Verify.MaxScans = 1 }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := scopedInput(t, "trex-fixed-cap-defined-probe")
			tc.change(&c)
			r, err := prepareScoped(context.Background(), b.Dataset, trexDefinedProbeName, c)
			if err != nil {
				t.Fatal(err)
			}
			v := r.single(context.Background(), b.Queries[1])
			if v.Complete || len(v.Journeys) != 0 || status(v.Err) != tc.want {
				t.Fatalf("decline outcome %s: %+v", status(v.Err), v)
			}
		})
	}
	c := scopedInput(t, "trex-fixed-cap-defined-probe")
	c.VerifyPreparation.MaxRows = 1
	r, err := prepareScoped(context.Background(), b.Dataset, trexDefinedProbeName, c)
	if err == nil || r.single != nil || r.cost == nil {
		t.Fatalf("incomplete raw preparation acquired serving: %v", err)
	}
	if got, fatal := preparationOutcome(err); got != "incomplete_budget" || fatal {
		t.Fatalf("positive preparation exhaustion misclassified: %s fatal=%v (%v)", got, fatal, err)
	}
}
