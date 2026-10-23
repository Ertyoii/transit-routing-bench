package ultra_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/oracle"
	"github.com/ertyoii/transit-routing-go/corech"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/paper"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/ultra"
	"github.com/ertyoii/transit-routing-go/validate"
	"math/rand/v2"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
)

func limits() ultra.Limits {
	return ultra.Limits{MaxRuns: 10000, MaxConnectionVisits: 10000000, MaxWalkSettled: 1000000, MaxWalkEdges: 5000000, MaxShortcuts: 10000, MaxOutputLegs: 1000000}
}
func config() ultra.Config {
	return ultra.Config{Core: corech.Config{MaximumAverageCoreOutDegree: 14, WitnessSettledPerSearch: 32, MaxContractions: 10000, MaxArcs: 100000, MaxWitnessSettled: 1000000, MaxWitnessEdges: 5000000}, Limits: limits()}
}
func dataset(ids ...string) model.Dataset {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "ultra", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-19"}
	for _, id := range ids {
		d.Stops = append(d.Stops, model.Stop{ID: id, Accessible: model.Yes})
	}
	return d
}
func ride(a, b string, d, aTime int64) model.Connection {
	return model.Connection{From: a, To: b, Departure: d, Arrival: aTime, Pickup: true, Dropoff: true}
}
func add(d *model.Dataset, id string, cs ...model.Connection) {
	d.Trips = append(d.Trips, model.Trip{ID: id, Accessible: model.Yes})
	for i, c := range cs {
		c.ID = fmt.Sprintf("%s:%d", id, i)
		c.TripID = id
		c.Sequence = i
		d.Connections = append(d.Connections, c)
	}
}
func walk(d *model.Dataset, id, a, b string, n int64) {
	d.Footpaths = append(d.Footpaths, model.Footpath{ID: id, From: a, To: b, Duration: n, Accessible: model.Yes})
}
func query(a, b string, start, end int64) model.Query {
	return model.Query{ID: "q", Origin: a, Destination: b, Departure: start, LatestArrival: end, MaxBoardings: 3, MaxLegs: 128, MaxWalkSeconds: 1200 + 2*(end-start), Walking: &model.WalkingLimits{Access: 600, Egress: 600, Direct: 600, Transfer: end - start}}
}
func vectors(t testing.TB, d model.Dataset, q model.Query, js []model.Journey) []int64 {
	t.Helper()
	checker, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	a := make([]int64, q.MaxBoardings+1)
	for i := range a {
		a[i] = paper.Infinity
	}
	for _, j := range js {
		v, e := checker.Check(q, j)
		if e != nil {
			t.Fatalf("invalid whole itinerary: %v %+v", e, j)
		}
		for b := v.Metrics.Boardings; b < len(a); b++ {
			a[b] = min(a[b], v.Metrics.Arrival)
		}
	}
	return a
}
func compare(t testing.TB, d model.Dataset, x *ultra.Index, q model.Query) {
	t.Helper()
	want, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 2000000, MaxJourneys: 1000000})
	if e != nil || !want.Complete {
		t.Fatal("independent complete universe required", e)
	}
	expected := vectors(t, d, q, want.Journeys)
	got, e := x.Search(context.Background(), q, limits())
	if e != nil || !got.Complete {
		t.Fatal("ULTRA incomplete", e)
	}
	if actual := vectors(t, d, q, got.Journeys); !reflect.DeepEqual(actual, expected) {
		t.Fatalf("ULTRA got %v want %v; query=%+v dataset=%+v shortcuts=%+v", actual, expected, q, d, x.Snapshot().Shortcuts)
	}
	base, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	br, e := base.Search(context.Background(), q)
	if e != nil || !br.Complete {
		t.Fatal(e)
	}
	if actual := vectors(t, d, q, br.Journeys); !reflect.DeepEqual(actual, expected) {
		t.Fatalf("baseline %v != %v", actual, expected)
	}
}
func support(t testing.TB, d model.Dataset, x *ultra.Index) {
	t.Helper()
	s := x.Snapshot()
	if !s.Complete || len(s.Runs) != s.PlannedRuns {
		t.Fatal("incomplete departure coverage", s.Error)
	}
	for _, r := range s.Runs {
		if !r.Complete {
			t.Fatal(r)
		}
	}
	for _, sc := range s.Shortcuts {
		q := query(sc.Source, sc.Target, sc.Departure, model.MaxServiceSecond)
		q.MaxWalkSeconds = model.MaxServiceSecond
		q.Walking = &model.WalkingLimits{Access: 600, Egress: 600, Transfer: model.MaxServiceSecond, Direct: 600}
		checker, e := validate.New(d)
		if e != nil {
			t.Fatal(e)
		}
		v, e := checker.Check(q, sc.Candidate)
		if e != nil || v.Metrics.Boardings != 2 {
			t.Fatal("invalid supporting candidate", e, sc)
		}
		edges := map[string]model.Footpath{}
		for _, e := range d.Footpaths {
			edges[e.ID] = e
		}
		at, total := sc.From, int64(0)
		for _, id := range sc.RawEdges {
			e, ok := edges[id]
			if !ok || e.From != at {
				t.Fatal("bad raw shortcut", sc)
			}
			at = e.To
			total += e.Duration
		}
		if at != sc.To || total != sc.Duration {
			t.Fatal(sc)
		}
	}
}
func generated(seed uint64) model.Dataset {
	r := rand.New(rand.NewPCG(seed, seed+97))
	n := 3 + r.IntN(3)
	ids := []string{}
	for i := 0; i < n; i++ {
		ids = append(ids, fmt.Sprintf("s%d", i))
	}
	d := dataset(ids...)
	for i := 0; i < n; i++ {
		if r.IntN(2) == 0 {
			j := r.IntN(n - 1)
			if j >= i {
				j++
			}
			walk(&d, fmt.Sprintf("w%d", i), ids[i], ids[j], 2+int64(r.IntN(4)))
		}
	}
	for i := 0; i < 4; i++ {
		a := r.IntN(n)
		b := r.IntN(n - 1)
		if b >= a {
			b++
		}
		dep := int64(r.IntN(12))
		arr := dep + 1 + int64(r.IntN(3))
		cs := []model.Connection{ride(ids[a], ids[b], dep, arr)}
		if r.IntN(2) == 0 {
			z := r.IntN(n - 1)
			if z >= b {
				z++
			}
			cs = append(cs, ride(ids[b], ids[z], arr+1, arr+3))
		}
		add(&d, fmt.Sprintf("t%d", i), cs...)
	}
	return d
}
func TestIndependentCompleteTinyUniverses(t *testing.T) {
	count := 0
	for seed := uint64(0); seed < 192; seed++ {
		d := generated(seed)
		x, e := ultra.Build(context.Background(), d, config())
		if e != nil {
			t.Fatal(seed, e)
		}
		support(t, d, x)
		for _, a := range d.Stops {
			for _, b := range d.Stops {
				for _, dep := range []int64{0, 4} {
					compare(t, d, x, query(a.ID, b.ID, dep, 18))
					count++
				}
			}
		}
	}
	t.Logf("192 networks; %d complete independent query universes", count)
}
func TestTimetableInitialAndFinalWitnessesRemoveShortcut(t *testing.T) {
	for _, kind := range []string{"none", "one-trip", "initial", "final"} {
		d := dataset("A", "B", "C", "D", "X", "Y")
		add(&d, "first", ride("A", "B", 1, 2))
		add(&d, "second", ride("C", "D", 4, 5))
		walk(&d, "bc", "B", "C", 1)
		switch kind {
		case "one-trip":
			add(&d, "witness", ride("A", "D", 1, 4))
		case "initial":
			walk(&d, "ax", "A", "X", 1)
			add(&d, "witness", ride("X", "D", 3, 4))
		case "final":
			add(&d, "witness", ride("A", "Y", 1, 3))
			walk(&d, "yd", "Y", "D", 1)
		}
		x, e := ultra.Build(context.Background(), d, config())
		if e != nil {
			t.Fatal(e)
		}
		want := 0
		if kind == "none" {
			want = 1
		}
		if len(x.Snapshot().Shortcuts) != want {
			t.Fatalf("%s shortcuts=%+v", kind, x.Snapshot().Shortcuts)
		}
		compare(t, d, x, query("A", "D", 1, 10))
		support(t, d, x)
	}
}
func TestBoundedAccessCounterexampleIsRejected(t *testing.T) {
	d := dataset("A", "B", "C", "D", "X")
	add(&d, "first", ride("A", "B", 1, 2))
	add(&d, "second", ride("C", "D", 605, 606))
	add(&d, "witness", ride("X", "D", 602, 603))
	walk(&d, "bc", "B", "C", 1)
	walk(&d, "ax", "A", "X", 601)
	x, e := ultra.Build(context.Background(), d, config())
	if e != nil {
		t.Fatal(e)
	}
	if len(x.Snapshot().Shortcuts) != 0 {
		t.Fatal("fixture did not exhibit unrestricted witness pruning")
	}
	q := query("A", "D", 1, 611)
	r, e := x.Search(context.Background(), q, limits())
	if e == nil || r.Complete || !strings.Contains(e.Error(), "access cap") {
		t.Fatal(r, e)
	}
	o, e := oracle.Enumerate(context.Background(), d, q, oracle.Limits{MaxStates: 10000, MaxJourneys: 10000})
	if e != nil || !o.Complete {
		t.Fatal(e)
	}
	if v := vectors(t, d, q, o.Journeys); v[2] != 606 {
		t.Fatal(v)
	}
}
func TestThreeTripDecompositionAndMetamorphisms(t *testing.T) {
	d := dataset("s", "a", "b", "c", "cprime", "d", "e", "t")
	add(&d, "1", ride("s", "a", 0, 1))
	add(&d, "2", ride("b", "c", 2, 3))
	add(&d, "3", ride("cprime", "d", 4, 5))
	add(&d, "4", ride("e", "t", 7, 8))
	for _, e := range [][2]string{{"a", "b"}, {"b", "cprime"}, {"c", "d"}, {"d", "e"}} {
		walk(&d, e[0]+e[1], e[0], e[1], 1)
	}
	x, e := ultra.Build(context.Background(), d, config())
	if e != nil {
		t.Fatal(e)
	}
	q := query("s", "t", 0, 10)
	compare(t, d, x, q)
	support(t, d, x)
	r, e := x.Search(context.Background(), q, limits())
	if e != nil {
		t.Fatal(e)
	}
	perm := d.Clone()
	slices.Reverse(perm.Stops)
	slices.Reverse(perm.Trips)
	slices.Reverse(perm.Connections)
	slices.Reverse(perm.Footpaths)
	y, e := ultra.Build(context.Background(), perm, config())
	if e != nil || !reflect.DeepEqual(x.Snapshot(), y.Snapshot()) {
		t.Fatal("input permutation changed preparation", e)
	}
	shifted := d.Clone()
	for i := range shifted.Connections {
		shifted.Connections[i].Departure += 90000
		shifted.Connections[i].Arrival += 90000
	}
	z, e := ultra.Build(context.Background(), shifted, config())
	if e != nil {
		t.Fatal(e)
	}
	sq := q
	sq.Departure += 90000
	sq.LatestArrival += 90000
	compare(t, shifted, z, sq)
	snap := x.Snapshot()
	if len(snap.Shortcuts) > 0 {
		snap.Shortcuts[0].RawEdges[0] = "mutated"
	}
	d.Connections[0].Arrival = 99
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rr, e := x.Search(context.Background(), q, limits())
			if e != nil || !reflect.DeepEqual(rr.Journeys, r.Journeys) {
				t.Error("concurrent/alias change", e)
			}
		}()
	}
	wg.Wait()
}
func TestUnsupportedAndIncompleteNeverCertified(t *testing.T) {
	d := dataset("A", "B", "C", "D")
	add(&d, "first", ride("A", "B", 1, 2))
	add(&d, "second", ride("C", "D", 4, 5))
	walk(&d, "bc", "B", "C", 1)
	for _, kind := range []string{"zero", "pickup", "rule"} {
		bad := d.Clone()
		switch kind {
		case "zero":
			bad.Footpaths[0].Duration = 0
		case "pickup":
			bad.Connections[0].Pickup = false
		case "rule":
			bad.Transfers = []model.TransferRule{{ID: "r", FromStop: "B", ToStop: "C", Type: 3}}
		}
		x, e := ultra.Build(context.Background(), bad, config())
		if e == nil || x.Complete() {
			t.Fatal(kind, e)
		}
	}
	for _, kind := range []string{"runs", "connections", "settled", "edges", "output"} {
		c := config()
		switch kind {
		case "runs":
			c.Limits.MaxRuns = 1
		case "connections":
			c.Limits.MaxConnectionVisits = 1
		case "settled":
			c.Limits.MaxWalkSettled = 1
		case "edges":
			c.Limits.MaxWalkEdges = 1
		case "output":
			c.Limits.MaxOutputLegs = 1
		}
		x, e := ultra.Build(context.Background(), d, c)
		if e == nil || x.Complete() {
			t.Fatal(kind, e)
		}
		r, e := x.Search(context.Background(), query("A", "D", 0, 10), limits())
		if e == nil || r.Complete {
			t.Fatal("accepted partial build")
		}
	}
	x, e := ultra.Build(context.Background(), d, config())
	if e != nil {
		t.Fatal(e)
	}
	q := query("A", "D", 0, 10)
	for _, kind := range []string{"buffer", "accessibility", "transfer"} {
		bad := q
		w := *q.Walking
		bad.Walking = &w
		switch kind {
		case "buffer":
			bad.TransferBuffer = 1
		case "accessibility":
			bad.AccessibleOnly = true
		case "transfer":
			bad.Walking.Transfer = 9
		}
		r, e := x.Search(context.Background(), bad, limits())
		if e == nil || r.Complete {
			t.Fatal(kind, e)
		}
	}
	for _, kind := range []string{"connections", "settled", "output"} {
		l := limits()
		switch kind {
		case "connections":
			l.MaxConnectionVisits = 1
		case "settled":
			l.MaxWalkSettled = 1
		case "output":
			l.MaxOutputLegs = 1
		}
		r, e := x.Search(context.Background(), q, l)
		if e == nil || r.Complete {
			t.Fatal(kind, e)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if r, e := x.Search(ctx, q, limits()); e == nil || r.Complete {
		t.Fatal(e)
	}
	if y, e := ultra.Build(ctx, d, config()); e == nil || y.Complete() {
		t.Fatal(e)
	}
}
func FuzzULTRAIndependent(f *testing.F) {
	for _, s := range []uint64{0, 1, 9, 71, 191} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, s uint64) {
		d := generated(s)
		for _, mode := range []string{ultra.IndependentTrips, ultra.NonOvertakingGroups} {
			c := config()
			c.RouteMode = mode
			base, e := ultra.Build(context.Background(), d, c)
			if e != nil {
				t.Fatal(e)
			}
			compare(t, d, base, query(d.Stops[0].ID, d.Stops[len(d.Stops)-1].ID, 0, 18))
			for _, reuse := range []bool{false, true} {
				c.ActiveRoutes = true
				c.ReuseDepartures = reuse
				x, e := ultra.Build(context.Background(), d, c)
				if e != nil {
					t.Fatal(e)
				}
				if !reuse && !reflect.DeepEqual(shortcutKeys(base), shortcutKeys(x)) {
					t.Fatal("fuzz active-route shortcut equivalence", s, mode, reuse, shortcutKeys(base), shortcutKeys(x))
				}
				support(t, d, x)
				compare(t, d, x, query(d.Stops[0].ID, d.Stops[len(d.Stops)-1].ID, 0, 18))
			}
		}
	})
}

func TestFinalWalkRespectsLatestArrival(t *testing.T) {
	d := dataset("A", "B", "D")
	add(&d, "only", ride("A", "B", 1, 8))
	walk(&d, "bd", "B", "D", 5)
	x, e := ultra.Build(context.Background(), d, config())
	if e != nil {
		t.Fatal(e)
	}
	compare(t, d, x, query("A", "D", 0, 10))
	compare(t, d, x, query("A", "D", 0, 13))
}
