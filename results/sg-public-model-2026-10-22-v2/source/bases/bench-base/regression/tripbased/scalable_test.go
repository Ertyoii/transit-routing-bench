package tripbased_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"reflect"
	"slices"
	"sync"
	"testing"
)

func scalableConfig() tripbased.ScalableConfig {
	return tripbased.ScalableConfig{Patterns: patternConfig(), MaxClusterSize: 3, MaxDirectArcs: 10000, MaxProfileRuns: 10000, MaxProfileLabels: 10000}
}
func scalableCompare(t testing.TB, d model.Dataset, x *tripbased.ScalableIndex, q model.Query, want []int64) {
	t.Helper()
	r, e := x.Search(context.Background(), q)
	if e != nil || !r.Complete {
		t.Fatalf("STP %v data=%+v q=%+v", e, d, q)
	}
	got := objectives(reconstructed(t, d, q, r.Journeys), q.MaxBoardings)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("STP want%v got%v data=%+v q=%+v graph=%+v", want, got, d, q, r.Graph)
	}
}
func TestScalableIndependentWholeWords(t *testing.T) {
	words, patterns := 0, 0
	for seed := uint64(0); seed < 320; seed++ {
		d, q := generated(seed)
		d.Transfers = nil
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q = flashQuery(q)
		ms, n := fullWords(d, q, 7)
		words += n
		for _, size := range []int{3, len(d.Stops)} {
			cfg := scalableConfig()
			cfg.MaxClusterSize = size
			x, e := tripbased.BuildScalable(context.Background(), d, cfg)
			if e != nil {
				t.Fatalf("seed%d: %v data=%+v", seed, e, d)
			}
			scalableCompare(t, d, x, q, objectives(ms, q.MaxBoardings))
			s := x.Snapshot()
			for _, store := range []tripbased.PatternSnapshot{s.Local, s.Border} {
				patterns += store.Stats.Patterns
				for _, w := range store.Witnesses {
					wq := flashQuery(query())
					wq.Origin = w.Source
					wq.Destination = w.Target
					wq.Departure = w.Departure
					wq.MaxBoardings = 4
					reconstructed(t, d, wq, []model.Journey{w.Journey})
				}
			}
		}
	}
	t.Logf("320 whole-word universes; %d unpruned words; two cluster sizes; %d pattern witnesses", words, patterns)
}
func TestScalableBordersAndNonconvex(t *testing.T) {
	// A is not adjacent to an elementary crossing. It must still be a border;
	// otherwise the one-boarding A-D option is lost to a faster B-D local choice.
	d := data()
	trip(&d, "blue", []string{"A", "B", "D"}, 0, 5, 5, 60)
	trip(&d, "green", []string{"B", "D"}, 6, 46)
	c := scalableConfig()
	c.Partition = map[string]int{"A": 0, "B": 0, "C": 0, "D": 1, "X": 1, "Y": 1}
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	q := flashQuery(query())
	q.LatestArrival = 100
	scalableCompare(t, d, x, q, []int64{inf, 60, 46, 46})
	if !slices.Contains(x.Snapshot().Borders, "A") {
		t.Fatal("through-vehicle source not border")
	}
	// Source and target in one non-convex cluster: transferring outside wins.
	d = data()
	trip(&d, "out", []string{"A", "D"}, 0, 2)
	trip(&d, "back", []string{"D", "B"}, 3, 4)
	trip(&d, "local", []string{"A", "B"}, 0, 20)
	x, e = tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	q.Destination = "B"
	scalableCompare(t, d, x, q, []int64{inf, 20, 4, 4})
	// An unsplit ride leaves/reenters the same cluster at no extra boarding.
	d = data()
	trip(&d, "loop", []string{"A", "D", "B"}, 0, 1, 2, 3)
	x, e = tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	q.MaxBoardings = 1
	scalableCompare(t, d, x, q, []int64{inf, 3})
}
func TestScalableOwnershipMetamorphismsAndOrder(t *testing.T) {
	d, q := patternsFixture()
	c := scalableConfig()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	before := x.Snapshot()
	want := []int64{inf, 20, 6, 6}
	s := x.Snapshot()
	for k := range s.Cells {
		s.Cells[k] = 100
	}
	if len(s.Local.Witnesses) > 0 {
		s.Local.Witnesses[0].Journey.Legs = nil
	}
	d.Connections[0].Arrival = 99
	if !reflect.DeepEqual(before, x.Snapshot()) {
		t.Fatal("input/snapshot alias")
	}
	d, q = patternsFixture()
	scalableCompare(t, d, x, q, want)
	for _, size := range []int{1, 2, 4, 8} {
		var wg sync.WaitGroup
		for i := 0; i < size; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				for _, at := range []int64{6, 0, 4, 3, 1} {
					qq := q
					qq.Departure = at
					ms, _ := fullWords(d, qq, 4)
					scalableCompare(t, d, x, qq, objectives(ms, qq.MaxBoardings))
				}
			}()
		}
		wg.Wait()
	}
	slices.Reverse(d.Connections)
	slices.Reverse(d.Stops)
	slices.Reverse(d.Trips)
	y, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, y, q, want)
	if !reflect.DeepEqual(before.Cells, y.Snapshot().Cells) {
		t.Fatal("partition depends on input order")
	}
	for i := range d.Connections {
		d.Connections[i].Departure += 90000
		d.Connections[i].Arrival += 90000
	}
	q.Departure += 90000
	q.LatestArrival += 90000
	y, e = tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, y, q, []int64{inf, 90020, 90006, 90006})
}
func TestScalableWalkingAndFailures(t *testing.T) {
	d, q := patternsFixture()
	d.Footpaths = []model.Footpath{{ID: "cx", From: "C", To: "X", Duration: 750, Accessible: model.Yes}}
	q.Walking = &model.WalkingLimits{Access: 600, Egress: 600, Direct: 600, Transfer: 750}
	q.MaxWalkSeconds = 10000
	q.LatestArrival = 1000
	c := scalableConfig()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, x, q, []int64{inf, 20, 6, 6})
	for _, kind := range []string{"work", "runs", "arcs", "labels", "patterns", "nodes", "edges", "direct", "cluster", "closure"} {
		cc := c
		switch kind {
		case "work":
			cc.Patterns.MaxBuildWork = 1
		case "runs":
			cc.MaxProfileRuns = 1
		case "arcs":
			cc.MaxDirectArcs = 1
		case "labels":
			cc.MaxProfileLabels = 1
		case "patterns":
			cc.Patterns.MaxPatterns = 1
		case "nodes":
			cc.Patterns.MaxNodes = 1
		case "edges":
			cc.Patterns.MaxEdges = 1
		case "direct":
			cc.Patterns.MaxDirectEntries = 1
		case "cluster":
			cc.MaxClusterSize = 1
		case "closure":
			cc.Patterns.Profile.Limits.MaxClosurePaths = 1
		}
		xx, e := tripbased.BuildScalable(context.Background(), d, cc)
		if e == nil || xx.Complete() {
			t.Fatal("accepted partial index", kind)
		}
		r, e := xx.Search(context.Background(), q)
		if e == nil || r.Complete || len(r.Journeys) > 0 {
			t.Fatal("queried partial index", kind)
		}
	}
	for _, kind := range []string{"work", "labels"} {
		cc := c
		if kind == "work" {
			cc.Patterns.MaxQueryWork = 1
		} else {
			cc.Patterns.MaxQueryLabels = 1
		}
		xx, e := tripbased.BuildScalable(context.Background(), d, cc)
		if e != nil {
			t.Fatal(e)
		}
		r, e := xx.Search(context.Background(), q)
		if e == nil || r.Complete || len(r.Journeys) > 0 {
			t.Fatal("accepted partial query", kind)
		}
	}
	c.Partition = map[string]int{"A": 0, "B": 0, "C": 0, "D": 1, "X": 1, "Y": 1}
	xx, e := tripbased.BuildScalable(context.Background(), d, c)
	if e == nil || xx.Complete() {
		t.Fatal("accepted cross-cluster walking")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	xx, e = tripbased.BuildScalable(ctx, d, scalableConfig())
	if e == nil || xx.Complete() {
		t.Fatal("cancelled build")
	}
	for _, self := range []bool{false, true} {
		qq := q
		if self {
			qq.Destination = qq.Origin
		}
		r, e := x.Search(ctx, qq)
		if e == nil || r.Complete {
			t.Fatal("cancelled query")
		}
	}
	for _, kind := range []string{"buffer", "accessibility", "boards", "walk", "legs"} {
		qq := q
		switch kind {
		case "buffer":
			qq.TransferBuffer = 1
		case "accessibility":
			qq.AccessibleOnly = true
		case "boards":
			qq.MaxBoardings = 5
		case "walk":
			qq.MaxWalkSeconds = 0
		case "legs":
			qq.MaxLegs = 1
		}
		r, e := x.Search(context.Background(), qq)
		if e == nil || r.Complete {
			t.Fatal("accepted unsupported query", kind)
		}
	}
}
func FuzzScalableIndependent(f *testing.F) {
	for _, s := range []uint64{0, 1, 71, 319} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, seed uint64) {
		d, q := generated(seed)
		d.Transfers = nil
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q = flashQuery(q)
		ms, _ := fullWords(d, q, 7)
		cfg := scalableConfig()
		switch seed % 4 {
		case 0:
			cfg.BorderSearchMode = "expanded"
		case 1:
			cfg.MaxLocalCacheEntries = 10000
		case 2:
			cfg.MaxLocalCacheEntries = 10000
			cfg.BorderMergeMaxSize = 6
			cfg.BorderReductionPercent = 25
		}
		if seed&4 != 0 {
			cfg.DirectIndex = "pairs"
			cfg.MaxDirectPairs = 100000
		}
		if seed&8 != 0 {
			cfg.BorderStorage = "cluster"
			cfg.MaxClusterDAGs = 10000
		}
		if seed&16 != 0 {
			cfg.DirectIndex = "demand"
			cfg.MaxDirectPairs = 1 + int(seed%31)
		}
		if seed&32 != 0 {
			cfg.BorderSearchMode = "border"
			for i, tr := range d.Trips {
				if seed>>uint(i+6)&1 != 0 {
					cfg.LongDistanceTrips = append(cfg.LongDistanceTrips, tr.ID)
				}
			}
			for _, cn := range d.Connections {
				if slices.Contains(cfg.LongDistanceTrips, cn.TripID) {
					cfg.Hubs = []string{cn.To}
					break
				}
			}
		}
		x, e := tripbased.BuildScalable(context.Background(), d, cfg)
		if e != nil {
			t.Fatal(e)
		}
		scalableCompare(t, d, x, q, objectives(ms, q.MaxBoardings))
	})
}
