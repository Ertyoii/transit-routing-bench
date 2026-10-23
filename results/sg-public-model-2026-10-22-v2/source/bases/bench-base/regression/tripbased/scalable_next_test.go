package tripbased_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"reflect"
	"testing"
)

func TestScalableAggregateConstructionBudget(t *testing.T) {
	d, q := patternsFixture()
	c := scalableConfig()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	s := x.Snapshot()
	sum := s.Stats.Work + s.Local.Stats.Work + s.Border.Stats.Work
	if s.Stats.ConstructionWork != sum || sum <= s.Stats.Work {
		t.Fatal("insertion missing from ledger", s.Stats, s.Local.Stats, s.Border.Stats)
	}
	for _, delta := range []int{-1, 0} {
		c.Patterns.MaxBuildWork = sum + delta
		y, e := tripbased.BuildScalable(context.Background(), d, c)
		z := y.Snapshot()
		if z.Stats.ConstructionWork != z.Stats.Work+z.Local.Stats.Work+z.Border.Stats.Work || z.Stats.ConstructionWork > c.Patterns.MaxBuildWork {
			t.Fatal("aggregate cap exceeded", delta, z.Stats)
		}
		if delta < 0 {
			r, qe := y.Search(context.Background(), q)
			if e == nil || y.Complete() || qe == nil || r.Complete {
				t.Fatal("partial accepted")
			}
		} else {
			if e != nil {
				t.Fatal(e)
			}
			scalableCompare(t, d, y, q, []int64{inf, 20, 6, 6})
		}
	}
}
func TestScalableNoUnusedTransferPreprocessing(t *testing.T) {
	d, q := patternsFixture()
	c := scalableConfig()
	c.Patterns.Profile.Limits.MaxTransfers = 1
	_, e := tripbased.New(context.Background(), d, tripbased.Config{StrictLineOrder: true, MaxTransfers: 1, MaxQueuedSegments: 1000, TransferWalkingLimit: 30})
	if e == nil {
		t.Fatal("fixture no longer exceeds ordinary TB transfer cap")
	}
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal("unused transfer cap prevented direct-only backend", e)
	}
	scalableCompare(t, d, x, q, []int64{inf, 20, 6, 6})
	if x.Snapshot().Local.Backend.Profile != "scalable_tp_direct_backend_without_transfers_v2" {
		t.Fatal("wrong backend provenance")
	}
}
func TestScalableBorderModesAndReduction(t *testing.T) {
	for seed := uint64(0); seed < 80; seed++ {
		d, q := generated(seed)
		d.Transfers = nil
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q = flashQuery(q)
		ms, _ := fullWords(d, q, 7)
		want := objectives(ms, q.MaxBoardings)
		for _, mode := range []string{"expanded", "border", "cached", "reduced"} {
			c := scalableConfig()
			c.BorderSearchMode = "border"
			if mode == "expanded" {
				c.BorderSearchMode = mode
			}
			if mode == "cached" || mode == "reduced" {
				c.MaxLocalCacheEntries = 10000
			}
			if mode == "reduced" {
				c.BorderMergeMaxSize = 6
				c.BorderReductionPercent = 25
			}
			x, e := tripbased.BuildScalable(context.Background(), d, c)
			if e != nil {
				t.Fatal(seed, mode, e)
			}
			scalableCompare(t, d, x, q, want)
			s := x.Snapshot()
			if mode == "border" && len(s.Borders) > 0 && s.Stats.GlobalQueueLabels == 0 {
				t.Fatal("border queue unused")
			}
			if s.Stats.LocalCacheEntries > c.MaxLocalCacheEntries {
				t.Fatal("cache exceeded record budget")
			}
			if s.Stats.BorderAfterReduction > s.Stats.BorderBeforeReduction {
				t.Fatal("border reduction increased boundary")
			}
		}
	}
}
func TestScalableLocalSufficiencyAndMerging(t *testing.T) {
	d := data()
	trip(&d, "local", []string{"A", "B"}, 0, 2)
	trip(&d, "out", []string{"B", "D"}, 3, 4)
	c := scalableConfig()
	c.Partition = map[string]int{"A": 0, "B": 0, "C": 0, "D": 1, "X": 1, "Y": 1}
	c.MaxLocalCacheEntries = 1000
	q := flashQuery(query())
	q.Destination = "B"
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.Search(context.Background(), q)
	if e != nil || !r.Stats.LocalOnly {
		t.Fatal("local sufficiency certificate unused", e, r.Stats)
	}
	scalableCompare(t, d, x, q, []int64{inf, 2, 2, 2})
	d = data()
	trip(&d, "out", []string{"A", "D"}, 0, 2)
	trip(&d, "back", []string{"D", "B"}, 3, 4)
	trip(&d, "local", []string{"A", "B"}, 0, 20)
	x, e = tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	r, e = x.Search(context.Background(), q)
	if e != nil || r.Stats.LocalOnly || x.Snapshot().LocalSufficient[0] {
		t.Fatal("outside improvement incorrectly certified", e)
	}
	scalableCompare(t, d, x, q, []int64{inf, 20, 4, 4})
	c.BorderMergeMaxSize = 6
	c.BorderReductionPercent = 50
	y, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	s := y.Snapshot()
	if s.Stats.BorderClusterMerges != 1 || s.Stats.BorderBeforeReduction != 3 || s.Stats.BorderAfterReduction != 0 {
		t.Fatal("expected full border removal", s.Stats)
	}
	scalableCompare(t, d, y, q, []int64{inf, 20, 4, 4})
	// Published snapshots do not own the live certification or phase-cost maps.
	before := y.Snapshot()
	s.LocalSufficient[0] = false
	for k := range s.PhaseCosts {
		delete(s.PhaseCosts, k)
	}
	if !reflect.DeepEqual(before, y.Snapshot()) {
		t.Fatal("mutable snapshot aliases live state")
	}
}
