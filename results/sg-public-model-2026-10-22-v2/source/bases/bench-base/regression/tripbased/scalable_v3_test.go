package tripbased_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/tripbased"
	"reflect"
	"sync"
	"testing"
)

func v3Config(shared, pairs bool) tripbased.ScalableConfig {
	c := scalableConfig()
	if shared {
		c.BorderStorage = "cluster"
		c.MaxClusterDAGs = 10000
	}
	if pairs {
		c.DirectIndex = "pairs"
		c.MaxDirectPairs = 100000
	}
	return c
}
func TestScalableV3IndependentWords(t *testing.T) {
	for seed := uint64(81001); seed < 81081; seed++ {
		d, q := generated(seed)
		d.Transfers = nil
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q = flashQuery(q)
		ms, _ := fullWords(d, q, 7)
		want := objectives(ms, q.MaxBoardings)
		for _, shared := range []bool{false, true} {
			for _, pairs := range []bool{false, true} {
				c := v3Config(shared, pairs)
				c.MaxLocalCacheEntries = 37
				x, e := tripbased.BuildScalable(context.Background(), d, c)
				if e != nil {
					t.Fatal(seed, shared, pairs, e)
				}
				scalableCompare(t, d, x, q, want)
				s := x.Snapshot()
				if s.Stats.ConstructionWork != s.Stats.Work+s.Local.Stats.Work+s.Border.Stats.Work {
					t.Fatal("work ledger")
				}
				if shared && (s.ClusterStats.Patterns != s.Border.Stats.Patterns || len(s.Border.DAGs) != 0) {
					t.Fatal("source DAG retained or missing shared word")
				}
			}
		}
	}
}
func cycleDAGFixture() (model.Dataset, model.Query, tripbased.ScalableConfig) {
	d := data()
	trip(&d, "ab", []string{"A", "B"}, 0, 1)
	trip(&d, "bc", []string{"B", "C"}, 2, 3)
	trip(&d, "cy", []string{"C", "Y"}, 4, 5)
	trip(&d, "xc", []string{"X", "C"}, 10, 11)
	trip(&d, "cb", []string{"C", "B"}, 12, 13)
	trip(&d, "by", []string{"B", "Y"}, 20, 21)
	q := flashQuery(query())
	q.Destination = "Y"
	q.LatestArrival = 40
	c := v3Config(true, true)
	c.Partition = map[string]int{"A": 0, "B": 1, "C": 2, "D": 3, "X": 4, "Y": 5}
	return d, q, c
}
func TestScalableV3CycleAndOwnership(t *testing.T) {
	d, q, c := cycleDAGFixture()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, x, q, []int64{inf, inf, 21, 5})
	q.Origin = "X"
	q.Departure = 10
	scalableCompare(t, d, x, q, []int64{inf, inf, inf, 21})
	s := x.Snapshot()
	if s.ClusterStats.RejectedMerges == 0 {
		t.Fatal("cycle branch not exercised")
	}
	before := x.Snapshot()
	for i := range s.ClusterDAGs {
		for j := range s.ClusterDAGs[i].Stops {
			s.ClusterDAGs[i].Stops[j] = "corrupted"
		}
		s.ClusterDAGs[i].Arcs = nil
	}
	if !reflect.DeepEqual(before, x.Snapshot()) {
		t.Fatal("snapshot aliases graph")
	}
	want, _ := x.Search(context.Background(), q)
	var wg sync.WaitGroup
	errors := make(chan string, 16)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, e := x.Search(context.Background(), q)
			if e != nil || !reflect.DeepEqual(r, want) {
				errors <- "concurrent shared result differs"
			}
		}()
	}
	wg.Wait()
	close(errors)
	for err := range errors {
		t.Error(err)
	}
	// Dataset order does not change direct line identities, greedy graph insertion,
	// or source/target extraction. Batch wrappers use the same immutable index.
	for i, j := 0, len(d.Connections)-1; i < j; i, j = i+1, j-1 {
		d.Connections[i], d.Connections[j] = d.Connections[j], d.Connections[i]
	}
	y, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	r, e := y.Search(context.Background(), q)
	if e != nil || !reflect.DeepEqual(r, want) {
		t.Fatal("input order", e)
	}
}
func TestScalableV3Budgets(t *testing.T) {
	d, q, c := cycleDAGFixture()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	total := x.Snapshot().Stats.ConstructionWork
	cases := []struct {
		name   string
		change func(*tripbased.ScalableConfig)
	}{
		{"pairs", func(c *tripbased.ScalableConfig) { c.MaxDirectPairs = 1 }},
		{"DAGs", func(c *tripbased.ScalableConfig) { c.MaxClusterDAGs = 1 }},
		{"nodes", func(c *tripbased.ScalableConfig) { c.Patterns.MaxNodes = 1 }},
		{"edges", func(c *tripbased.ScalableConfig) { c.Patterns.MaxEdges = 1 }},
		{"aggregate", func(c *tripbased.ScalableConfig) { c.Patterns.MaxBuildWork = total - 1 }},
	}
	for _, v := range cases {
		t.Run(v.name, func(t *testing.T) {
			cfg := c
			v.change(&cfg)
			x, e := tripbased.BuildScalable(context.Background(), d, cfg)
			if e == nil || x.Complete() {
				t.Fatal("partial accepted")
			}
			r, e := x.Search(context.Background(), q)
			if e == nil || r.Complete {
				t.Fatal("partial query accepted")
			}
			s := x.Snapshot()
			if s.Stats.ConstructionWork != s.Stats.Work+s.Local.Stats.Work+s.Border.Stats.Work || s.Stats.ConstructionWork > cfg.Patterns.MaxBuildWork {
				t.Fatal("ledger")
			}
		})
	}
	c.Patterns.MaxBuildWork = total
	if _, e := tripbased.BuildScalable(context.Background(), d, c); e != nil {
		t.Fatal("exact cap", e)
	}
}
