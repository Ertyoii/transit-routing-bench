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

func hierarchyFixture() (model.Dataset, model.Query, tripbased.ScalableConfig) {
	d := data()
	trip(&d, "ab", []string{"A", "B"}, 0, 1)
	trip(&d, "bd", []string{"B", "D"}, 2, 3)
	c := v3Config(true, false)
	c.DirectIndex = "demand"
	c.MaxDirectPairs = 7
	c.LongDistanceTrips = []string{"ab", "bd"}
	c.Hubs = []string{"B"}
	c.Partition = map[string]int{"A": 0, "B": 1, "C": 2, "D": 3, "X": 4, "Y": 5}
	q := flashQuery(query())
	q.LatestArrival = 40
	return d, q, c
}
func TestScalableV4HubContinuation(t *testing.T) {
	d, q, c := hierarchyFixture()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, x, q, []int64{inf, inf, 3, 3})
	s := x.Snapshot()
	if !slices.Contains(s.HubAccess["A"], "B") || s.Stats.HubStopLabels == 0 || s.LongDistance.Stats.Patterns == 0 {
		t.Fatal("hub phase not exercised", s.Stats, s.HubAccess)
	}
	if s.Stats.ConstructionWork != s.Stats.Work+s.Local.Stats.Work+s.Border.Stats.Work+s.LongDistance.Stats.Work {
		t.Fatal("hierarchy ledger")
	}
	// A single through vehicle may pass a hub with no second boarding.
	trip(&d, "through", []string{"A", "B", "D"}, 4, 5, 6, 7)
	c.LongDistanceTrips = append(c.LongDistanceTrips, "through")
	q.Departure = 4
	q.MaxBoardings = 1
	x, e = tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, x, q, []int64{inf, 7})
	for i := range d.Connections {
		d.Connections[i].Departure += 90000
		d.Connections[i].Arrival += 90000
	}
	q.Departure += 90000
	q.LatestArrival += 90000
	x, e = tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	scalableCompare(t, d, x, q, []int64{inf, 90007})
}
func TestScalableV4IndependentWords(t *testing.T) {
	for seed := uint64(84001); seed < 84081; seed++ {
		d, q := generated(seed)
		d.Transfers = nil
		for i := range d.Connections {
			d.Connections[i].Pickup = true
			d.Connections[i].Dropoff = true
		}
		q = flashQuery(q)
		ms, _ := fullWords(d, q, 7)
		want := objectives(ms, q.MaxBoardings)
		for mask := 0; mask < 8; mask++ {
			c := v3Config(mask&1 != 0, false)
			c.MaxLocalCacheEntries = 17
			c.DirectIndex = "demand"
			c.MaxDirectPairs = 1 + mask*7
			for i, tr := range d.Trips {
				if mask>>i&1 != 0 {
					c.LongDistanceTrips = append(c.LongDistanceTrips, tr.ID)
				}
			}
			for _, cn := range d.Connections {
				if slices.Contains(c.LongDistanceTrips, cn.TripID) && !slices.Contains(c.Hubs, cn.To) {
					c.Hubs = append(c.Hubs, cn.To)
					break
				}
			}
			x, e := tripbased.BuildScalable(context.Background(), d, c)
			if e != nil {
				t.Fatal(seed, mask, e)
			}
			scalableCompare(t, d, x, q, want)
			s := x.Snapshot()
			if s.Stats.DirectCache.Records > c.MaxDirectPairs {
				t.Fatal("cache capacity")
			}
			if s.Stats.ConstructionWork != s.Stats.Work+s.Local.Stats.Work+s.Border.Stats.Work+s.LongDistance.Stats.Work {
				t.Fatal("ledger")
			}
			for _, w := range s.LongDistance.Witnesses {
				qq := flashQuery(query())
				qq.Origin = w.Source
				qq.Destination = w.Target
				qq.Departure = w.Departure
				qq.MaxBoardings = 4
				reconstructed(t, d, qq, []model.Journey{w.Journey})
			}
		}
	}
}
func TestScalableV4DemandIdentityAndOwnership(t *testing.T) {
	d, q, c := hierarchyFixture()
	c.LongDistanceTrips = nil
	c.Hubs = nil
	c.DirectIndex = "incidence"
	old, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	for _, cap := range []int{1, 3, 1000} {
		c.DirectIndex = "demand"
		c.MaxDirectPairs = cap
		x, e := tripbased.BuildScalable(context.Background(), d, c)
		if e != nil {
			t.Fatal(e)
		}
		before := x.Snapshot()
		for _, dep := range []int64{10, 0, 1, 2, 0} {
			q.Departure = dep
			a, e := old.Search(context.Background(), q)
			if e != nil {
				t.Fatal(e)
			}
			b, e := x.Search(context.Background(), q)
			if e != nil || !reflect.DeepEqual(a.Journeys, b.Journeys) {
				t.Fatal("identity", cap, dep, e)
			}
		}
		var wg sync.WaitGroup
		for i := 0; i < 8; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if _, e := x.Search(context.Background(), q); e != nil {
					t.Error(e)
				}
			}()
		}
		wg.Wait()
		if !reflect.DeepEqual(before, x.Snapshot()) {
			t.Fatal("query mutated cache")
		}
	}
	d, q, c = hierarchyFixture()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	before := x.Snapshot()
	s := x.Snapshot()
	s.Config.LongDistanceTrips[0] = "bad"
	s.Config.Hubs[0] = "bad"
	s.LongStations[0] = "bad"
	for k := range s.HubAccess {
		if len(s.HubAccess[k]) > 0 {
			s.HubAccess[k][0] = "bad"
		}
	}
	if len(s.LongDistance.Witnesses) > 0 {
		s.LongDistance.Witnesses[0].Journey.Legs = nil
	}
	c.LongDistanceTrips[0] = "bad"
	c.Hubs[0] = "bad"
	if !reflect.DeepEqual(before, x.Snapshot()) {
		t.Fatal("hierarchy alias")
	}
	scalableCompare(t, d, x, q, []int64{inf, inf, 3, 3})
}
func TestScalableV4BoundsAndClassification(t *testing.T) {
	d, q, c := hierarchyFixture()
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	total := x.Snapshot().Stats.ConstructionWork
	cases := []func(*tripbased.ScalableConfig){func(c *tripbased.ScalableConfig) { c.LongDistanceTrips = []string{"missing"} }, func(c *tripbased.ScalableConfig) { c.LongDistanceTrips = []string{"ab", "ab"} }, func(c *tripbased.ScalableConfig) { c.Hubs = []string{"X"} }, func(c *tripbased.ScalableConfig) { c.Hubs = []string{"B", "B"} }, func(c *tripbased.ScalableConfig) { c.BorderSearchMode = "expanded" }, func(c *tripbased.ScalableConfig) { c.Patterns.MaxBuildWork = total - 1 }, func(c *tripbased.ScalableConfig) { c.MaxProfileRuns = 1 }}
	for i, f := range cases {
		cc := c
		f(&cc)
		z, e := tripbased.BuildScalable(context.Background(), d, cc)
		if e == nil || z.Complete() {
			t.Fatal("invalid accepted", i)
		}
		r, e := z.Search(context.Background(), q)
		if e == nil || r.Complete || len(r.Journeys) > 0 {
			t.Fatal("partial queried", i)
		}
	}
	c.Patterns.MaxBuildWork = total
	if _, e = tripbased.BuildScalable(context.Background(), d, c); e != nil {
		t.Fatal("exact cap", e)
	}
}

func TestScalableV4RepeatedStopDemandAndMixedClass(t *testing.T) {
	d := data()
	trip(&d, "early", []string{"A", "B", "A", "C", "B", "D"}, 0, 2, 2, 3, 10, 12, 12, 14, 14, 16)
	trip(&d, "late", []string{"A", "B", "A", "C", "B", "D"}, 9, 10, 10, 11, 12, 13, 13, 15, 15, 17)
	c := v3Config(true, false)
	c.DirectIndex = "demand"
	c.Partition = map[string]int{"A": 0, "B": 1, "C": 2, "D": 3, "X": 4, "Y": 5}
	c.LongDistanceTrips = []string{"early"}
	c.Hubs = []string{"B"}
	for _, cap := range []int{1, 1000} {
		c.MaxDirectPairs = cap
		for _, shift := range []int64{0, 90000} {
			data := d
			data.Connections = append([]model.Connection{}, d.Connections...)
			for i := range data.Connections {
				data.Connections[i].Departure += shift
				data.Connections[i].Arrival += shift
			}
			x, e := tripbased.BuildScalable(context.Background(), data, c)
			if e != nil {
				t.Fatal(e)
			}
			for _, p := range []struct{ at, want int64 }{{5, 16}, {10, 16}, {11, 17}, {13, inf}} {
				q := flashQuery(query())
				q.Departure = p.at + shift
				q.LatestArrival = 40 + shift
				q.MaxBoardings = 1
				want := p.want
				if want != inf {
					want += shift
				}
				scalableCompare(t, data, x, q, []int64{inf, want})
			}
		}
	}
	// Two strict FIFO trips on one line have different classifications.
	d = data()
	trip(&d, "early", []string{"A", "B"}, 0, 1)
	trip(&d, "late", []string{"A", "B"}, 5, 6)
	trip(&d, "tail", []string{"B", "D"}, 7, 8)
	c.MaxDirectPairs = 100
	c.LongDistanceTrips = []string{"early"}
	x, e := tripbased.BuildScalable(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	q := flashQuery(query())
	q.Departure = 5
	scalableCompare(t, d, x, q, []int64{inf, inf, 8, 8})
}
