package reviewchallenge

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand/v2"
	"reflect"
	"slices"
	"sort"
	"testing"

	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/validate"
)

type point struct {
	Arrival   int64
	Boardings int
	Walk      int64
}

func metrics(t *testing.T, d model.Dataset, q model.Query, js []model.Journey) []point {
	t.Helper()
	v, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	out := []point{}
	for _, j := range js {
		r, e := v.Check(q, j)
		if e != nil {
			t.Fatalf("invalid witness: %v %+v", e, j)
		}
		out = append(out, point{r.Metrics.Arrival, r.Metrics.Boardings, r.Metrics.WalkingSeconds})
	}
	return out
}
func frontier(ps []point, three bool) []point {
	unique := []point{}
	for _, p := range ps {
		if !three {
			p.Walk = 0
		}
		if !slices.Contains(unique, p) {
			unique = append(unique, p)
		}
	}
	out := []point{}
	for i, p := range unique {
		keep := true
		for j, a := range unique {
			if i != j && a.Arrival <= p.Arrival && a.Boardings <= p.Boardings && a.Walk <= p.Walk {
				keep = false
				break
			}
		}
		if keep {
			out = append(out, p)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.Boardings != b.Boardings {
			return a.Boardings < b.Boardings
		}
		if a.Arrival != b.Arrival {
			return a.Arrival < b.Arrival
		}
		return a.Walk < b.Walk
	})
	return out
}
func challenge(t *testing.T, d model.Dataset, q model.Query) {
	t.Helper()
	o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 200000, MaxJourneys: 20000})
	if e != nil || !o.Complete {
		t.Fatalf("oracle inconclusive %v", e)
	}
	expected := metrics(t, d, q, o.Journeys)
	x, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	actual := map[string]any{}
	for _, early := range []bool{false, true} {
		cfg := raptor.MultiConfig{Criterion: "walking_seconds", MaxLabels: 100000, MaxConnectionVisits: 100000, EarlyPruning: early}
		r, e := x.SearchMulti(context.Background(), q, cfg)
		if e != nil || !r.Complete {
			t.Fatal(e, r)
		}
		points := metrics(t, d, q, r.Journeys)
		got := frontier(points, true)
		if len(points) != len(got) {
			t.Fatalf("3D returned duplicate or dominated vectors: %v", points)
		}
		want := frontier(expected, true)
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("3D early%v want%v got%v d%+v q%+v", early, want, got, d, q)
		}
		actual[fmt.Sprint("3D-", early)] = r
	}
	a, e := x.Search(context.Background(), q)
	if e != nil || !a.Complete {
		t.Fatal(e)
	}
	b, s, e := x.SearchEarlyPruning(context.Background(), q)
	if e != nil || !b.Complete {
		t.Fatal(e)
	}
	for _, js := range [][]model.Journey{a.Journeys, b.Journeys} {
		points := metrics(t, d, q, js)
		got, want := frontier(points, false), frontier(expected, false)
		if len(points) != len(got) {
			t.Fatalf("2D returned duplicate or dominated vectors: %v", points)
		}
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("2D want%v got%v d%+v q%+v", want, got, d, q)
		}
	}
	actual["2D-false"] = a
	actual["2D-true"] = b
	actual["2D-pruning-stats"] = s
	raw, _ := json.Marshal(map[string]any{"dataset": d, "query": q, "oracle": o, "actual": actual})
	t.Logf("CASE_JSON %s", raw)
}
func base() (model.Dataset, model.Query) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "independent-early-review", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17"}
	for _, s := range []string{"A", "B", "C", "D", "X"} {
		d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
	}
	q := model.Query{ID: "review", Origin: "A", Destination: "D", Departure: 0, LatestArrival: 24, MaxBoardings: 3, MaxLegs: 64, MaxWalkSeconds: 30, Walking: &model.WalkingLimits{Access: 5, Transfer: 5, Egress: 5, Direct: 5}}
	return d, q
}
func trip(d *model.Dataset, id string, stops []string, times ...int64) {
	d.Trips = append(d.Trips, model.Trip{ID: id, Accessible: model.Yes})
	for i := 0; i < len(stops)-1; i++ {
		d.Connections = append(d.Connections, model.Connection{ID: fmt.Sprintf("%s-%d", id, i), TripID: id, Sequence: i, From: stops[i], To: stops[i+1], Departure: times[i*2], Arrival: times[i*2+1], Pickup: true, Dropoff: true})
	}
}
func walk(d *model.Dataset, from, to string, duration int64) {
	d.Footpaths = append(d.Footpaths, model.Footpath{ID: from + to, From: from, To: to, Duration: duration, Accessible: model.Yes})
}

func TestIndependentAdversarialCorpus(t *testing.T) {
	for seed := uint64(100001); seed < 100161; seed++ {
		rng := rand.New(rand.NewPCG(seed, 37219))
		d, q := base()
		q.ID = fmt.Sprint(seed)
		q.MaxBoardings = 1 + rng.IntN(3)
		if seed%10 == 0 {
			q.MaxBoardings = 0
		}
		q.Departure = 0
		q.LatestArrival = 20
		q.TransferBuffer = int64(rng.IntN(4))
		q.Walking = &model.WalkingLimits{Access: int64(rng.IntN(5)), Transfer: int64(rng.IntN(5)), Egress: int64(rng.IntN(5)), Direct: int64(rng.IntN(5))}
		stops := []string{"A", "B", "C", "D", "X"}
		q.Destination = stops[1+rng.IntN(4)]
		// Includes repeated stops, same-pattern FIFO and overtaking trips.
		trip(&d, "loop", []string{"A", "B", "A"}, 0, 3, 3, 6)
		trip(&d, "loop-variant", []string{"A", "B", "A"}, 1, 2, 4, 5)
		trip(&d, "slow-seated", []string{"A", "D"}, 0, 18)
		trip(&d, "finish", []string{"C", "D"}, 10, 12)
		walk(&d, "B", "C", 1+int64(rng.IntN(3)))
		for j := 0; j < 3; j++ {
			f := rng.IntN(5)
			to := (f + 1 + rng.IntN(4)) % 5
			dep := int64(rng.IntN(15))
			trip(&d, fmt.Sprint("single", j), []string{stops[f], stops[to]}, dep, dep+1+int64(rng.IntN(4)))
		}
		for i := range d.Connections {
			d.Connections[i].Pickup = rng.IntN(8) != 0
			d.Connections[i].Dropoff = rng.IntN(8) != 0
		}
		for i := 0; i < 5; i++ {
			f, to := rng.IntN(5), rng.IntN(5)
			if f == to {
				continue
			}
			exists := false
			for _, w := range d.Footpaths {
				if w.From == stops[f] && w.To == stops[to] {
					exists = true
				}
			}
			if !exists {
				walk(&d, stops[f], stops[to], 1+int64(rng.IntN(4)))
			}
		}
		if seed%3 != 0 {
			typ := 2
			if seed%3 == 1 {
				typ = 3
			}
			d.Transfers = []model.TransferRule{{ID: "one-rule", FromStop: "B", ToStop: "C", Type: typ, MinSeconds: 0}}
			if typ == 2 {
				d.Transfers[0].MinSeconds = 7
			}
		}
		if seed%4 == 0 {
			q.AccessibleOnly = true
			d.Stops[1].Accessible = model.Unknown
			d.Trips[2].Accessible = model.Unknown
		}
		challenge(t, d, q)
		if seed%20 == 0 {
			slices.Reverse(d.Stops)
			slices.Reverse(d.Trips)
			slices.Reverse(d.Connections)
			slices.Reverse(d.Footpaths)
			challenge(t, d, q)
			for i := range d.Connections {
				d.Connections[i].Departure += 90000
				d.Connections[i].Arrival += 90000
			}
			q.Departure += 90000
			q.LatestArrival += 90000
			challenge(t, d, q)
		}
	}
}

func TestIndependentEqualityAndInfeasibleBounds(t *testing.T) {
	d0, q0 := base()
	trip(&d0, "through", []string{"A", "X", "D"}, 0, 2, 8, 10)
	trip(&d0, "unused", []string{"B", "C"}, 15, 16)
	walk(&d0, "A", "D", 4)
	walk(&d0, "X", "B", 5)
	challenge(t, d0, q0) // dominated walking tail must not terminate the onboard continuation
	d, q := base()
	trip(&d, "seated", []string{"A", "D"}, 0, 4)
	walk(&d, "A", "D", 4)
	challenge(t, d, q) // equal arrival, less walking vs fewer boardings
	d, q = base()
	trip(&d, "only", []string{"B", "D"}, 5, 6)
	walk(&d, "A", "D", 4)
	walk(&d, "A", "B", 5)
	q.Walking.Direct = 3
	challenge(t, d, q) // infeasible direct walk cannot seed bound
	d, q = base()
	trip(&d, "incumbent", []string{"A", "D"}, 0, 10)
	trip(&d, "in", []string{"A", "X"}, 0, 2)
	trip(&d, "finish", []string{"C", "D"}, 4, 5)
	walk(&d, "X", "B", 1)
	walk(&d, "X", "C", 2)
	d.Transfers = []model.TransferRule{{ID: "prohibited-short", FromStop: "X", ToStop: "B", Type: 3}}
	challenge(t, d, q)
	// A directly infeasible egress must not bound a longer legal transfer tail.
	d, q = base()
	trip(&d, "in", []string{"A", "X"}, 0, 2)
	trip(&d, "finish", []string{"C", "D"}, 6, 8)
	walk(&d, "X", "D", 2)
	walk(&d, "X", "C", 4)
	q.Walking.Egress = 1
	challenge(t, d, q)
}
