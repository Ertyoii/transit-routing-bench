package csa_test

import (
	"context"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"math/rand/v2"
	"reflect"
	"slices"
	"testing"
)

func topKDifferential(t testing.TB, d model.Dataset, qs []model.Query) {
	t.Helper()
	idx, e := csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	want := map[string][]model.Validated{}
	for _, q := range qs {
		o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 300000, MaxJourneys: 100000})
		if e != nil || !o.Complete {
			t.Fatalf("inconclusive oracle: %v", e)
		}
		want[q.ID] = canonical(t, d, q, o.Journeys)
	}
	for _, k := range []int{1, 3, 5, 10} {
		cfg := csa.Config{MaxLabels: 300000, MaxJourneys: 100000, ExactTopK: k}
		batch, e := idx.Shared(context.Background(), qs, cfg)
		if e != nil {
			t.Fatal(e)
		}
		for i, q := range qs {
			single, e := idx.Single(context.Background(), q, cfg)
			if e != nil {
				t.Fatal(e)
			}
			expected := want[q.ID][:min(k, len(want[q.ID]))]
			for _, r := range []csa.Result{single, batch.Results[i]} {
				if !r.TopKComplete || r.Complete || r.TopK != k || !reflect.DeepEqual(canonical(t, d, q, r.Journeys), expected) {
					t.Fatalf("k=%d query=%s: want=%+v got=%+v", k, q.ID, expected, r)
				}
			}
		}
	}
}
func TestExactTopKFixtureAndPermutation(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	topKDifferential(t, b.Dataset, b.Queries)
	slices.Reverse(b.Dataset.Connections)
	slices.Reverse(b.Queries)
	topKDifferential(t, b.Dataset, b.Queries)
}
func TestEquivalentPrefixesAndLateLexicographicReplacement(t *testing.T) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "merge", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17"}
	for _, s := range []string{"A", "B", "C", "D"} {
		d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
	}
	for _, trip := range []string{"z", "a", "m", "join"} {
		d.Trips = append(d.Trips, model.Trip{ID: trip, Accessible: model.Yes})
	}
	d.Connections = []model.Connection{{ID: "z", TripID: "z", From: "A", To: "B", Departure: 0, Arrival: 2, Pickup: true, Dropoff: true}, {ID: "a", TripID: "a", From: "A", To: "B", Departure: 1, Arrival: 2, Pickup: true, Dropoff: true}, {ID: "m", TripID: "m", From: "A", To: "B", Departure: 1, Arrival: 2, Pickup: true, Dropoff: true}, {ID: "join", TripID: "join", From: "B", To: "C", Departure: 2, Arrival: 2, Pickup: true, Dropoff: true}, {ID: "end", TripID: "join", Sequence: 1, From: "C", To: "D", Departure: 2, Arrival: 2, Pickup: true, Dropoff: true}}
	q := model.Query{ID: "q", Origin: "A", Destination: "D", Departure: 0, LatestArrival: 10, MaxBoardings: 3, MaxLegs: 5}
	topKDifferential(t, d, []model.Query{q})
	idx, _ := csa.New(d)
	r, e := idx.Single(context.Background(), q, csa.Config{MaxLabels: 100, MaxJourneys: 10, ExactTopK: 1})
	if e != nil || r.Stats.EquivalentPruned == 0 || r.Journeys[0].Legs[0].Ref != "a" {
		t.Fatalf("equivalent-prefix replacement not exercised: %+v %v", r, e)
	}
}
func TestTopKBudgetDoesNotCertifyPartialSet(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	idx, _ := csa.New(b.Dataset)
	r, e := idx.Single(context.Background(), b.Queries[0], csa.Config{MaxLabels: 1, MaxJourneys: 10, ExactTopK: 3})
	if e == nil || r.TopKComplete || r.Complete {
		t.Fatal("truncation claimed top-k guarantee")
	}
	if _, e = idx.Single(context.Background(), b.Queries[0], csa.Config{MaxLabels: 100, MaxJourneys: 10, ExactTopK: 3, HeuristicLabelsPerStop: 1}); e == nil {
		t.Fatal("heuristic cap mixed with exact contract")
	}
}
func FuzzExactTopK(f *testing.F) {
	f.Add(uint64(1))
	f.Add(uint64(20261017))
	f.Fuzz(func(t *testing.T, seed uint64) {
		rng := rand.New(rand.NewPCG(seed, seed+19))
		d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "generated", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17"}
		stops := []string{"A", "B", "C"}
		for _, s := range stops {
			d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
		}
		for i := 0; i < 6; i++ {
			id := string(rune('a' + i))
			dep := int64(rng.IntN(8))
			d.Trips = append(d.Trips, model.Trip{ID: id, Accessible: model.Yes})
			d.Connections = append(d.Connections, model.Connection{ID: id, TripID: id, From: stops[rng.IntN(3)], To: stops[rng.IntN(3)], Departure: dep, Arrival: dep + int64(rng.IntN(3)), Pickup: rng.IntN(4) != 0, Dropoff: rng.IntN(4) != 0})
		}
		d.Footpaths = []model.Footpath{{ID: "w", From: stops[rng.IntN(3)], To: stops[rng.IntN(3)], Duration: 1, Accessible: model.Yes}}
		q := model.Query{ID: "q", Origin: "A", Destination: "C", Departure: 0, LatestArrival: 12, MaxBoardings: 3, MaxLegs: 5, MaxWalkSeconds: 3, TransferBuffer: int64(rng.IntN(3))}
		topKDifferential(t, d, []model.Query{q})
	})
}
