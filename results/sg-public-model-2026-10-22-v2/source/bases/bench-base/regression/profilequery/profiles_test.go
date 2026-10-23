package profilequery_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/profilecsa"
	"github.com/ertyoii/transit-routing-go/profilequery"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"reflect"
	"slices"
	"sync"
	"testing"
)

var limits = profilequery.Limits{MaxConnectionVisits: 100000, MaxLabels: 100000, MaxDepartures: 10000}

type search func(context.Context, profilequery.Query, profilequery.Limits) (profilequery.Result, error)

func searches(t testing.TB, d model.Dataset) map[string]search {
	t.Helper()
	a, e := profilecsa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	b, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	return map[string]search{"profile_csa": a.Search, "range_raptor": b.SearchRange}
}
func metrics(t testing.TB, d model.Dataset, q model.Query, j model.Journey) model.Metrics {
	t.Helper()
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
			t.Fatal("unknown itinerary event", l)
		}
		word = append(word, index)
	}
	expected, m, ok := assess(d, q, word)
	if !ok || !reflect.DeepEqual(expected, j) {
		t.Fatalf("invalid profile witness at %d: %+v; expected %+v", q.Departure, j, expected)
	}
	return m
}
func words(d model.Dataset, q model.Query, depth int) []model.Metrics {
	ms := []model.Metrics{}
	var visit func([]int)
	visit = func(w []int) {
		_, m, ok := assess(d, q, w)
		if ok {
			ms = append(ms, m)
		}
		if len(w) == depth {
			return
		}
		for i := 0; i < len(d.Connections)+len(d.Footpaths); i++ {
			visit(append(w, i))
		}
	}
	visit(nil)
	return ms
}
func check(t testing.TB, d model.Dataset, q profilequery.Query, depth int) {
	t.Helper()
	expected := map[int64][]int64{}
	for ready := q.Base.Departure; ready <= q.End; ready++ {
		at := q.Base
		at.Departure = ready
		expected[ready] = objectives(words(d, at, depth), at.MaxBoardings)
	}
	for name, run := range searches(t, d) {
		r, e := run(context.Background(), q, limits)
		if e != nil || !r.Complete {
			t.Fatalf("%s: %+v %v", name, r, e)
		}
		for _, p := range r.Points {
			at := q.Base
			at.Departure = p.LatestReady
			m := metrics(t, d, at, p.Journey)
			if p.LatestReady < q.Base.Departure || p.LatestReady > q.End || p.Arrival != m.Arrival || p.Boardings != m.Boardings {
				t.Fatalf("%s incorrect point %+v / %+v", name, p, m)
			}
		}
		for ready, want := range expected {
			js, e := r.At(ready)
			if e != nil {
				t.Fatal(e)
			}
			at := q.Base
			at.Departure = ready
			ms := []model.Metrics{}
			for _, j := range js {
				ms = append(ms, metrics(t, d, at, j))
			}
			if got := objectives(ms, at.MaxBoardings); !reflect.DeepEqual(got, want) {
				t.Fatalf("%s ready %d want %v got %v; dataset=%+v query=%+v result=%+v", name, ready, want, got, d, q, r)
			}
		}
	}
}
func generated(seed uint64) (model.Dataset, profilequery.Query) {
	rng := rand.New(rand.NewPCG(seed, seed+151))
	d := data()
	q := query()
	q.MaxLegs = 32
	q.LatestArrival = 30
	q.MaxBoardings = 1 + rng.IntN(3)
	q.Walking = &model.WalkingLimits{Access: int64(rng.IntN(5)), Egress: int64(rng.IntN(5)), Transfer: int64(rng.IntN(5)), Direct: int64(rng.IntN(5))}
	q.TransferBuffer = int64(rng.IntN(4))
	q.AccessibleOnly = rng.IntN(5) == 0
	dep := int64(rng.IntN(9))
	arr := dep + 1 + int64(rng.IntN(5))
	dep2 := arr + int64(rng.IntN(3))
	trip(&d, "through", []string{"A", "B", "C"}, dep, arr, dep2, dep2+1+int64(rng.IntN(5)))
	from := []string{"A", "B", "C"}[rng.IntN(3)]
	dep = int64(rng.IntN(16))
	trip(&d, "exit", []string{from, "D"}, dep, dep+1+int64(rng.IntN(5)))
	for i := range d.Connections {
		d.Connections[i].Pickup = rng.IntN(5) != 0
		d.Connections[i].Dropoff = rng.IntN(5) != 0
	}
	d.Footpaths = []model.Footpath{{ID: "walk", From: []string{"A", "B", "C"}[rng.IntN(3)], To: "D", Duration: 1 + int64(rng.IntN(4)), Accessible: model.Yes}}
	typ := []int{0, 2, 3}[rng.IntN(3)]
	rule := model.TransferRule{ID: "rule", FromStop: "B", ToStop: from, Type: typ}
	if typ == 2 {
		rule.MinSeconds = int64(rng.IntN(7))
	}
	d.Transfers = []model.TransferRule{rule}
	if rng.IntN(4) == 0 {
		d.Stops[1].Accessible = model.No
	}
	if rng.IntN(4) == 0 {
		d.Trips[0].Accessible = model.Unknown
	}
	return d, profilequery.Query{Base: q, End: 15}
}
func TestIndependentWholeWindow(t *testing.T) {
	for seed := uint64(0); seed < 96; seed++ {
		d, q := generated(seed)
		check(t, d, q, 7)
	}
	t.Log("96 complete tiny universes × 16 integer ready times; 33,553,920 unpruned word assessments; no search/pruning shared")
}
func TestLiteralDepartureBoundariesAndClockTranslation(t *testing.T) {
	d := data()
	q := query()
	q.LatestArrival = 60
	trip(&d, "early", []string{"A", "D"}, 5, 30)
	trip(&d, "later", []string{"A", "D"}, 10, 25)
	trip(&d, "afterwindow", []string{"A", "D"}, 20, 40)
	trip(&d, "feed", []string{"A", "B"}, 8, 9)
	trip(&d, "exit", []string{"B", "D"}, 9, 15)
	q.Walking = &model.WalkingLimits{}
	window := profilequery.Query{Base: q, End: 12}
	check(t, d, window, 5)
	for _, run := range searches(t, d) {
		r, e := run(context.Background(), window, limits)
		if e != nil {
			t.Fatal(e)
		}
		for ready, want := range map[int64][]int64{0: {inf, 25, 15, 15}, 8: {inf, 25, 15, 15}, 9: {inf, 25, 25, 25}, 10: {inf, 25, 25, 25}, 11: {inf, 40, 40, 40}, 12: {inf, 40, 40, 40}} {
			js, e := r.At(ready)
			if e != nil {
				t.Fatal(e)
			}
			at := q
			at.Departure = ready
			ms := []model.Metrics{}
			for _, j := range js {
				ms = append(ms, metrics(t, d, at, j))
			}
			if !reflect.DeepEqual(objectives(ms, 3), want) {
				t.Fatal(ready, want, ms)
			}
		}
		if _, e := r.At(13); e == nil {
			t.Fatal("out-of-window lookup accepted")
		}
	}
	slices.Reverse(d.Connections)
	slices.Reverse(d.Trips)
	check(t, d, window, 5)
	for i := range d.Connections {
		d.Connections[i].Departure += 86395
		d.Connections[i].Arrival += 86395
	}
	window.Base.Departure += 86395
	window.Base.LatestArrival += 86395
	window.End += 86395
	check(t, d, window, 5)
}
func TestAccessOffsetWalkingOnlyAndStayingAboard(t *testing.T) {
	d := data()
	q := query()
	q.LatestArrival = 25
	q.Walking = &model.WalkingLimits{Access: 3, Egress: 3, Transfer: 4, Direct: 10}
	d.Footpaths = []model.Footpath{{ID: "access", From: "A", To: "B", Duration: 3, Accessible: model.Yes}, {ID: "direct", From: "A", To: "D", Duration: 10, Accessible: model.Yes}}
	trip(&d, "through", []string{"B", "C", "D"}, 7, 9, 9, 12)
	d.Connections[0].Dropoff = false
	d.Connections[1].Pickup = false
	q.TransferBuffer = 99
	check(t, d, profilequery.Query{Base: q, End: 11}, 5)
	// The first vehicle at 7 is catchable from A exactly at 4, not at 5.
	for _, run := range searches(t, d) {
		r, e := run(context.Background(), profilequery.Query{Base: q, End: 11}, limits)
		if e != nil {
			t.Fatal(e)
		}
		js, _ := r.At(4)
		ms := []model.Metrics{}
		at := q
		at.Departure = 4
		for _, j := range js {
			ms = append(ms, metrics(t, d, at, j))
		}
		if !reflect.DeepEqual(objectives(ms, 3), []int64{14, 12, 12, 12}) {
			t.Fatal(ms)
		}
	}
}
func TestProfileFailuresAreNotCertificates(t *testing.T) {
	d, base := data(), query()
	trip(&d, "through", []string{"A", "B", "D"}, 1, 2, 3, 4)
	trip(&d, "late", []string{"A", "D"}, 10, 12)
	q := profilequery.Query{Base: base, End: 8}
	for name, run := range searches(t, d) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		r, e := run(ctx, q, limits)
		if e == nil || r.Complete {
			t.Fatal(name, "cancel accepted")
		}
		if _, e = r.At(0); e == nil {
			t.Fatal("incomplete lookup")
		}
		for _, bad := range []profilequery.Limits{{MaxConnectionVisits: 1, MaxLabels: 100, MaxDepartures: 100}, {MaxConnectionVisits: 100, MaxLabels: 1, MaxDepartures: 100}, {}} {
			r, e = run(context.Background(), q, bad)
			if e == nil || r.Complete {
				t.Fatal(name, "budget accepted", bad, r)
			}
		}
		bad := q
		bad.End = -1
		r, e = run(context.Background(), bad, limits)
		if e == nil || r.Complete {
			t.Fatal("negative range accepted")
		}
	}
}

func TestStationTransferBoundaryAndRejectedSpecificity(t *testing.T) {
	for _, tc := range []struct {
		typ              int
		minimum, arrival int64
	}{{0, 0, 10}, {2, 2, 10}, {2, 3, 20}, {3, 0, 20}} {
		d, b := data(), query()
		d.Stops = append(d.Stops, model.Stop{ID: "station", LocationType: 1, Accessible: model.Yes})
		d.Stops[1].ParentStation = "station"
		trip(&d, "in", []string{"A", "B"}, 2, 5)
		trip(&d, "out", []string{"C", "D"}, 7, 10)
		trip(&d, "direct", []string{"A", "D"}, 6, 20)
		d.Footpaths = []model.Footpath{{ID: "transfer", From: "B", To: "C", Duration: 2, Accessible: model.Yes}}
		d.Transfers = []model.TransferRule{{ID: "parent", FromStop: "station", ToStop: "C", Type: tc.typ, MinSeconds: tc.minimum}}
		b.Walking = &model.WalkingLimits{Transfer: 2}
		b.TransferBuffer = 100
		v, e := validate.New(d)
		if e != nil {
			t.Fatal(e)
		}
		for name, run := range searches(t, d) {
			r, e := run(context.Background(), profilequery.Query{Base: b, End: 3}, limits)
			if e != nil {
				t.Fatal(e)
			}
			for ready := int64(0); ready <= 3; ready++ {
				js, e := r.At(ready)
				if e != nil {
					t.Fatal(e)
				}
				at := b
				at.Departure = ready
				ms := []model.Metrics{}
				for _, j := range js {
					m, e := v.Check(at, j)
					if e != nil {
						t.Fatal(name, e)
					}
					ms = append(ms, m.Metrics)
				}
				arrival := tc.arrival
				if ready > 2 {
					arrival = 20
				}
				want := []int64{inf, 20, arrival, arrival}
				if got := objectives(ms, 3); !reflect.DeepEqual(got, want) {
					t.Fatal(name, tc, ready, got, want)
				}
			}
		}
		d.Transfers[0].ToTrip = "out"
		if _, e := profilecsa.New(d); e == nil {
			t.Fatal("profile CSA accepted unsupported trip selector")
		}
		if _, e := raptor.New(d); e == nil {
			t.Fatal("range RAPTOR accepted unsupported trip selector")
		}
	}
}

func TestWindowPartitionDegeneracyAndConcurrentReuse(t *testing.T) {
	d, b := data(), query()
	b.Walking = &model.WalkingLimits{}
	trip(&d, "early", []string{"A", "D"}, 2, 8)
	trip(&d, "late", []string{"A", "D"}, 5, 10)
	for _, bounds := range [][2]int64{{0, 6}, {0, 2}, {3, 6}, {5, 5}, {6, 6}} {
		q := profilequery.Query{Base: b, End: bounds[1]}
		q.Base.Departure = bounds[0]
		check(t, d, q, 2)
	}
	for name, run := range searches(t, d) {
		var wg sync.WaitGroup
		results := make(chan profilequery.Result, 8)
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func(i int) {
				defer wg.Done()
				q := profilequery.Query{Base: b, End: 6}
				q.Base.Departure = int64(i % 3)
				r, e := run(context.Background(), q, limits)
				if e != nil {
					r.Error = e.Error()
				}
				results <- r
			}(i)
		}
		wg.Wait()
		close(results)
		for r := range results {
			if !r.Complete || r.Error != "" {
				t.Fatal(name, r.Error)
			}
			js, e := r.At(5)
			if e != nil {
				t.Fatal(e)
			}
			at := b
			at.Departure = 5
			ms := []model.Metrics{}
			for _, j := range js {
				ms = append(ms, metrics(t, d, at, j))
			}
			if !reflect.DeepEqual(objectives(ms, 3), []int64{inf, 10, 10, 10}) {
				t.Fatal(name, ms)
			}
		}
		bad := profilequery.Query{Base: b, End: 6}
		bad.Base.MaxWalkSeconds = 0
		bad.Base.Walking = &model.WalkingLimits{Access: 10}
		r, e := run(context.Background(), bad, limits)
		if e == nil || r.Complete {
			t.Fatal("binding resource accepted")
		}
	}
	r, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	small := limits
	small.MaxDepartures = 1
	out, e := r.SearchRange(context.Background(), profilequery.Query{Base: b, End: 6}, small)
	if e == nil || out.Complete {
		t.Fatal("departure budget silently truncates")
	}
	b.Destination = b.Origin
	check(t, d, profilequery.Query{Base: b, End: 6}, 2)
}
func FuzzIndependentProfileWindow(f *testing.F) {
	for _, s := range []uint64{0, 3, 8, 31, 90} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s uint64) { d, q := generated(s); q.End = 3; check(t, d, q, 7) })
}
