package review_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"math/rand/v2"
	"reflect"
	"testing"
)

const infinity int64 = 1 << 60

func config() tripbased.TREXConfig {
	return tripbased.TREXConfig{Levels: 0, MaxBoardings: 4, Limits: tripbased.TREXLimits{MaxStops: 100, MaxTrips: 100, MaxInputEdges: 1000, MaxClosurePaths: 10000, MaxWalkSettled: 10000, MaxTransfers: 10000, MaxRuns: 10000, MaxWork: 1000000, MaxWitnesses: 10000, MaxOverlayEntries: 100000, MaxQueuedSegments: 100000, MaxQueryWork: 1000000}}
}
func dataset() model.Dataset {
	d := model.Dataset{SchemaVersion: "0.2", ID: "independent-review", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17"}
	for _, s := range []string{"A", "B", "C", "D", "X"} {
		d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
	}
	return d
}
func addTrip(d *model.Dataset, id string, ss []string, ts ...int64) {
	d.Trips = append(d.Trips, model.Trip{ID: id, Accessible: model.Yes})
	for i := 0; i < len(ss)-1; i++ {
		d.Connections = append(d.Connections, model.Connection{ID: fmt.Sprintf("%s/%d", id, i), TripID: id, Sequence: i, From: ss[i], To: ss[i+1], Departure: ts[2*i], Arrival: ts[2*i+1], Pickup: true, Dropoff: true})
	}
}
func query() model.Query {
	return model.Query{ID: "q", Origin: "A", Destination: "D", LatestArrival: 20, MaxBoardings: 3, MaxLegs: 128, MaxWalkSeconds: 100, Walking: &model.WalkingLimits{Access: 4, Transfer: 4, Egress: 4, Direct: 4}}
}

// Independent raw action interpreter: no router, closure, validation, transfer,
// oracle, or frontier helper is imported. A walking block's role is resolved
// only when boarding next or terminating at destination.
type state struct {
	stop             string
	at, block, total int64
	boards, legs     int
	prev             *model.Connection
}

func initial(q model.Query) state { return state{stop: q.Origin, at: q.Departure} }
func ride(s state, c model.Connection, q model.Query) (state, bool) {
	if c.From != s.stop || c.Departure < s.at || c.Arrival > q.LatestArrival {
		return s, false
	}
	stay := s.prev != nil && s.prev.TripID == c.TripID && s.prev.Sequence+1 == c.Sequence
	if !stay {
		cap := q.Walking.Transfer
		if s.boards == 0 {
			cap = q.Walking.Access
		}
		if s.block > cap {
			return s, false
		}
		s.boards++
	}
	s.stop = c.To
	s.at = c.Arrival
	s.block = 0
	s.legs++
	s.prev = &c
	return s, s.boards <= q.MaxBoardings && s.legs <= q.MaxLegs
}
func walk(s state, w model.Footpath, q model.Query) (state, bool) {
	if s.stop != w.From {
		return s, false
	}
	s.stop = w.To
	s.at += w.Duration
	s.block += w.Duration
	s.total += w.Duration
	s.legs++
	s.prev = nil
	cap := max(q.Walking.Transfer, q.Walking.Egress)
	if s.boards == 0 {
		cap = max(q.Walking.Access, q.Walking.Direct)
	}
	return s, s.at <= q.LatestArrival && s.block <= cap && s.total <= q.MaxWalkSeconds && s.legs <= q.MaxLegs
}
func terminal(s state, q model.Query) bool {
	cap := q.Walking.Egress
	if s.boards == 0 {
		cap = q.Walking.Direct
	}
	return s.stop == q.Destination && s.block <= cap
}
func unpruned(t *testing.T, d model.Dataset, q model.Query) []int64 {
	t.Helper()
	out := make([]int64, q.MaxBoardings+1)
	for i := range out {
		out[i] = infinity
	}
	states := 0
	var visit func(state)
	visit = func(s state) {
		states++
		if states > 200000 {
			t.Fatal("independent oracle state limit")
		}
		if s.stop == q.Destination {
			if terminal(s, q) {
				for b := s.boards; b <= q.MaxBoardings; b++ {
					out[b] = min(out[b], s.at)
				}
			}
			return
		}
		for _, c := range d.Connections {
			if n, ok := ride(s, c, q); ok {
				visit(n)
			}
		}
		for _, w := range d.Footpaths {
			if n, ok := walk(s, w, q); ok {
				visit(n)
			}
		}
	}
	visit(initial(q))
	return out
}
func returned(t *testing.T, d model.Dataset, q model.Query, js []model.Journey) []int64 {
	t.Helper()
	out := make([]int64, q.MaxBoardings+1)
	for i := range out {
		out[i] = infinity
	}
	for _, j := range js {
		s := initial(q)
		for _, leg := range j.Legs {
			if s.stop == q.Destination {
				t.Fatal("witness crosses absorbing target", j)
			}
			ok := false
			var n state
			if leg.Kind == "ride" {
				for _, c := range d.Connections {
					if c.ID == leg.Ref && leg.Departure == c.Departure && leg.Arrival == c.Arrival {
						n, ok = ride(s, c, q)
						break
					}
				}
			} else if leg.Kind == "walk" {
				for _, w := range d.Footpaths {
					if w.ID == leg.Ref && leg.Departure == s.at && leg.Arrival == s.at+w.Duration {
						n, ok = walk(s, w, q)
						break
					}
				}
			}
			if !ok {
				t.Fatal("invalid raw witness", j, s, leg)
			}
			s = n
		}
		if !terminal(s, q) {
			t.Fatal("invalid terminal block", j, s)
		}
		for b := s.boards; b <= q.MaxBoardings; b++ {
			out[b] = min(out[b], s.at)
		}
	}
	return out
}
func compare(t *testing.T, d model.Dataset, q model.Query) {
	t.Helper()
	want := unpruned(t, d, q)
	x, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, q.Destination, 5, config())
	if e != nil || !x.Complete() {
		t.Fatal(e)
	}
	r, e := x.Search(context.Background(), q)
	if e != nil || !r.Complete {
		t.Fatal(e)
	}
	if got := returned(t, d, q, r.Journeys); !reflect.DeepEqual(got, want) {
		t.Fatalf("want %v got %v d=%+v q=%+v", want, got, d, q)
	}
}
func TestIndependentCyclicCorpus(t *testing.T) {
	for seed := uint64(0); seed < 240; seed++ {
		t.Run(fmt.Sprint(seed), func(t *testing.T) {
			rng := rand.New(rand.NewPCG(seed, 371))
			d, q := dataset(), query()
			q.Departure = int64(rng.IntN(3))
			q.LatestArrival = 16
			q.MaxBoardings = rng.IntN(4)
			ss := []string{"A", "B", "C", "D", "X"}
			q.Origin = ss[rng.IntN(5)]
			q.Destination = ss[rng.IntN(5)]
			q.Walking = &model.WalkingLimits{Access: int64(rng.IntN(6)), Transfer: int64(rng.IntN(6)), Egress: int64(rng.IntN(6)), Direct: int64(rng.IntN(6))}
			for ti := 0; ti < 4; ti++ {
				stops := []string{ss[rng.IntN(5)]}
				times := []int64{}
				at := int64(rng.IntN(7))
				for j := 0; j < 1+rng.IntN(3); j++ {
					next := ss[rng.IntN(5)]
					if next == stops[len(stops)-1] {
						next = ss[(rng.IntN(4)+1+index(ss, next))%5]
					}
					times = append(times, at, at+1+int64(rng.IntN(3)))
					at = times[len(times)-1] + int64(rng.IntN(3))
					stops = append(stops, next)
				}
				addTrip(&d, fmt.Sprint(ti), stops, times...)
			}
			for wi := 0; wi < 5; wi++ {
				from, to := ss[rng.IntN(5)], ss[rng.IntN(5)]
				if from == to {
					continue
				}
				d.Footpaths = append(d.Footpaths, model.Footpath{ID: fmt.Sprint("w", wi), From: from, To: to, Duration: 1 + int64(rng.IntN(4)), Accessible: model.Yes})
			}
			compare(t, d, q)
		})
	}
}
func index(ss []string, s string) int {
	for i, v := range ss {
		if v == s {
			return i
		}
	}
	panic(s)
}

func TestFIFOAndRoleCapGrid(t *testing.T) {
	d, q := dataset(), query()
	addTrip(&d, "early", []string{"B", "X", "D"}, 3, 4, 4, 8)
	addTrip(&d, "late", []string{"B", "X", "D"}, 5, 6, 6, 9)
	addTrip(&d, "feed", []string{"A", "B"}, 0, 2)
	addTrip(&d, "loop", []string{"A", "B", "A", "C"}, 0, 1, 1, 2, 2, 4)
	addTrip(&d, "overtakes", []string{"B", "X", "D"}, 4, 5, 5, 7)
	d.Footpaths = []model.Footpath{
		{ID: "ac", From: "A", To: "C", Duration: 2, Accessible: model.Yes},
		{ID: "cb", From: "C", To: "B", Duration: 1, Accessible: model.Yes},
		{ID: "bx", From: "B", To: "X", Duration: 2, Accessible: model.Yes},
		{ID: "xd", From: "X", To: "D", Duration: 2, Accessible: model.Yes},
		{ID: "dc", From: "D", To: "C", Duration: 1, Accessible: model.Yes},
		{ID: "ca", From: "C", To: "A", Duration: 1, Accessible: model.Yes},
	}
	x, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, "D", 5, config())
	if e != nil {
		t.Fatal(e)
	}
	if len(x.Snapshot().Index.Lines) == len(d.Trips) {
		t.Fatal("FIFO grouping not exercised")
	}
	for a := int64(0); a <= 5; a++ {
		for tr := int64(0); tr <= 5; tr++ {
			for eg := int64(0); eg <= 5; eg++ {
				for di := int64(0); di <= 5; di++ {
					q.Walking = &model.WalkingLimits{Access: a, Transfer: tr, Egress: eg, Direct: di}
					r, e := x.Search(context.Background(), q)
					if e != nil || !r.Complete {
						t.Fatal(e)
					}
					if got, want := returned(t, d, q, r.Journeys), unpruned(t, d, q); !reflect.DeepEqual(got, want) {
						t.Fatalf("caps %+v want %v got %v", q.Walking, want, got)
					}
				}
			}
		}
	}
}
func TestAbsorbingDetoursAndTargetReboarding(t *testing.T) {
	d, q := dataset(), query()
	addTrip(&d, "feed", []string{"A", "B"}, 0, 1)
	addTrip(&d, "return", []string{"C", "D"}, 5, 6)
	addTrip(&d, "leave-target", []string{"D", "C"}, 2, 3)
	d.Footpaths = []model.Footpath{
		{ID: "bd", From: "B", To: "D", Duration: 1, Accessible: model.Yes},
		{ID: "dc", From: "D", To: "C", Duration: 1, Accessible: model.Yes},
		{ID: "bx", From: "B", To: "X", Duration: 2, Accessible: model.Yes},
		{ID: "xc", From: "X", To: "C", Duration: 2, Accessible: model.Yes},
	}
	q.Walking = &model.WalkingLimits{Transfer: 4}
	compare(t, d, q)
	d.Footpaths = d.Footpaths[:2]
	compare(t, d, q)
}
func TestExplicitCapabilityRejections(t *testing.T) {
	d, q := dataset(), query()
	addTrip(&d, "direct", []string{"A", "D"}, 1, 5)
	for _, kind := range []string{"zero-walk", "zero-outgoing-target", "zero-ride", "rule", "pickup", "dropoff", "ranked", "partition"} {
		dd := d.Clone()
		cfg := config()
		switch kind {
		case "zero-walk":
			dd.Footpaths = []model.Footpath{{ID: "zero", From: "A", To: "B", Duration: 0, Accessible: model.Yes}}
		case "zero-outgoing-target":
			dd.Footpaths = []model.Footpath{{ID: "zero", From: "D", To: "B", Duration: 0, Accessible: model.Yes}}
		case "zero-ride":
			dd.Connections[0].Arrival = dd.Connections[0].Departure
		case "rule":
			dd.Transfers = []model.TransferRule{{ID: "r", FromStop: "B", ToStop: "B", Type: 2, MinSeconds: 1}}
		case "pickup":
			dd.Connections[0].Pickup = false
		case "dropoff":
			dd.Connections[0].Dropoff = false
		case "ranked":
			cfg.Levels = 1
		case "partition":
			cfg.Partition = map[string]int{"A": 0}
		}
		x, e := tripbased.BuildBoundedWalkingTB(context.Background(), dd, "D", 5, cfg)
		if e == nil || x.Complete() {
			t.Fatal("unsupported preparation accepted", kind)
		}
	}
	x, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, "D", 5, config())
	if e != nil {
		t.Fatal(e)
	}
	for _, kind := range []string{"buffer", "accessible", "transfer-ceiling", "destination", "legs", "aggregate"} {
		qq := q
		w := *q.Walking
		qq.Walking = &w
		switch kind {
		case "buffer":
			qq.TransferBuffer = 1
		case "accessible":
			qq.AccessibleOnly = true
		case "transfer-ceiling":
			w.Transfer = 6
		case "destination":
			qq.Destination = "C"
		case "legs":
			qq.MaxLegs = 0
		case "aggregate":
			qq.MaxWalkSeconds = 0
		}
		r, e := x.Search(context.Background(), qq)
		if e == nil || r.Complete {
			t.Fatal("unsupported query accepted", kind)
		}
	}
}

func TestEarliestFIFO(t *testing.T) {
	d, q := dataset(), query()
	q.MaxBoardings = 1
	q.Walking = &model.WalkingLimits{Access: 1}
	addTrip(&d, "early", []string{"B", "D"}, 2, 6)
	addTrip(&d, "late", []string{"B", "D"}, 4, 9)
	d.Footpaths = []model.Footpath{{ID: "access", From: "A", To: "B", Duration: 1, Accessible: model.Yes}}
	compare(t, d, q)
}

func TestTransferCap(t *testing.T) {
	d, q := dataset(), query()
	q.Walking = &model.WalkingLimits{}
	addTrip(&d, "feed", []string{"A", "B"}, 0, 1)
	addTrip(&d, "finish", []string{"C", "D"}, 4, 5)
	d.Footpaths = []model.Footpath{{ID: "transfer", From: "B", To: "C", Duration: 3, Accessible: model.Yes}}
	x, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, "D", 5, config())
	if e != nil {
		t.Fatal(e)
	}
	for _, cap := range []int64{0, 3, 2, 5, 1, 3} {
		q.Walking.Transfer = cap
		r, e := x.Search(context.Background(), q)
		if e != nil || !r.Complete {
			t.Fatal(e)
		}
		if got, want := returned(t, d, q, r.Journeys), unpruned(t, d, q); !reflect.DeepEqual(got, want) {
			t.Fatalf("transfer cap %d want %v got %v", cap, want, got)
		}
	}
}

func TestExplicitlyTwoDNotWalkingPareto(t *testing.T) {
	d, q := dataset(), query()
	q.Walking = &model.WalkingLimits{Access: 2}
	addTrip(&d, "seated", []string{"A", "D"}, 0, 10)
	addTrip(&d, "fast", []string{"B", "D"}, 2, 5)
	d.Footpaths = []model.Footpath{{ID: "access", From: "A", To: "B", Duration: 2, Accessible: model.Yes}}
	x, e := tripbased.BuildBoundedWalkingTB(context.Background(), d, "D", 5, config())
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.Search(context.Background(), q)
	if e != nil || !r.Complete {
		t.Fatal(e)
	}
	if len(r.Journeys) != 1 || len(r.Journeys[0].Legs) != 2 || r.Journeys[0].Legs[0].Ref != "access" {
		t.Fatal("expected only faster walking representative", r)
	}
	if got, want := returned(t, d, q, r.Journeys), unpruned(t, d, q); !reflect.DeepEqual(got, want) {
		t.Fatal(got, want)
	}
}
