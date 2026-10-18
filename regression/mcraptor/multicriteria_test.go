package mcraptor_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/raptor"
	"math/rand/v2"
	"reflect"
	"slices"
	"sort"
	"sync"
	"testing"
)

type vector struct {
	Arrival int64
	Boards  int
	Walk    int64
}

func pareto(ms []model.Metrics) []vector {
	all := []vector{}
	for _, m := range ms {
		v := vector{m.Arrival, m.Boardings, m.WalkingSeconds}
		if !slices.Contains(all, v) {
			all = append(all, v)
		}
	}
	out := []vector{}
	for i, a := range all {
		dominated := false
		for j, b := range all {
			if i != j && b.Arrival <= a.Arrival && b.Boards <= a.Boards && b.Walk <= a.Walk {
				dominated = true
				break
			}
		}
		if !dominated {
			out = append(out, a)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.Boards != b.Boards {
			return a.Boards < b.Boards
		}
		if a.Arrival != b.Arrival {
			return a.Arrival < b.Arrival
		}
		return a.Walk < b.Walk
	})
	return out
}
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
			t.Fatalf("invalid McRAPTOR witness %+v expected %+v", j, expected)
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
func cfg() raptor.MultiConfig {
	return raptor.MultiConfig{Criterion: "walking_seconds", MaxLabels: 100000, MaxConnectionVisits: 100000}
}
func check(t testing.TB, d model.Dataset, q model.Query, want []vector) *raptor.Index {
	t.Helper()
	x, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.SearchMulti(context.Background(), q, cfg())
	if e != nil || !r.Complete {
		t.Fatal(e, r)
	}
	ms := metrics(t, d, q, r.Journeys)
	got := pareto(ms)
	if len(got) != len(ms) || !reflect.DeepEqual(got, want) {
		t.Fatalf("want %v got %v; dataset %+v query %+v result %+v", want, got, d, q, r)
	}
	return x
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
func TestIndependentThreeObjectiveCorpus(t *testing.T) {
	for seed := uint64(0); seed < 192; seed++ {
		d, q := generated(seed)
		check(t, d, q, pareto(fullWords(d, q, 7)))
	}
	t.Log("192 finite universes; 18,749,952 unpruned words; three positive ride events and at most one directed A-outgoing walk per gap")
}
func TestLiteralWalkingTradeoffsAndRouteBags(t *testing.T) {
	d, q := data(), query()
	q.Walking = &model.WalkingLimits{Access: 10, Egress: 10, Transfer: 10, Direct: 10}
	d.Footpaths = []model.Footpath{{ID: "walk-to-fast", From: "A", To: "B", Duration: 3, Accessible: model.Yes}, {ID: "direct-walk", From: "A", To: "D", Duration: 7, Accessible: model.Yes}}
	trip(&d, "direct", []string{"A", "D"}, 1, 20)
	trip(&d, "fast", []string{"B", "D"}, 3, 10)
	trip(&d, "feed", []string{"A", "C"}, 0, 2)
	trip(&d, "out", []string{"C", "D"}, 2, 8)
	want := []vector{{7, 0, 7}, {10, 1, 3}, {20, 1, 0}, {8, 2, 0}}
	check(t, d, q, want)
	slices.Reverse(d.Connections)
	slices.Reverse(d.Trips)
	slices.Reverse(d.Footpaths)
	check(t, d, q, want)
	for i := range d.Connections {
		d.Connections[i].Departure += 86399
		d.Connections[i].Arrival += 86399
	}
	q.Departure += 86399
	q.LatestArrival += 86399
	for i := range want {
		want[i].Arrival += 86399
	}
	check(t, d, q, want)
	d, q = data(), query()
	d.Footpaths = []model.Footpath{{ID: "access", From: "A", To: "B", Duration: 1, Accessible: model.Yes}}
	trip(&d, "zero-walk", []string{"A", "C"}, 0, 5)
	trip(&d, "some-walk", []string{"B", "C"}, 1, 3)
	trip(&d, "shared", []string{"C", "D"}, 6, 10)
	check(t, d, q, []vector{{10, 2, 0}})
	d, q = data(), query()
	d.Footpaths = []model.Footpath{{ID: "access", From: "A", To: "B", Duration: 3, Accessible: model.Yes}}
	trip(&d, "walking-feed", []string{"B", "C"}, 3, 4)
	trip(&d, "seated-feed", []string{"A", "C"}, 0, 6)
	trip(&d, "early-route", []string{"C", "X", "D"}, 5, 7, 7, 10)
	trip(&d, "late-route", []string{"C", "X", "D"}, 8, 10, 10, 14)
	check(t, d, q, []vector{{10, 2, 3}, {14, 2, 0}})
}
func TestRestrictionOnboardAndBudgetContracts(t *testing.T) {
	d, q := data(), query()
	trip(&d, "through", []string{"A", "B", "D"}, 1, 2, 2, 4)
	d.Connections[0].Dropoff = false
	d.Connections[1].Pickup = false
	d.Stops[1].Accessible = model.No
	q.AccessibleOnly = true
	q.TransferBuffer = 100
	x := check(t, d, q, []vector{{4, 1, 0}})
	for _, bad := range []raptor.MultiConfig{{Criterion: "fare_zones", MaxLabels: 100, MaxConnectionVisits: 100}, {Criterion: "walking_seconds", MaxLabels: 1, MaxConnectionVisits: 100}, {Criterion: "walking_seconds", MaxLabels: 100, MaxConnectionVisits: 1}} {
		r, e := x.SearchMulti(context.Background(), q, bad)
		if e == nil || r.Complete {
			t.Fatal("unsupported/truncated query accepted", bad, r)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r, e := x.SearchMulti(ctx, q, cfg())
	if e == nil || r.Complete {
		t.Fatal("cancel accepted")
	}
	var wg sync.WaitGroup
	results := make(chan raptor.MultiResult, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, e := x.SearchMulti(context.Background(), q, cfg())
			if e != nil {
				r.Error = e.Error()
			}
			results <- r
		}()
	}
	wg.Wait()
	close(results)
	for r := range results {
		if !r.Complete || r.Error != "" || !reflect.DeepEqual(pareto(metrics(t, d, q, r.Journeys)), []vector{{4, 1, 0}}) {
			t.Fatal(r)
		}
	}
}
func FuzzIndependentWalkingPareto(f *testing.F) {
	for _, s := range []uint64{0, 1, 13, 31, 72} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s uint64) { d, q := generated(s); check(t, d, q, pareto(fullWords(d, q, 7))) })
}
