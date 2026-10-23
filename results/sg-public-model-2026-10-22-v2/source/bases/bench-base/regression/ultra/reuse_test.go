package ultra_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/ultra"
	"reflect"
	"slices"
	"testing"
)

func shortcutKeys(x *ultra.Index) []string {
	a := []string{}
	for _, s := range x.Snapshot().Shortcuts {
		a = append(a, fmt.Sprintf("%s\x00%s\x00%d", s.From, s.To, s.Duration))
	}
	slices.Sort(a)
	return a
}
func TestActiveAndReuseShortcutAndIndependentQueryEquivalence(t *testing.T) {
	count, repairs, prunes := 0, 0, 0
	for seed := uint64(0); seed < 192; seed++ {
		d := generated(seed)
		for _, mode := range []string{ultra.IndependentTrips, ultra.NonOvertakingGroups} {
			c := config()
			c.RouteMode = mode
			base, e := ultra.Build(context.Background(), d, c)
			if e != nil {
				t.Fatal(e)
			}
			for _, reuse := range []bool{false, true} {
				c.ActiveRoutes = true
				c.ReuseDepartures = reuse
				x, e := ultra.Build(context.Background(), d, c)
				if e != nil {
					t.Fatal(seed, mode, reuse, e)
				}
				if !reuse && !reflect.DeepEqual(shortcutKeys(x), shortcutKeys(base)) {
					t.Fatalf("shortcut sets differ seed=%d mode=%s reuse=%v base=%v optimized=%v dataset=%+v", seed, mode, reuse, shortcutKeys(base), shortcutKeys(x), d)
				}
				support(t, d, x)
				repairs += x.Snapshot().Stats.EqualLabelRepairs
				prunes += x.Snapshot().Stats.RetainedLabelPrunes
				for _, a := range d.Stops {
					for _, b := range d.Stops {
						for _, dep := range []int64{0, 4} {
							compare(t, d, x, query(a.ID, b.ID, dep, 18))
							count++
						}
					}
				}
			}
		}
	}
	t.Logf("192 networks, both route modes, active and reused variants: %d independent complete query checks; equal repairs=%d retained prunes=%d", count, repairs, prunes)
}
func selfPruningFixture() model.Dataset {
	d := dataset("s", "a", "b", "c", "cp", "d", "e", "t", "z")
	add(&d, "blue", ride("s", "a", 0, 1))
	add(&d, "red", ride("b", "c", 2, 3))
	add(&d, "green", ride("cp", "d", 4, 5))
	add(&d, "purple", ride("e", "t", 7, 8))
	add(&d, "later-run", ride("b", "z", 3, 9))
	walk(&d, "ab", "a", "b", 1)
	walk(&d, "bcp", "b", "cp", 1)
	walk(&d, "cd", "c", "d", 1)
	walk(&d, "de", "d", "e", 1)
	return d
}
func TestSelfPruningEqualLabelRepairAndAbsoluteWitnessTimes(t *testing.T) {
	for _, mode := range []string{ultra.IndependentTrips, ultra.NonOvertakingGroups} {
		d := selfPruningFixture()
		c := config()
		c.RouteMode = mode
		base, e := ultra.Build(context.Background(), d, c)
		if e != nil {
			t.Fatal(e)
		}
		c.ActiveRoutes = true
		c.ReuseDepartures = true
		x, e := ultra.Build(context.Background(), d, c)
		if e != nil {
			t.Fatal(e)
		}
		compare(t, d, x, query("s", "t", 0, 10))
		if x.Snapshot().Stats.EqualLabelRepairs == 0 {
			t.Fatal("fixture did not exercise retained equal-label repair")
		}
		if !reflect.DeepEqual(shortcutKeys(x), shortcutKeys(base)) {
			t.Fatal("repair changed shortcuts", shortcutKeys(x), shortcutKeys(base))
		}
		support(t, d, x)
		compare(t, d, x, query("s", "t", 0, 10))
		compare(t, d, x, query("b", "t", 2, 10))
		compare(t, d, x, query("b", "t", 3, 10))
	}
}

func TestReusePermutationMidnightCancellationAndBudgets(t *testing.T) {
	d := selfPruningFixture()
	c := groupedConfig()
	c.ActiveRoutes = true
	c.ReuseDepartures = true
	x, e := ultra.Build(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	perm := d.Clone()
	slices.Reverse(perm.Stops)
	slices.Reverse(perm.Trips)
	slices.Reverse(perm.Connections)
	slices.Reverse(perm.Footpaths)
	y, e := ultra.Build(context.Background(), perm, c)
	if e != nil || !reflect.DeepEqual(x.Snapshot(), y.Snapshot()) {
		t.Fatal("reuse changed under input permutation", e)
	}
	shifted := d.Clone()
	for i := range shifted.Connections {
		shifted.Connections[i].Departure += 86400
		shifted.Connections[i].Arrival += 86400
	}
	z, e := ultra.Build(context.Background(), shifted, c)
	if e != nil || !reflect.DeepEqual(shortcutKeys(x), shortcutKeys(z)) {
		t.Fatal("midnight shift changed transfer keys", e)
	}
	compare(t, shifted, z, query("s", "t", 86400, 86410))
	support(t, shifted, z)
	for _, kind := range []string{"run", "connection", "walk", "edge", "output"} {
		bad := c
		switch kind {
		case "run":
			bad.Limits.MaxRuns = 1
		case "connection":
			bad.Limits.MaxConnectionVisits = 1
		case "walk":
			bad.Limits.MaxWalkSettled = 1
		case "edge":
			bad.Limits.MaxWalkEdges = 1
		case "output":
			bad.Limits.MaxOutputLegs = 1
		}
		partial, e := ultra.Build(context.Background(), d, bad)
		if e == nil || partial.Complete() {
			t.Fatal("accepted exhausted reuse", kind, e)
		}
		if r, e := partial.Search(context.Background(), query("s", "t", 0, 10), limits()); e == nil || r.Complete {
			t.Fatal("queried partial reuse", kind)
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if r, e := x.Search(ctx, query("s", "s", 0, 10), limits()); e == nil || r.Complete {
		t.Fatal("cancelled optimized self query accepted")
	}
}
