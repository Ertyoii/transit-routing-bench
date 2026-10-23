package tripbased_test

import (
	"context"
	"reflect"
	"slices"
	"sync"
	"testing"

	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
)

func trexConfig(levels int) tripbased.TREXConfig {
	return tripbased.TREXConfig{Levels: levels, MaxBoardings: 4, Limits: tripbased.TREXLimits{MaxStops: 100, MaxTrips: 100, MaxInputEdges: 1000, MaxClosurePaths: 10000, MaxWalkSettled: 10000, MaxTransfers: 10000, MaxRuns: 10000, MaxWork: 10000000, MaxWitnesses: 10000, MaxOverlayEntries: 100000, MaxQueuedSegments: 100000, MaxQueryWork: 1000000}}
}
func trexCompare(t testing.TB, d model.Dataset, x *tripbased.TREXIndex, q model.Query, want []int64) {
	t.Helper()
	for name, fn := range map[string]func(context.Context, model.Query) (tripbased.TREXResult, error){"overlay": x.Search, "rank-test": x.SearchRanked, "unranked": x.SearchUnranked} {
		r, e := fn(context.Background(), q)
		if e != nil || !r.Complete {
			t.Fatalf("%s %v q=%+v", name, e, q)
		}
		got := objectives(reconstructed(t, d, q, r.Journeys), q.MaxBoardings)
		if !reflect.DeepEqual(got, want) {
			t.Fatalf("%s want%v got%v dataset=%+v q=%+v snapshot=%+v", name, want, got, d, q, x.Snapshot())
		}
	}
}
func trexFixture() (model.Dataset, model.Query, tripbased.TREXConfig) {
	d := data()
	trip(&d, "in", []string{"A", "B"}, 0, 1)
	trip(&d, "middle", []string{"B", "C"}, 2, 3)
	trip(&d, "out", []string{"C", "D"}, 4, 5)
	trip(&d, "late", []string{"B", "C"}, 2, 20)
	c := trexConfig(2)
	c.Partition = map[string]int{"A": 0, "B": 1, "C": 1, "D": 3, "X": 2, "Y": 2}
	q := flashQuery(query())
	return d, q, c
}
func TestTREXHierarchyLiteral(t *testing.T) {
	d, q, c := trexFixture()
	x, e := tripbased.BuildTREX(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	trexCompare(t, d, x, q, []int64{inf, inf, inf, 5})
	s := x.Snapshot()
	if s.Stats.RankPromotions == 0 || len(s.Witnesses) == 0 {
		t.Fatal("customization unexercised")
	}
	a, e := x.SearchRanked(context.Background(), q)
	if e != nil || a.Stats.RankRejected == 0 {
		t.Fatal("rank test unexercised", e, a)
	}
	b, e := x.Search(context.Background(), q)
	if e != nil || b.Stats.TransferVisits >= a.Stats.TransferVisits || b.Stats.SplitSegments == 0 {
		t.Fatal("overlay skipped no transfers", e, b.Stats, a.Stats)
	}
	work := 0
	for _, p := range s.Phases {
		work += p.Work
	}
	if work != s.Stats.Work {
		t.Fatal("phase ledger", work, s.Stats.Work)
	}
	for _, cap := range []int{s.Stats.Work, s.Stats.Work - 1} {
		cc := c
		cc.Limits.MaxWork = cap
		y, e := tripbased.BuildTREX(context.Background(), d, cc)
		if cap == s.Stats.Work {
			if e != nil {
				t.Fatal("exact budget", e)
			}
		} else if e == nil || y.Complete() {
			t.Fatal("one-short budget accepted")
		}
	}
}
func TestTREXIndependentWords(t *testing.T) {
	count := 0
	for seed := uint64(88001); seed < 88161; seed++ {
		d, q := generated(seed)
		d.Transfers = nil
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q = flashQuery(q)
		ms, n := fullWords(d, q, 7)
		count += n // three positive rides plus one directed walk: seven exhausts this universe.
		for level := 0; level <= 2; level++ {
			x, e := tripbased.BuildTREX(context.Background(), d, trexConfig(level))
			if e != nil {
				t.Fatal(seed, level, e)
			}
			trexCompare(t, d, x, q, objectives(ms, q.MaxBoardings))
		}
	}
	t.Logf("160 complete whole-word universes; %d words; three levels and three query modes", count)
}
func FuzzTREXIndependent(f *testing.F) {
	for _, seed := range []uint64{88001, 88007, 88160} {
		f.Add(seed)
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
		x, e := tripbased.BuildTREX(context.Background(), d, trexConfig(2))
		if e != nil {
			t.Fatal(e)
		}
		trexCompare(t, d, x, q, objectives(ms, q.MaxBoardings))
	})
}
func TestTREXOwnershipTimeAndBatchOrder(t *testing.T) {
	d, q, c := trexFixture()
	x, e := tripbased.BuildTREX(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	before := x.Snapshot()
	for _, s := range [][]int64{{0, 2, 0, 4}, {4, 0, 2, 0}, {0}, {2, 0, 4}} {
		for _, dep := range s {
			qq := q
			qq.Departure = dep
			want := []int64{inf, inf, inf, inf}
			if dep == 0 {
				want[3] = 5
			}
			trexCompare(t, d, x, qq, want)
		}
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, e := x.Search(context.Background(), q)
			if e != nil || !r.Complete {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
	copySnap := x.Snapshot()
	copySnap.Config.Partition["A"] = 3
	copySnap.Partition.Cells["B"] = 2
	copySnap.Lines[0][0] = "bad"
	copySnap.Transfers[0].Rank = 99
	copySnap.Witnesses[0].Journey.Legs = nil
	c.Partition["A"] = 3
	if !reflect.DeepEqual(before, x.Snapshot()) {
		t.Fatal("mutable alias/query state")
	}
	perm := d.Clone()
	slices.Reverse(perm.Stops)
	slices.Reverse(perm.Connections)
	slices.Reverse(perm.Trips)
	c = before.Config
	y, e := tripbased.BuildTREX(context.Background(), perm, c)
	if e != nil {
		t.Fatal(e)
	}
	after := y.Snapshot()
	// Builds cannot reproduce elapsed time or allocator measurements. Compare
	// every semantic field and work counter, including the newly exposed level
	// telemetry and phase work, while excluding only those measurements.
	for _, snapshot := range []*tripbased.TREXSnapshot{&before, &after} {
		for name, phase := range snapshot.Phases {
			phase.ElapsedNS = 0
			phase.AllocatedBytes = 0
			snapshot.Phases[name] = phase
		}
		for i := range snapshot.Stats.Levels {
			snapshot.Stats.Levels[i].ElapsedNS = 0
			snapshot.Stats.Levels[i].AllocatedBytes = 0
		}
	}
	if !reflect.DeepEqual(before, after) {
		t.Fatal("input-order-dependent index")
	}
	for i := range d.Connections {
		d.Connections[i].Departure += 90000
		d.Connections[i].Arrival += 90000
	}
	q.Departure += 90000
	q.LatestArrival += 90000
	z, e := tripbased.BuildTREX(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	trexCompare(t, d, z, q, []int64{inf, inf, inf, 90005})
}
func TestTREXBoundaries(t *testing.T) {
	d, q, c := trexFixture()
	for _, kind := range []string{"work", "runs", "transfers", "closure", "settled", "overlay", "witness", "network", "input", "queue"} {
		cc := c
		dd := d.Clone()
		switch kind {
		case "work":
			cc.Limits.MaxWork = 1
		case "runs":
			cc.Limits.MaxRuns = 1
		case "transfers":
			cc.Limits.MaxTransfers = 1
		case "closure":
			cc.Limits.MaxClosurePaths = 1
		case "settled":
			cc.Limits.MaxWalkSettled = 1
		case "overlay":
			cc.Limits.MaxOverlayEntries = 1
		case "witness":
			cc.Limits.MaxWitnesses = 1
			trip(&dd, "second-entry", []string{"X", "B"}, 0, 1)
		case "network":
			cc.Limits.MaxStops = 1
		case "input":
			cc.Limits.MaxInputEdges = 1
		case "queue":
			cc.Limits.MaxQueuedSegments = 1
		}
		x, e := tripbased.BuildTREX(context.Background(), dd, cc)
		if e == nil || x.Complete() {
			t.Fatal("budget accepted", kind)
		}
		r, e := x.Search(context.Background(), q)
		if e == nil || r.Complete {
			t.Fatal("partial query", kind)
		}
	}
	x, e := tripbased.BuildTREX(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	for _, kind := range []string{"buffer", "accessible", "boards", "walktotal", "legs"} {
		qq := q
		switch kind {
		case "buffer":
			qq.TransferBuffer = 1
		case "accessible":
			qq.AccessibleOnly = true
		case "boards":
			qq.MaxBoardings = 5
		case "walktotal":
			qq.MaxWalkSeconds = 0
		case "legs":
			qq.MaxLegs = 1
		}
		r, e := x.Search(context.Background(), qq)
		if e == nil || r.Complete {
			t.Fatal("capability accepted", kind)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	q.Destination = q.Origin
	r, e := x.Search(ctx, q)
	if e == nil || r.Complete || len(r.Journeys) > 0 {
		t.Fatal("cancelled self accepted")
	}
}

func TestTREXAdversarialOccurrencesAndRoles(t *testing.T) {
	d := data()
	trip(&d, "loop", []string{"A", "B", "A", "C", "B", "D"}, 1, 3, 4, 6, 7, 9, 10, 12, 13, 15)
	trip(&d, "tie", []string{"A", "B", "A", "C", "B", "D"}, 1, 2, 3, 5, 7, 9, 10, 11, 13, 15)
	trip(&d, "overtake", []string{"A", "B", "A", "C", "B", "D"}, 2, 3, 4, 5, 6, 8, 9, 11, 12, 14)
	for _, level := range []int{0, 1, 2} {
		x, e := tripbased.BuildTREX(context.Background(), d, trexConfig(level))
		if e != nil {
			t.Fatal(e)
		}
		q := flashQuery(query())
		q.Departure = 5
		q.MaxBoardings = 1
		trexCompare(t, d, x, q, []int64{inf, 14})
	}
	// An intermediate walk may exceed endpoint600. Neither endpoint limits nor
	// the presentation penalty changes this feasible transfer.
	d = data()
	trip(&d, "in", []string{"A", "B"}, 0, 1)
	trip(&d, "out", []string{"C", "D"}, 751, 752)
	d.Footpaths = []model.Footpath{{ID: "bc", From: "B", To: "C", Duration: 750, Accessible: model.Yes}}
	q := flashQuery(query())
	q.LatestArrival = 1000
	q.Walking = &model.WalkingLimits{Access: 600, Egress: 600, Transfer: 900, Direct: 600}
	q.MaxWalkSeconds = 3900
	x, e := tripbased.BuildTREX(context.Background(), d, trexConfig(2))
	if e != nil {
		t.Fatal(e)
	}
	trexCompare(t, d, x, q, []int64{inf, inf, 752, 752})
	for _, which := range []string{"transfer", "access", "egress"} {
		qq := q
		w := *q.Walking
		qq.Walking = &w
		switch which {
		case "transfer":
			w.Transfer = 749
		case "access":
			qq.Origin = "B"
		case "egress":
			qq.Destination = "C"
		}
		r, e := x.Search(context.Background(), qq)
		if e == nil || r.Complete {
			t.Fatal("binding cap accepted", which)
		}
	}
	for _, which := range []string{"rules", "pickup", "dropoff", "zero-ride", "zero-walk", "cut-footpath", "missing-leaf"} {
		dd := d.Clone()
		c := trexConfig(2)
		switch which {
		case "rules":
			dd.Transfers = []model.TransferRule{{ID: "no", FromStop: "B", ToStop: "C", Type: 3}}
		case "pickup":
			dd.Connections[0].Pickup = false
		case "dropoff":
			dd.Connections[0].Dropoff = false
		case "zero-ride":
			dd.Connections[0].Arrival = 0
		case "zero-walk":
			dd.Footpaths[0].Duration = 0
		case "cut-footpath":
			c.Partition = map[string]int{"A": 0, "B": 1, "C": 2, "D": 3, "X": 0, "Y": 3}
		case "missing-leaf":
			c.Partition = map[string]int{"A": 0, "B": 0, "C": 0, "D": 0, "X": 0, "Y": 0}
		}
		xx, e := tripbased.BuildTREX(context.Background(), dd, c)
		if e == nil || xx.Complete() {
			t.Fatal("unsupported dataset", which)
		}
	}
	c := trexConfig(2)
	c.Limits.MaxQueryWork = 1
	xx, e := tripbased.BuildTREX(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	r, e := xx.Search(context.Background(), q)
	if e == nil || r.Complete {
		t.Fatal("query work cap")
	}
}
