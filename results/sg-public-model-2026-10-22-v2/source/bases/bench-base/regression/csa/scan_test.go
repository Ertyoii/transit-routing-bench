package csa_test

import (
	"context"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/selection"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"reflect"
	"slices"
	"sync"
	"testing"
)

var cfg = csa.Config{MaxLabels: 200000, MaxJourneys: 100000}

func canonical(t testing.TB, d model.Dataset, q model.Query, js []model.Journey) []model.Validated {
	t.Helper()
	checker, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	vs := []model.Validated{}
	for _, j := range js {
		v, e := checker.Check(q, j)
		if e != nil {
			t.Fatalf("invalid witness %s: %+v: %v", q.ID, j, e)
		}
		vs = append(vs, v)
	}
	slices.SortFunc(vs, selection.Compare)
	for i := 1; i < len(vs); i++ {
		if vs[i-1].Identity == vs[i].Identity {
			t.Fatal("duplicate identity")
		}
	}
	return vs
}
func differential(t testing.TB, d model.Dataset, qs []model.Query) {
	t.Helper()
	idx, e := csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	batch, e := idx.Shared(context.Background(), qs, cfg)
	if e != nil {
		t.Fatal(e)
	}
	for i, q := range qs {
		exhaustive, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 200000, MaxJourneys: 100000})
		if e != nil {
			t.Fatal(e)
		}
		want := canonical(t, d, q, exhaustive.Journeys)
		single, e := idx.Single(context.Background(), q, cfg)
		if e != nil {
			t.Fatal(e)
		}
		for _, got := range []csa.Result{single, batch.Results[i]} {
			if !got.Complete || !reflect.DeepEqual(canonical(t, d, q, got.Journeys), want) {
				t.Fatalf("query %s mismatch; want=%+v got=%+v", q.ID, want, got)
			}
		}
	}
}
func TestFixtureDifferential(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	differential(t, b.Dataset, b.Queries)
}
func walkFixture() (model.Dataset, model.Query) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "walk-phases", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17"}
	for _, id := range []string{"A", "B", "C", "D", "E", "F"} {
		d.Stops = append(d.Stops, model.Stop{ID: id, Accessible: model.Yes})
	}
	d.Trips = []model.Trip{{ID: "one", RouteID: "R1", Accessible: model.Yes}, {ID: "two", RouteID: "R2", Accessible: model.Yes}}
	d.Connections = []model.Connection{{ID: "one", TripID: "one", From: "B", To: "C", Departure: 700, Arrival: 800, Pickup: true, Dropoff: true}, {ID: "two", TripID: "two", From: "D", To: "E", Departure: 1500, Arrival: 1600, Pickup: true, Dropoff: true}}
	d.Footpaths = []model.Footpath{{ID: "access", From: "A", To: "B", Duration: 600, Accessible: model.Yes}, {ID: "transfer", From: "C", To: "D", Duration: 601, Accessible: model.Yes}, {ID: "egress", From: "E", To: "F", Duration: 600, Accessible: model.Yes}}
	q := model.Query{ID: "q", Origin: "A", Destination: "F", Departure: 0, LatestArrival: 2300, MaxWalkSeconds: 2000, MaxBoardings: 2, MaxLegs: 5, Walking: &model.WalkingLimits{Access: 600, Egress: 600, Transfer: 900, Direct: 600}}
	return d, q
}
func TestWalkingPhasesAndProhibitedTransferSurviveSyntheticEdges(t *testing.T) {
	d, q := walkFixture()
	differential(t, d, []model.Query{q})
	idx, e := csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := idx.Single(context.Background(), q, cfg)
	if e != nil || len(r.Journeys) != 1 {
		t.Fatalf("separate 600-second access/egress should permit 601 intermediate seconds: %v", e)
	}
	v := canonical(t, d, q, r.Journeys)[0]
	if v.Metrics.AccessWalking != 600 || v.Metrics.EgressWalking != 600 || v.Metrics.TransferWalking != 601 || v.Metrics.Arrival != 2200 {
		t.Fatalf("phase metrics wrong: %+v", v.Metrics)
	}
	for _, phase := range []string{"access", "egress", "transfer"} {
		changed := q
		w := *q.Walking
		changed.Walking = &w
		switch phase {
		case "access":
			w.Access = 599
		case "egress":
			w.Egress = 599
		case "transfer":
			w.Transfer = 600
		}
		differential(t, d, []model.Query{changed})
		r, e := idx.Single(context.Background(), changed, cfg)
		if e != nil || len(r.Journeys) != 0 {
			t.Fatalf("%s cap ignored", phase)
		}
	}
	d.Transfers = []model.TransferRule{{ID: "forbid", FromStop: "C", ToStop: "D", Type: 3}}
	differential(t, d, []model.Query{q})
	idx, e = csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e = idx.Single(context.Background(), q, cfg)
	if e != nil || len(r.Journeys) != 0 {
		t.Fatal("synthetic walking erased prohibition")
	}
	d.Transfers = append(d.Transfers, model.TransferRule{ID: "exception", FromStop: "C", ToStop: "D", FromTrip: "one", ToTrip: "two", Type: 2, MinSeconds: 700})
	differential(t, d, []model.Query{q})
	idx, e = csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e = idx.Single(context.Background(), q, cfg)
	if e != nil || len(r.Journeys) != 1 {
		t.Fatal("specific exception or inclusive deadline wrong")
	}
	d.Transfers[1].MinSeconds = 701
	differential(t, d, []model.Query{q})
	idx, e = csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e = idx.Single(context.Background(), q, cfg)
	if e != nil || len(r.Journeys) != 0 {
		t.Fatal("missed minimum accepted")
	}
}
func TestEqualDepartureClosureAndOvertaking(t *testing.T) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "ties", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17", Stops: []model.Stop{{ID: "A", Accessible: model.Yes}, {ID: "B", Accessible: model.Yes}, {ID: "D", Accessible: model.Yes}}, Trips: []model.Trip{{ID: "first", Accessible: model.Yes}, {ID: "second", Accessible: model.Yes}, {ID: "slow", Accessible: model.Yes}, {ID: "fast", Accessible: model.Yes}}, Connections: []model.Connection{
		{ID: "z-first", TripID: "first", From: "A", To: "B", Departure: 5, Arrival: 5, Pickup: true, Dropoff: true},
		{ID: "a-second", TripID: "second", From: "B", To: "D", Departure: 5, Arrival: 5, Pickup: true, Dropoff: true},
		{ID: "slow", TripID: "slow", From: "A", To: "D", Departure: 1, Arrival: 20, Pickup: true, Dropoff: true},
		{ID: "fast", TripID: "fast", From: "A", To: "D", Departure: 2, Arrival: 10, Pickup: true, Dropoff: true},
	}}
	q := model.Query{ID: "q", Origin: "A", Destination: "D", Departure: 0, LatestArrival: 30, MaxBoardings: 3, MaxLegs: 3}
	differential(t, d, []model.Query{q})
	idx, e := csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := idx.Single(context.Background(), q, cfg)
	if e != nil {
		t.Fatal(e)
	}
	js := canonical(t, d, q, r.Journeys)
	if len(js) != 3 || js[0].Metrics.Arrival != 5 || js[1].Metrics.Arrival != 10 || js[2].Metrics.Arrival != 20 {
		t.Fatalf("time ties/overtaking lost: %+v", js)
	}
}
func TestBatchOrderSizeDuplicatesAndConcurrentIndex(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	idx, e := csa.New(b.Dataset)
	if e != nil {
		t.Fatal(e)
	}
	qs := append([]model.Query{}, b.Queries...)
	duplicate := qs[0]
	duplicate.ID = "same-query-new-request"
	qs = append(qs, duplicate)
	want := map[string][]model.Validated{}
	for _, q := range qs {
		r, e := idx.Single(context.Background(), q, cfg)
		if e != nil {
			t.Fatal(e)
		}
		want[q.ID] = canonical(t, b.Dataset, q, r.Journeys)
	}
	slices.Reverse(qs)
	for _, size := range []int{1, 2, 3, 6} {
		for start := 0; start < len(qs); start += size {
			end := min(start+size, len(qs))
			batch, e := idx.Shared(context.Background(), qs[start:end], cfg)
			if e != nil {
				t.Fatal(e)
			}
			for i, r := range batch.Results {
				if !reflect.DeepEqual(canonical(t, b.Dataset, qs[start+i], r.Journeys), want[r.QueryID]) {
					t.Fatalf("batch size %d query %s differs", size, r.QueryID)
				}
			}
		}
	}
	if _, e = idx.Shared(context.Background(), []model.Query{qs[0], qs[0]}, cfg); e == nil {
		t.Fatal("duplicate request ID accepted")
	}
	// Concurrent read-only users of the same prepared index; failures use Error, not Fatal in workers.
	var wg sync.WaitGroup
	for range 4 {
		wg.Go(func() {
			r, e := idx.Shared(context.Background(), qs, cfg)
			if e != nil || len(r.Results) != len(qs) {
				t.Errorf("concurrent scan failed: %v", e)
			}
		})
	}
	wg.Wait()
	// The index owns a snapshot: modifying the caller's original data cannot affect it.
	b.Dataset.Connections[0].Arrival = 100000
	r, e := idx.Shared(context.Background(), qs, cfg)
	if e != nil || !r.Results[0].Complete {
		t.Fatal("caller mutated prepared snapshot")
	}
}
func TestBudgetAndHeuristicStatusNeverClaimExact(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	idx, e := csa.New(b.Dataset)
	if e != nil {
		t.Fatal(e)
	}
	limited := cfg
	limited.MaxLabels = 1
	r, e := idx.Single(context.Background(), b.Queries[0], limited)
	if e == nil || r.Complete || r.Error == "" {
		t.Fatal("budget truncation hidden")
	}
	heuristic := cfg
	heuristic.HeuristicLabelsPerStop = 1
	d, q := walkFixture()
	d.Footpaths = append(d.Footpaths, model.Footpath{ID: "alternate-access", From: "A", To: "B", Duration: 500, Accessible: model.Yes})
	idx, e = csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e = idx.Single(context.Background(), q, heuristic)
	if e != nil || r.Complete || r.Stats.HeuristicDiscarded == 0 {
		t.Fatal("heuristic cap claimed completeness")
	}
}
func TestSeededTinyDifferential(t *testing.T) {
	const seed = 20261017
	rng := rand.New(rand.NewPCG(seed, 42))
	for n := 0; n < 250; n++ {
		d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "generated", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17", Stops: []model.Stop{{ID: "A", Accessible: model.Yes}, {ID: "B", Accessible: model.Yes}, {ID: "C", Accessible: model.Yes}}}
		stops := []string{"A", "B", "C"}
		for i := 0; i < 5; i++ {
			id := string(rune('a' + i))
			dep := int64(rng.IntN(10))
			d.Trips = append(d.Trips, model.Trip{ID: id, RouteID: id, Accessible: model.Yes})
			d.Connections = append(d.Connections, model.Connection{ID: id, TripID: id, From: stops[rng.IntN(3)], To: stops[rng.IntN(3)], Departure: dep, Arrival: dep + int64(rng.IntN(4)), Pickup: rng.IntN(4) != 0, Dropoff: rng.IntN(4) != 0})
		}
		for i := 0; i < 2; i++ {
			d.Footpaths = append(d.Footpaths, model.Footpath{ID: string(rune('w' + i)), From: stops[rng.IntN(3)], To: stops[rng.IntN(3)], Duration: 1 + int64(rng.IntN(3)), Accessible: model.Yes})
		}
		q := model.Query{ID: "generated", Origin: "A", Destination: "C", Departure: 0, LatestArrival: 15, MaxWalkSeconds: 8, MaxBoardings: 4, MaxLegs: 4, TransferBuffer: int64(rng.IntN(3)), Walking: &model.WalkingLimits{Access: 4, Egress: 3, Transfer: 5, Direct: 5}}
		if n%2 == 0 {
			d.Transfers = []model.TransferRule{{ID: "rule", FromStop: stops[rng.IntN(3)], ToStop: stops[rng.IntN(3)], Type: 3}}
		}
		t.Run(string(rune(0x100+n)), func(t *testing.T) { differential(t, d, []model.Query{q}) })
	}
}
func FuzzCSADifferential(f *testing.F) {
	f.Add(uint64(1))
	f.Add(uint64(20261017))
	f.Add(uint64(0))
	f.Fuzz(func(t *testing.T, seed uint64) {
		rng := rand.New(rand.NewPCG(seed, seed+1))
		d, q := walkFixture()
		q.MaxLegs = 6
		q.LatestArrival = 3000
		for i := range d.Connections {
			d.Connections[i].Departure += int64(rng.IntN(300))
			d.Connections[i].Arrival = d.Connections[i].Departure + int64(rng.IntN(100))
		}
		for i := range d.Footpaths {
			d.Footpaths[i].Duration = 1 + int64(rng.IntN(900))
		}
		if seed%3 == 0 {
			d.Transfers = []model.TransferRule{{ID: "rule", FromStop: "C", ToStop: "D", Type: 2, MinSeconds: int64(rng.IntN(1000))}}
		}
		differential(t, d, []model.Query{q})
	})
}
