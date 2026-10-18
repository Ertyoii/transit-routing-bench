package paper_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/eacsa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"reflect"
	"slices"
	"sync"
	"testing"
)

func base() (model.Dataset, model.Query) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "paper-test", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17"}
	for _, s := range []string{"A", "B", "C", "D", "E"} {
		d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
	}
	q := model.Query{ID: "q", Origin: "A", Destination: "D", Departure: 0, LatestArrival: 100, MaxBoardings: 3, MaxLegs: 32, MaxWalkSeconds: 20, Walking: &model.WalkingLimits{Access: 4, Transfer: 5, Egress: 4, Direct: 4}}
	return d, q
}
func add(d *model.Dataset, id string, cs ...model.Connection) {
	d.Trips = append(d.Trips, model.Trip{ID: id, RouteID: "same-gtfs-route", Accessible: model.Yes})
	for i, c := range cs {
		c.ID = fmt.Sprintf("%s-%d", id, i)
		c.TripID = id
		c.Sequence = i
		d.Connections = append(d.Connections, c)
	}
}
func ride(from, to string, dep, arr int64) model.Connection {
	return model.Connection{From: from, To: to, Departure: dep, Arrival: arr, Pickup: true, Dropoff: true}
}
func vectors(t testing.TB, d model.Dataset, q model.Query, js []model.Journey) []int64 {
	t.Helper()
	v, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	best := make([]int64, q.MaxBoardings+1)
	for i := range best {
		best[i] = paper.Infinity
	}
	for _, j := range js {
		x, e := v.Check(q, j)
		if e != nil {
			t.Fatalf("invalid witness: %v; %+v", e, j)
		}
		for b := x.Metrics.Boardings; b < len(best); b++ {
			best[b] = min(best[b], x.Metrics.Arrival)
		}
	}
	return best
}
func compare(t testing.TB, d model.Dataset, q model.Query, alsoCandidates bool) []int64 {
	t.Helper()
	o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 300000, MaxJourneys: 100000})
	if e != nil || !o.Complete {
		t.Fatalf("oracle inconclusive: %v", e)
	}
	want := vectors(t, d, q, o.Journeys)
	a, e := eacsa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	for name, search := range map[string]func(context.Context, model.Query) (paper.Result, error){"EA-CSA": a.Search, "RAPTOR": r.Search} {
		result, e := search(context.Background(), q)
		if e != nil || !result.Complete {
			t.Fatalf("%s incomplete: %v", name, e)
		}
		if got := vectors(t, d, q, result.Journeys); !reflect.DeepEqual(got, want) {
			t.Fatalf("%s: want %v got %v; data %+v; query %+v; witnesses %+v", name, want, got, d, q, result.Journeys)
		}
	}
	if alsoCandidates {
		idx, e := csa.New(d)
		if e != nil {
			t.Fatal(e)
		}
		cfg := csa.Config{MaxLabels: 300000, MaxJourneys: 100000}
		single, e := idx.Single(context.Background(), q, cfg)
		if e != nil || !single.Complete {
			t.Fatal(e)
		}
		shared, e := idx.Shared(context.Background(), []model.Query{q}, cfg)
		if e != nil {
			t.Fatal(e)
		}
		for _, result := range []csa.Result{single, shared.Results[0]} {
			if got := vectors(t, d, q, result.Journeys); !reflect.DeepEqual(got, want) {
				t.Fatalf("candidate mismatch: %v != %v", got, want)
			}
		}
	}
	return want
}
func TestOvertakingAndDistinctParetoPoints(t *testing.T) {
	d, q := base()
	add(&d, "slow", ride("A", "B", 1, 20), ride("B", "D", 21, 40))
	add(&d, "fast", ride("A", "B", 2, 10), ride("B", "D", 11, 30))
	add(&d, "feeder", ride("A", "C", 3, 5))
	add(&d, "express", ride("C", "D", 6, 15))
	want := compare(t, d, q, true)
	if !reflect.DeepEqual(want, []int64{paper.Infinity, 30, 15, 15}) {
		t.Fatal(want)
	}
	idx, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	if idx.Preparation().OvertakingSplits != 1 {
		t.Fatalf("overtaking trips were not split: %+v", idx.Preparation())
	}
}
func TestWalkingRolesMinimumProhibitionAndOnboard(t *testing.T) {
	d, q := base()
	q.Walking = &model.WalkingLimits{Access: 2, Egress: 2, Transfer: 5, Direct: 2}
	q.TransferBuffer = 50
	d.Footpaths = []model.Footpath{{ID: "a", From: "A", To: "B", Duration: 2, Accessible: model.Yes}, {ID: "x", From: "C", To: "E", Duration: 5, Accessible: model.Yes}}
	add(&d, "one", ride("B", "C", 2, 10))
	add(&d, "two", ride("E", "D", 16, 20))
	d.Transfers = []model.TransferRule{{ID: "minimum", FromStop: "C", ToStop: "E", Type: 2, MinSeconds: 6}}
	if got := compare(t, d, q, true); got[2] != 20 {
		t.Fatal(got)
	}
	d.Transfers[0].MinSeconds = 7
	if got := compare(t, d, q, true); got[3] != paper.Infinity {
		t.Fatal("inclusive minimum ignored")
	}
	d.Transfers[0].Type = 3
	d.Transfers[0].MinSeconds = 0
	if got := compare(t, d, q, true); got[3] != paper.Infinity {
		t.Fatal("walking bypassed transfer prohibition")
	}
	d, q = base()
	q.TransferBuffer = 99
	c := ride("A", "B", 1, 5)
	c.Dropoff = false
	next := ride("B", "D", 5, 10)
	next.Pickup = false
	add(&d, "stay", c, next)
	if got := compare(t, d, q, true); got[1] != 10 {
		t.Fatal("transfer buffer or pickup/dropoff wrongly prevents staying")
	}
}
func TestAccessCannotDominateTransitTransferWalking(t *testing.T) {
	d, q := base()
	q.Walking = &model.WalkingLimits{Access: 0, Egress: 0, Transfer: 3, Direct: 0}
	add(&d, "loop", ride("A", "B", 1, 2), ride("B", "A", 2, 3))
	add(&d, "last", ride("C", "D", 7, 8))
	d.Footpaths = []model.Footpath{{ID: "ac", From: "A", To: "C", Duration: 3, Accessible: model.Yes}}
	if got := compare(t, d, q, true); got[2] != 8 {
		t.Fatal("access label incorrectly dominates a different walking role")
	}
}
func TestDestinationAbsorbingAndAccessibility(t *testing.T) {
	d, q := base()
	q.Walking = &model.WalkingLimits{Access: 4, Egress: 4, Transfer: 4, Direct: 0}
	d.Footpaths = []model.Footpath{{ID: "ad", From: "A", To: "D", Duration: 1, Accessible: model.Yes}, {ID: "dc", From: "D", To: "C", Duration: 1, Accessible: model.Yes}}
	add(&d, "back", ride("C", "D", 5, 10))
	if got := compare(t, d, q, true); got[3] != paper.Infinity {
		t.Fatal("walk left destination")
	}
	d, q = base()
	add(&d, "unknown", ride("A", "D", 5, 10))
	d.Trips[0].Accessible = model.Unknown
	q.AccessibleOnly = true
	if got := compare(t, d, q, true); got[3] != paper.Infinity {
		t.Fatal("unknown access accepted")
	}
}
func generated(seed uint64) (model.Dataset, model.Query) {
	rng := rand.New(rand.NewPCG(seed, 918273))
	d, q := base()
	q.LatestArrival = 30
	stops := []string{"A", "B", "C", "D", "E"}
	for i := 0; i < 7; i++ {
		from := rng.IntN(5)
		to := (from + 1 + rng.IntN(4)) % 5
		dep := int64(rng.IntN(20))
		c := ride(stops[from], stops[to], dep, dep+1+int64(rng.IntN(5)))
		c.Pickup = rng.IntN(5) != 0
		c.Dropoff = rng.IntN(5) != 0
		add(&d, fmt.Sprint(i), c)
	}
	// Acyclic walking keeps bounded exhaustive enumeration modest.
	for i := 0; i < 2; i++ {
		from := rng.IntN(4)
		to := from + 1 + rng.IntN(4-from)
		d.Footpaths = append(d.Footpaths, model.Footpath{ID: fmt.Sprint("w", i), From: stops[from], To: stops[to], Duration: int64(1 + rng.IntN(5)), Accessible: model.Yes})
	}
	q.TransferBuffer = int64(rng.IntN(5))
	if seed%3 != 0 {
		kind := 2
		if seed%3 == 1 {
			kind = 3
		}
		minimum := int64(0)
		if kind == 2 {
			minimum = int64(rng.IntN(7))
		}
		d.Transfers = []model.TransferRule{{ID: "rule", FromStop: stops[rng.IntN(5)], ToStop: stops[rng.IntN(5)], Type: kind, MinSeconds: minimum}}
	}
	return d, q
}
func TestSeededMatchedContracts(t *testing.T) {
	for seed := uint64(20261017); seed < 20261317; seed++ {
		d, q := generated(seed)
		compare(t, d, q, seed%10 == 0)
	}
}

// Repeated stops, shared patterns, overtaking, and partial boarding restrictions
// exercise route scanning and parent replacement beyond one-connection trips.
func complexGenerated(seed uint64) (model.Dataset, model.Query) {
	rng := rand.New(rand.NewPCG(seed, 112358))
	d, q := base()
	q.LatestArrival = 45
	stops := []string{"A", "B", "C", "D", "E"}
	for pattern := 0; pattern < 3; pattern++ {
		length := 2 + rng.IntN(2)
		path := []int{rng.IntN(5)}
		for range length {
			path = append(path, (path[len(path)-1]+1+rng.IntN(4))%5)
		}
		pickup, dropoff := []bool{}, []bool{}
		for range length {
			pickup = append(pickup, rng.IntN(4) != 0)
			dropoff = append(dropoff, rng.IntN(4) != 0)
		}
		for variant := 0; variant < 2; variant++ {
			at := int64(rng.IntN(15))
			cs := []model.Connection{}
			for i := 0; i < length; i++ {
				c := ride(stops[path[i]], stops[path[i+1]], at, at+1+int64(rng.IntN(7)))
				c.Pickup = pickup[i]
				c.Dropoff = dropoff[i]
				cs = append(cs, c)
				at = c.Arrival + int64(rng.IntN(3))
			}
			add(&d, fmt.Sprintf("%d-%d", pattern, variant), cs...)
		}
	}
	for i := 0; i < 2; i++ {
		from := rng.IntN(4)
		to := from + 1 + rng.IntN(4-from)
		d.Footpaths = append(d.Footpaths, model.Footpath{ID: fmt.Sprintf("w%d", i), From: stops[from], To: stops[to], Duration: 1 + int64(rng.IntN(5)), Accessible: model.Yes})
	}
	q.TransferBuffer = int64(rng.IntN(6))
	return d, q
}
func TestSeededMultiSegmentRoutes(t *testing.T) {
	for seed := uint64(20261017); seed < 20261317; seed++ {
		d, q := complexGenerated(seed)
		compare(t, d, q, seed%20 == 0)
	}
}
func FuzzPaperBaselines(f *testing.F) {
	f.Add(uint64(20261017))
	f.Add(uint64(0))
	f.Add(uint64(97))
	f.Fuzz(func(t *testing.T, seed uint64) {
		d, q := generated(seed)
		compare(t, d, q, false)
		d, q = complexGenerated(seed)
		compare(t, d, q, false)
	})
}
func TestMetamorphicPermutationTimeShiftConcurrency(t *testing.T) {
	d, q := generated(20261027)
	want := compare(t, d, q, true)
	slices.Reverse(d.Connections)
	slices.Reverse(d.Trips)
	slices.Reverse(d.Stops)
	slices.Reverse(d.Footpaths)
	if got := compare(t, d, q, true); !reflect.DeepEqual(got, want) {
		t.Fatal("input permutation changed objectives")
	}
	const shift = 90000
	for i := range d.Connections {
		d.Connections[i].Arrival += shift
		d.Connections[i].Departure += shift
	}
	q.Departure += shift
	q.LatestArrival += shift
	got := compare(t, d, q, true)
	for i := range want {
		if want[i] != paper.Infinity {
			want[i] += shift
		}
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatal("time translation changed objectives")
	}
	a, _ := eacsa.New(d)
	r, _ := raptor.New(d)
	var wg sync.WaitGroup
	for range 4 {
		wg.Go(func() {
			for _, search := range []func(context.Context, model.Query) (paper.Result, error){a.Search, r.Search} {
				result, e := search(context.Background(), q)
				if e != nil || !result.Complete {
					t.Errorf("concurrent search: %v", e)
				}
			}
		})
	}
	wg.Wait()
}
func TestUnsupportedCapabilitiesAndCancellation(t *testing.T) {
	d, q := base()
	add(&d, "ride", ride("A", "D", 1, 2))
	for _, factory := range []func(model.Dataset) error{func(d model.Dataset) error { _, e := eacsa.New(d); return e }, func(d model.Dataset) error { _, e := raptor.New(d); return e }} {
		bad := d.Clone()
		bad.Connections[0].Arrival = 1
		if factory(bad) == nil {
			t.Fatal("zero-duration capability silently accepted")
		}
		bad = d.Clone()
		bad.Transfers = []model.TransferRule{{ID: "trip-rule", FromStop: "A", ToStop: "D", FromTrip: "ride", Type: 3}}
		if factory(bad) == nil {
			t.Fatal("trip rule capability silently accepted")
		}
	}
	a, _ := eacsa.New(d)
	r, _ := raptor.New(d)
	for _, search := range []func(context.Context, model.Query) (paper.Result, error){a.Search, r.Search} {
		bad := q
		bad.MaxWalkSeconds = 1
		if result, e := search(context.Background(), bad); e == nil || result.Complete {
			t.Fatal("binding resource silently ignored")
		}
		bad = q
		bad.MaxLegs = 3
		bad.MaxBoardings = 3
		d2 := d.Clone()
		add(&d2, "long", ride("A", "B", 1, 2), ride("B", "D", 2, 3))
		idx, _ := eacsa.New(d2)
		if _, e := idx.Search(context.Background(), bad); e == nil {
			t.Fatal("binding leg budget ignored")
		}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		if result, e := search(ctx, q); e == nil || result.Complete {
			t.Fatal("cancelled query exact")
		}
	}
}
