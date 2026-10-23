package comparison_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/comparison"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"reflect"
	"slices"
	"sort"
	"testing"
)

func rankedUniverse(t testing.TB, d model.Dataset, q model.Query, penalty int64) []model.Validated {
	t.Helper()
	o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 300000, MaxJourneys: 100000})
	if e != nil || !o.Complete {
		t.Fatal("oracle truncated", e)
	}
	checker, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	vs := []model.Validated{}
	for _, j := range o.Journeys {
		v, e := checker.Check(q, j)
		if e != nil {
			t.Fatal(e)
		}
		vs = append(vs, v)
	}
	sort.Slice(vs, func(i, j int) bool {
		a, b := vs[i], vs[j]
		aa, bb := a.Metrics, b.Metrics
		av := []int64{aa.Arrival - q.Departure + int64(aa.Transfers)*penalty, aa.Arrival, int64(aa.Transfers), aa.WalkingSeconds, int64(aa.LegCount)}
		bv := []int64{bb.Arrival - q.Departure + int64(bb.Transfers)*penalty, bb.Arrival, int64(bb.Transfers), bb.WalkingSeconds, int64(bb.LegCount)}
		for n := range av {
			if av[n] != bv[n] {
				return av[n] < bv[n]
			}
		}
		return a.Identity < b.Identity
	})
	return vs
}
func rankedCheck(t testing.TB, d model.Dataset, qs []model.Query) {
	t.Helper()
	idx, e := csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	checker, _ := validate.New(d)
	for _, penalty := range []int64{0, 1, 300, 600} {
		for _, k := range []int{1, 3, 5, 10} {
			cfg := csa.Config{ExactTopK: k, MaxLabels: 300000, MaxJourneys: 100000}
			b, e := idx.StratifiedShared(context.Background(), qs, cfg)
			if e != nil {
				t.Fatal(e)
			}
			for i, q := range qs {
				universe := rankedUniverse(t, d, q, penalty)
				want := universe[:min(k, len(universe))]
				single, e := idx.StratifiedSingle(context.Background(), q, cfg)
				if e != nil {
					t.Fatal(e)
				}
				for _, r := range []csa.Result{single, b.Results[i]} {
					got, e := comparison.RankCaps(checker, q, r, k, penalty)
					if e != nil {
						t.Fatal(e)
					}
					actual := []model.Validated{}
					for _, o := range got.Ranked.Options {
						actual = append(actual, o.Journey)
					}
					if !got.StrictComplete || !got.Ranked.GlobalOptimalityClaim || !reflect.DeepEqual(actual, want) {
						t.Fatalf("k%d penalty%d q%s differs", k, penalty, q.ID)
					}
				}
			}
		}
	}
}
func TestRankedCapsAllTinyFixtures(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	rankedCheck(t, b.Dataset, b.Queries)
	slices.Reverse(b.Dataset.Connections)
	slices.Reverse(b.Queries)
	rankedCheck(t, b.Dataset, b.Queries)
}
func generated(seed uint64) (model.Dataset, []model.Query) {
	rng := rand.New(rand.NewPCG(seed, seed+29))
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "ranked-generated", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-12"}
	stops := []string{"A", "B", "C"}
	for _, s := range stops {
		d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
	}
	for i := 0; i < 6; i++ {
		id := fmt.Sprintf("t%d", i)
		from := rng.IntN(3)
		to := (from + 1 + rng.IntN(2)) % 3
		dep := int64(rng.IntN(10))
		d.Trips = append(d.Trips, model.Trip{ID: id, Accessible: model.Yes})
		d.Connections = append(d.Connections, model.Connection{ID: id, TripID: id, From: stops[from], To: stops[to], Departure: dep, Arrival: dep + int64(rng.IntN(4)), Pickup: true, Dropoff: true})
	}
	d.Footpaths = []model.Footpath{{ID: "walk", From: "A", To: "B", Duration: 1, Accessible: model.Yes}}
	qs := []model.Query{}
	for i, o := range stops {
		q := model.Query{ID: fmt.Sprint(i), Origin: o, Destination: "C", Departure: 0, LatestArrival: 15, MaxBoardings: 3, MaxLegs: 5, MaxWalkSeconds: 10, Walking: &model.WalkingLimits{Access: 600, Egress: 600, Transfer: 2, Direct: 600}}
		qs = append(qs, q)
	}
	return d, qs
}
func TestRankedCapsSeededUniverses(t *testing.T) {
	for seed := uint64(93001); seed < 93065; seed++ {
		d, q := generated(seed)
		rankedCheck(t, d, q)
	}
}
func FuzzRankedCaps(f *testing.F) {
	f.Add(uint64(93001))
	f.Add(uint64(93042))
	f.Fuzz(func(t *testing.T, seed uint64) { d, q := generated(seed); rankedCheck(t, d, q) })
}
func TestRankedCapsNoCertificateAfterTruncationOrMissingCap(t *testing.T) {
	b, _, _ := fixtures.Load("../../testdata/tiny.manifest.json")
	q := b.Queries[0]
	idx, _ := csa.New(b.Dataset)
	checker, _ := validate.New(b.Dataset)
	r, _ := idx.StratifiedSingle(context.Background(), q, csa.Config{ExactTopK: 3, MaxLabels: 1, MaxJourneys: 10})
	out, e := comparison.RankCaps(checker, q, r, 3, 300)
	if e != nil || out.StrictComplete || out.Ranked.GlobalOptimalityClaim {
		t.Fatal(out, e)
	}
	r, _ = idx.StratifiedSingle(context.Background(), q, csa.Config{ExactTopK: 3, MaxLabels: 300000, MaxJourneys: 100000})
	r.CapResults = r.CapResults[:len(r.CapResults)-1]
	if _, e = comparison.RankCaps(checker, q, r, 3, 300); e == nil {
		t.Fatal("missing cap certified")
	}
}
