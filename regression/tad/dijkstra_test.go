package tad_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tad"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"reflect"
	"slices"
	"sync"
	"testing"
)

func fullWords(d model.Dataset, q model.Query, limit int) []model.Metrics {
	ms := []model.Metrics{}
	var visit func([]int)
	visit = func(w []int) {
		_, m, ok := assess(d, q, w)
		if ok {
			ms = append(ms, m)
		}
		if len(w) == limit {
			return
		}
		for i := 0; i < len(d.Connections)+len(d.Footpaths); i++ {
			visit(append(w, i))
		}
	}
	visit(nil)
	return ms
}
func metrics(t testing.TB, d model.Dataset, q model.Query, js []model.Journey) []model.Metrics {
	t.Helper()
	ms := []model.Metrics{}
	seen := map[string]bool{}
	for _, j := range js {
		word := []int{}
		for _, l := range j.Legs {
			index := -1
			for i, c := range d.Connections {
				if l.Kind == "ride" && l.Ref == c.ID {
					index = i
				}
			}
			for i, w := range d.Footpaths {
				if l.Kind == "walk" && l.Ref == w.ID {
					index = len(d.Connections) + i
				}
			}
			if index < 0 {
				t.Fatal("unknown event", l)
			}
			word = append(word, index)
		}
		expected, m, ok := assess(d, q, word)
		if !ok || !reflect.DeepEqual(j, expected) {
			t.Fatalf("invalid TAD witness %+v expected %+v", j, expected)
		}
		id := identity(j)
		if seen[id] {
			t.Fatal("duplicate identity")
		}
		seen[id] = true
		ms = append(ms, m)
	}
	return ms
}
func generated(seed uint64) (model.Dataset, model.Query) {
	rng := rand.New(rand.NewPCG(seed, seed+57))
	d := data()
	q := query()
	q.MaxLegs = 32
	q.LatestArrival = 30
	q.MaxBoardings = 1 + rng.IntN(3)
	q.Departure = int64(rng.IntN(4))
	q.TransferBuffer = int64(rng.IntN(4))
	q.AccessibleOnly = rng.IntN(5) == 0
	q.Walking = &model.WalkingLimits{Access: int64(rng.IntN(6)), Egress: int64(rng.IntN(6)), Transfer: int64(rng.IntN(6)), Direct: int64(rng.IntN(6))}
	dep := int64(rng.IntN(7))
	arr := dep + 1 + int64(rng.IntN(5))
	dep2 := arr + int64(rng.IntN(3))
	trip(&d, "loop", []string{"A", "B", "A"}, dep, arr, dep2, dep2+1+int64(rng.IntN(4)))
	from := []string{"A", "B", "C"}[rng.IntN(3)]
	dep = int64(rng.IntN(17))
	trip(&d, "exit", []string{from, "D"}, dep, dep+1+int64(rng.IntN(5)))
	d.Footpaths = []model.Footpath{{ID: "w1", From: "A", To: "B", Duration: 1 + int64(rng.IntN(5)), Accessible: model.Yes}, {ID: "w2", From: "A", To: []string{"C", "D"}[rng.IntN(2)], Duration: 1 + int64(rng.IntN(5)), Accessible: model.Yes}}
	for i := range d.Connections {
		d.Connections[i].Pickup = rng.IntN(6) != 0
		d.Connections[i].Dropoff = rng.IntN(6) != 0
	}
	typ := []int{0, 2, 3}[rng.IntN(3)]
	rule := model.TransferRule{ID: "rule", FromStop: "B", ToStop: from, Type: typ}
	if typ == 2 {
		rule.MinSeconds = int64(rng.IntN(5))
	}
	d.Transfers = []model.TransferRule{rule}
	if rng.IntN(4) == 0 {
		d.Stops[1].Accessible = model.Unknown
	}
	return d, q
}

func cfg() tad.Config {
	return tad.Config{MaxLabels: 100000, MaxConnectionVisits: 100000, MaxWalkVisits: 100000}
}
func minimum(ms []model.Metrics) int64 {
	v := inf
	for _, m := range ms {
		v = min(v, m.Arrival)
	}
	return v
}
func check(t testing.TB, d model.Dataset, q model.Query, want int64) *tad.Index {
	t.Helper()
	x, e := tad.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.Search(context.Background(), q, cfg())
	if e != nil || !r.Complete {
		t.Fatal(e, r)
	}
	ms := metrics(t, d, q, r.Journeys)
	if len(ms) > 1 || minimum(ms) != want {
		t.Fatalf("want %d got %v; data %+v query %+v", want, ms, d, q)
	}
	return x
}
func TestIndependentEventUniverses(t *testing.T) {
	for seed := uint64(0); seed < 192; seed++ {
		d, q := generated(seed)
		check(t, d, q, minimum(fullWords(d, q, 7)))
	}
	t.Log("192 complete event universes; 18,749,952 unpruned words; three positive ride events and at most one A-outgoing walk per gap")
}
func TestIndependentWalkingCycleUniverses(t *testing.T) {
	for seed := uint64(0); seed < 64; seed++ {
		rng := rand.New(rand.NewPCG(seed, seed+91))
		d, q := data(), query()
		q.LatestArrival = 8
		q.MaxBoardings = 2
		q.TransferBuffer = int64(rng.IntN(3))
		q.Walking = &model.WalkingLimits{Access: int64(rng.IntN(4)), Egress: int64(rng.IntN(4)), Transfer: int64(rng.IntN(4)), Direct: int64(rng.IntN(4))}
		dep := int64(rng.IntN(4))
		trip(&d, "feed", []string{"A", "B"}, dep, dep+1)
		dep = int64(rng.IntN(7))
		trip(&d, "exit", []string{"C", "D"}, dep, dep+1)
		d.Footpaths = []model.Footpath{{ID: "out", From: "B", To: "C", Duration: 1, Accessible: model.Yes}, {ID: "back", From: "C", To: "B", Duration: 1, Accessible: model.Yes}}
		check(t, d, q, minimum(fullWords(d, q, 8)))
	}
	t.Log("64 complete walking-cycle universes; 5,592,384 unpruned words; all legs consume >=1 second inside horizon 8, so no feasible word can exceed length 8")
}
func TestDominatedIntermediateArrivalMustKeepSeatedVehicle(t *testing.T) {
	d, q := data(), query()
	q.TransferBuffer = 5
	trip(&d, "early-stop", []string{"A", "B"}, 0, 2)
	trip(&d, "through", []string{"A", "B", "D"}, 1, 3, 3, 4)
	x := check(t, d, q, 4)
	r, _ := x.Search(context.Background(), q, cfg())
	if got := []string{r.Journeys[0].Legs[0].Ref, r.Journeys[0].Legs[1].Ref}; !reflect.DeepEqual(got, []string{"through/0", "through/1"}) {
		t.Fatal(got)
	}
	d.Connections[1].Dropoff = false
	d.Connections[2].Pickup = false
	d.Stops[1].Accessible = model.No
	q.AccessibleOnly = true
	check(t, d, q, 4)
	slices.Reverse(d.Connections)
	slices.Reverse(d.Trips)
	check(t, d, q, 4)
	for i := range d.Connections {
		d.Connections[i].Departure += 86399
		d.Connections[i].Arrival += 86399
	}
	q.Departure += 86399
	q.LatestArrival += 86399
	check(t, d, q, 86403)
}
func TestNonFIFOAndClosedBoardingBoundary(t *testing.T) {
	d, q := data(), query()
	trip(&d, "slow", []string{"A", "D"}, 1, 10)
	trip(&d, "fast", []string{"A", "D"}, 2, 3)
	q.Departure = 2
	check(t, d, q, 3)
	q.Departure = 3
	check(t, d, q, inf)
}
func TestAlightingContextAndWalkingRoles(t *testing.T) {
	d, q := data(), query()
	trip(&d, "b", []string{"A", "B"}, 0, 1)
	trip(&d, "c", []string{"A", "C"}, 0, 3)
	trip(&d, "out", []string{"X", "D"}, 5, 7)
	d.Footpaths = []model.Footpath{{ID: "bx", From: "B", To: "X", Duration: 4, Accessible: model.Yes}, {ID: "cx", From: "C", To: "X", Duration: 1, Accessible: model.Yes}}
	d.Transfers = []model.TransferRule{{ID: "block-early", FromStop: "C", ToStop: "X", Type: 2, MinSeconds: 10}}
	check(t, d, q, 7)
	q.Walking.Transfer = 3
	check(t, d, q, inf)
	d, q = data(), query()
	q.MaxBoardings = 0
	q.Walking = &model.WalkingLimits{Access: 1, Egress: 1, Transfer: 1, Direct: 3}
	d.Footpaths = []model.Footpath{{ID: "ab", From: "A", To: "B", Duration: 1, Accessible: model.Yes}, {ID: "bc", From: "B", To: "C", Duration: 1, Accessible: model.Yes}, {ID: "cd", From: "C", To: "D", Duration: 1, Accessible: model.Yes}, {ID: "cb", From: "C", To: "B", Duration: 1, Accessible: model.Yes}}
	check(t, d, q, 3)
	q.Walking.Direct = 2
	check(t, d, q, inf)
}
func TestParentStationSpecificityAndBufferEquality(t *testing.T) {
	d, q := data(), query()
	d.Stops = append(d.Stops, model.Stop{ID: "P", LocationType: 1, Accessible: model.Yes})
	d.Stops[1].ParentStation = "P"
	d.Stops[2].ParentStation = "P"
	trip(&d, "feed", []string{"A", "B"}, 0, 1)
	trip(&d, "out", []string{"C", "D"}, 4, 6)
	d.Footpaths = []model.Footpath{{ID: "bc", From: "B", To: "C", Duration: 1, Accessible: model.Yes}}
	q.TransferBuffer = 20
	// Parent semantics are checked against literal answers and the independent
	// production validator; the retained whole-word evaluator models exact pairs.
	for _, tc := range []struct {
		rules []model.TransferRule
		want  int64
	}{
		{[]model.TransferRule{{ID: "minimum", FromStop: "P", ToStop: "P", Type: 2, MinSeconds: 3}}, 6},
		{[]model.TransferRule{{ID: "minimum", FromStop: "P", ToStop: "P", Type: 2, MinSeconds: 4}}, inf},
		{[]model.TransferRule{{ID: "recommended", FromStop: "P", ToStop: "P", Type: 0}}, 6},
		{[]model.TransferRule{{ID: "forbidden", FromStop: "P", ToStop: "P", Type: 3}}, inf},
	} {
		d.Transfers = tc.rules
		x, e := tad.New(d)
		if e != nil {
			t.Fatal(e)
		}
		r, e := x.Search(context.Background(), q, cfg())
		if e != nil || !r.Complete {
			t.Fatal(e, r)
		}
		checker, e := validate.New(d)
		if e != nil {
			t.Fatal(e)
		}
		ms := []model.Metrics{}
		for _, j := range r.Journeys {
			v, e := checker.Check(q, j)
			if e != nil {
				t.Fatal(e)
			}
			ms = append(ms, v.Metrics)
		}
		if minimum(ms) != tc.want {
			t.Fatal(tc, ms)
		}
	}
}
func TestConflictingParentAndChildRulesReject(t *testing.T) {
	d := data()
	d.Stops = append(d.Stops, model.Stop{ID: "P", LocationType: 1, Accessible: model.Yes})
	d.Stops[1].ParentStation = "P"
	d.Stops[2].ParentStation = "P"
	d.Transfers = []model.TransferRule{{ID: "parent", FromStop: "P", ToStop: "P", Type: 3}, {ID: "child", FromStop: "B", ToStop: "C", Type: 0}}
	if _, e := tad.New(d); e == nil {
		t.Fatal("conflicting rules at equal selector specificity accepted")
	}
}
func TestBudgetsRejectionCancellationAndConcurrentReuse(t *testing.T) {
	d, q := data(), query()
	trip(&d, "through", []string{"A", "B", "D"}, 1, 2, 2, 4)
	d.Footpaths = []model.Footpath{{ID: "ab", From: "A", To: "B", Duration: 1, Accessible: model.Yes}, {ID: "bc", From: "B", To: "C", Duration: 1, Accessible: model.Yes}}
	x := check(t, d, q, 4)
	for _, c := range []tad.Config{{MaxLabels: 1, MaxConnectionVisits: 100, MaxWalkVisits: 100}, {MaxLabels: 100, MaxConnectionVisits: 1, MaxWalkVisits: 100}, {MaxLabels: 100, MaxConnectionVisits: 100, MaxWalkVisits: 1}, {}} {
		r, e := x.Search(context.Background(), q, c)
		if e == nil || r.Complete {
			t.Fatal("truncated accepted", r, c)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if r, e := x.Search(ctx, q, cfg()); e == nil || r.Complete {
		t.Fatal(r, e)
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, e := x.Search(context.Background(), q, cfg())
			if e != nil || !r.Complete || minimum(metrics(t, d, q, r.Journeys)) != 4 {
				t.Error(r, e)
			}
		}()
	}
	wg.Wait()
	d.Transfers = []model.TransferRule{{ID: "specific", FromStop: "B", ToStop: "B", FromTrip: "through", Type: 0}}
	if _, e := tad.New(d); e == nil {
		t.Fatal("unsupported trip specificity accepted")
	}
	q.MaxWalkSeconds = 1
	if r, e := x.Search(context.Background(), q, cfg()); e == nil || r.Complete {
		t.Fatal("binding resource accepted", r)
	}
}
func FuzzIndependentTAD(f *testing.F) {
	for _, seed := range []uint64{0, 1, 19, 41, 191} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, seed uint64) { d, q := generated(seed); check(t, d, q, minimum(fullWords(d, q, 7))) })
}
