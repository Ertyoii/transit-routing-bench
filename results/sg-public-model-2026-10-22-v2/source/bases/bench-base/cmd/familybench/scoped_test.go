package main

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"sort"
	"sync"
	"testing"

	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"github.com/ertyoii/transit-routing-go/validate"
)

func scopedFixture(t *testing.T) fixtures.Bundle {
	t.Helper()
	b, _, err := fixtures.Load("../../testdata/scoped.manifest.json")
	if err != nil {
		t.Fatal(err)
	}
	return b
}
func scopedInput(t *testing.T, name string) scopedConfig {
	t.Helper()
	b, err := os.ReadFile("../../testdata/scoped-config/" + name + ".json")
	if err != nil {
		t.Fatal(err)
	}
	var c scopedConfig
	if err := strictjson.Decode(b, &c); err != nil {
		t.Fatal(err)
	}
	return c
}
func bestArrival(t *testing.T, d model.Dataset, q model.Query, raw []model.Journey) int64 {
	t.Helper()
	checker, err := validate.New(d)
	if err != nil {
		t.Fatal(err)
	}
	best := int64(-1)
	for _, j := range raw {
		v, err := checker.Check(q, j)
		if err != nil {
			t.Fatalf("invalid complete itinerary: %v", err)
		}
		if best < 0 || v.Metrics.Arrival < best {
			best = v.Metrics.Arrival
		}
	}
	return best
}

// Protects adapter dispatch/cap preservation through the actual public kernels.
// Switching capped TB to legacy Search, dropping the walking class, or marking
// an unsupported result complete cannot satisfy the literal finite answers.
func TestScopedAdaptersLiteralCapsAndValidEmpty(t *testing.T) {
	b := scopedFixture(t)
	cases := []struct{ name, config string }{
		{"trip_based_capped", "tb"},
		{"ultra_transfer_complete_capped", "ultra-control"},
		{"ultra_cap_safe_stay_witness_subset_v1", "ultra-subset"},
		{"flash_tb_static_stop_pair_suffix_flags_role_caps_v1", "flash"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r, err := prepareScoped(context.Background(), b.Dataset, tc.name, scopedInput(t, tc.config))
			if err != nil {
				t.Fatal(err)
			}
			for i, q := range b.Queries {
				v := r.single(context.Background(), q)
				if v.Err != nil || !v.Complete {
					t.Fatalf("%s: complete=%v error=%v", q.ID, v.Complete, v.Err)
				}
				if got, want := bestArrival(t, b.Dataset, q, v.Journeys), []int64{30, 20, -1}[i]; got != want {
					t.Fatalf("%s: arrival=%d want=%d", q.ID, got, want)
				}
			}
		})
	}
	for _, name := range []string{"raptor_early", "mc_raptor_early"} {
		r, err := prepare(context.Background(), b.Dataset, name, 10, 10000, 10000, 1000000, 10000)
		if err != nil {
			t.Fatal(err)
		}
		for i, q := range b.Queries {
			v := r.single(context.Background(), q)
			if v.Err != nil || !v.Complete {
				t.Fatalf("%s/%s: %v", name, q.ID, v.Err)
			}
			if got, want := bestArrival(t, b.Dataset, q, v.Journeys), []int64{30, 20, -1}[i]; got != want {
				t.Fatalf("%s: %d != %d", name, got, want)
			}
		}
	}
}

// A rejected unrestricted representative does not imply no feasible capped
// route. The independent exhaustive tiny oracle retains the later arrival.
func TestTREXCapHiddenAlternativeAndMandatoryVerification(t *testing.T) {
	b := scopedFixture(t)
	name := "trex_static_caps_mandatory_verified_experimental"
	cfg := scopedInput(t, "trex")
	r, err := prepareScoped(context.Background(), b.Dataset, name, cfg)
	if err != nil {
		t.Fatal(err)
	}
	narrow := r.single(context.Background(), b.Queries[0])
	if narrow.Complete || status(narrow.Err) != "unsupported_cap_certificate" || len(narrow.Journeys) != 0 {
		t.Fatalf("cap decline: %+v", narrow)
	}
	ref, err := oracle.Enumerate(context.Background(), b.Dataset, b.Queries[0], oracle.Limits{MaxStates: 10000, MaxJourneys: 10000})
	if err != nil || !ref.Complete {
		t.Fatalf("oracle incomplete: %v", err)
	}
	if got := bestArrival(t, b.Dataset, b.Queries[0], ref.Journeys); got != 30 {
		t.Fatalf("hidden feasible arrival=%d", got)
	}
	broad := r.single(context.Background(), b.Queries[1])
	if broad.Err != nil || !broad.Complete || bestArrival(t, b.Dataset, b.Queries[1], broad.Journeys) != 20 {
		t.Fatalf("broad query: %+v", broad)
	}
	detail, ok := broad.Detail.(tripbased.TREXStaticCapResult)
	if !ok || !detail.VerificationComplete || !detail.Certificate.Accepted {
		t.Fatalf("mandatory gate absent: %+v", broad.Detail)
	}
	empty := r.single(context.Background(), b.Queries[2])
	if empty.Err != nil || !empty.Complete || len(empty.Journeys) != 0 {
		t.Fatalf("valid empty: %+v", empty)
	}

	for _, tc := range []struct {
		name, want string
		configure  func(*scopedConfig)
	}{
		{"ranked-budget", "incomplete_ranked_work", func(c *scopedConfig) { c.TREX.Limits.MaxQueryWork = 1 }},
		{"verifier-budget", "incomplete_verification", func(c *scopedConfig) { c.Verify.MaxScans = 1 }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := scopedInput(t, "trex")
			tc.configure(&c)
			x, err := prepareScoped(context.Background(), b.Dataset, name, c)
			if err != nil {
				t.Fatal(err)
			}
			v := x.single(context.Background(), b.Queries[1])
			if v.Complete || len(v.Journeys) != 0 || status(v.Err) != tc.want {
				t.Fatalf("budget outcome: %+v status=%s", v, status(v.Err))
			}
		})
	}
	cfg = scopedInput(t, "trex")
	cfg.Verify = nil
	if _, err = prepareScoped(context.Background(), b.Dataset, name, cfg); err == nil {
		t.Fatal("missing mandatory verification accepted")
	}
}

// The adapter must not turn a useful partial pattern prefix into a usable index.
// A complete tiny scope answers only its exact destination/walking class.
func TestFixedCapTPPartialAndScope(t *testing.T) {
	b := scopedFixture(t)
	name := "tp_destination_fixed_caps_experimental"
	r, err := prepareScoped(context.Background(), b.Dataset, name, scopedInput(t, "tp-partial"))
	if err == nil || status(err) != "incomplete_budget" || r.single != nil {
		t.Fatalf("partial preparation: %v", err)
	}
	if r.cost == nil {
		t.Fatal("partial preparation diagnostics lost")
	}
	data, err := json.Marshal(r.cost())
	if err != nil {
		t.Fatal(err)
	}
	var diag struct {
		Complete bool `json:"complete"`
		Stats    struct {
			SourcesCompleted int `json:"sources_completed"`
		} `json:"stats"`
	}
	if err = json.Unmarshal(data, &diag); err != nil {
		t.Fatal(err)
	}
	if diag.Complete || diag.Stats.SourcesCompleted != 1 {
		t.Fatalf("unexpected partial boundary: %s", data)
	}
	r, err = prepareScoped(context.Background(), b.Dataset, name, scopedInput(t, "tp"))
	if err != nil {
		t.Fatal(err)
	}
	v := r.single(context.Background(), b.Queries[0])
	if v.Err != nil || !v.Complete || bestArrival(t, b.Dataset, b.Queries[0], v.Journeys) != 30 {
		t.Fatalf("fixed class: %+v", v)
	}
	v = r.single(context.Background(), b.Queries[1])
	if v.Complete || status(v.Err) != "unsupported_semantics" {
		t.Fatalf("scope changed: %+v", v)
	}
}

// Same public adapter instances serve different query orders concurrently.
// Compare owned raw journeys, not timing or implementation counters.
func TestScopedOrderAndConcurrentReuse(t *testing.T) {
	b := scopedFixture(t)
	for _, tc := range []struct{ name, config string }{
		{"trip_based_capped", "tb"}, {"ultra_transfer_complete_capped", "ultra-control"},
		{"ultra_cap_safe_stay_witness_subset_v1", "ultra-subset"},
		{"flash_tb_static_stop_pair_suffix_flags_role_caps_v1", "flash"},
		{"trex_static_caps_mandatory_verified_experimental", "trex"},
	} {
		r, err := prepareScoped(context.Background(), b.Dataset, tc.name, scopedInput(t, tc.config))
		if err != nil {
			t.Fatal(err)
		}
		encode := func(q model.Query) string {
			v := r.single(context.Background(), q)
			js := make([]string, 0, len(v.Journeys))
			for _, j := range v.Journeys {
				b, _ := json.Marshal(j)
				js = append(js, string(b))
			}
			sort.Strings(js)
			value, _ := json.Marshal([]any{v.Complete, status(v.Err), js})
			return string(value)
		}
		want := make([]string, len(b.Queries))
		for i, q := range b.Queries {
			want[i] = encode(q)
		}
		got := make([]string, len(want))
		var wg sync.WaitGroup
		for i := len(got) - 1; i >= 0; i-- {
			wg.Add(1)
			go func(i int) { defer wg.Done(); got[i] = encode(b.Queries[i]) }(i)
		}
		wg.Wait()
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("%s changed across order/concurrency", tc.name)
		}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		v := r.single(ctx, b.Queries[0])
		if v.Complete || status(v.Err) != "deadline" {
			t.Fatalf("%s ignored cancellation: %+v", tc.name, v)
		}
	}
}
