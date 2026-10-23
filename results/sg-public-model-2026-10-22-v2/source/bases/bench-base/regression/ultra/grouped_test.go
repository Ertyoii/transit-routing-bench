package ultra_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/ultra"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
)

func groupedConfig() ultra.Config { c := config(); c.RouteMode = ultra.NonOvertakingGroups; return c }

func TestGroupedDestinationMustAllowLaterBoardingPosition(t *testing.T) {
	d := dataset("O", "A", "B", "D")
	add(&d, "early", ride("A", "D", 0, 1), ride("D", "B", 2, 3), ride("B", "D", 5, 6))
	add(&d, "late", ride("A", "D", 10, 11), ride("D", "B", 12, 13), ride("B", "D", 15, 16))
	walk(&d, "oa", "O", "A", 2)
	walk(&d, "ob", "O", "B", 4)
	x, e := ultra.Build(context.Background(), d, groupedConfig())
	if e != nil {
		t.Fatal(e)
	}
	q := query("O", "D", 0, 20)
	q.MaxBoardings = 1
	compare(t, d, x, q)
}
func TestGroupedIndependentCompleteTinyUniverses(t *testing.T) {
	count := 0
	for seed := uint64(0); seed < 192; seed++ {
		d := generated(seed)
		x, e := ultra.Build(context.Background(), d, groupedConfig())
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
	t.Logf("grouped mode: 192 networks; %d complete independent query universes", count)
}
func TestGroupedOvertakingTiesPermutationIsolationAndBudgets(t *testing.T) {
	d := dataset("A", "B", "C", "D")
	add(&d, "early-slow", ride("A", "B", 1, 6), ride("B", "C", 7, 12))
	add(&d, "late-fast", ride("A", "B", 3, 4), ride("B", "C", 5, 8))
	add(&d, "ordered", ride("A", "B", 9, 10), ride("B", "C", 11, 15))
	add(&d, "tie", ride("A", "B", 9, 10), ride("B", "C", 11, 15))
	add(&d, "last", ride("C", "D", 13, 14))
	c := groupedConfig()
	x, e := ultra.Build(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	for _, dep := range []int64{0, 2, 4, 9, 10} {
		compare(t, d, x, query("A", "D", dep, 20))
		compare(t, d, x, query("B", "C", dep, 20))
	}
	// Every route grouping must be non-overtaking, independently inspecting the
	// public snapshot rather than sharing a production partition helper.
	trips := map[string][]model.Connection{}
	for _, co := range d.Connections {
		trips[co.TripID] = append(trips[co.TripID], co)
	}
	grouped := false
	for _, r := range x.Snapshot().Routes {
		if len(r.TripIDs) > 1 {
			grouped = true
		}
		for i := 1; i < len(r.TripIDs); i++ {
			a, b := trips[r.TripIDs[i-1]], trips[r.TripIDs[i]]
			for j := range a {
				if a[j].Departure > b[j].Departure || a[j].Arrival > b[j].Arrival {
					t.Fatal("overtaking route", r)
				}
			}
		}
	}
	if !grouped {
		t.Fatal("fixture did not exercise grouping")
	}
	perm := d.Clone()
	slices.Reverse(perm.Stops)
	slices.Reverse(perm.Trips)
	slices.Reverse(perm.Connections)
	y, e := ultra.Build(context.Background(), perm, c)
	if e != nil || !reflect.DeepEqual(x.Snapshot(), y.Snapshot()) {
		t.Fatal("input permutation changed canonical preparation", e)
	}
	q := query("A", "D", 0, 20)
	before, e := x.Search(context.Background(), q, limits())
	if e != nil {
		t.Fatal(e)
	}
	snap := x.Snapshot()
	snap.Routes[0].TripIDs[0] = "mutated"
	snap.Routes[0].Stops[0] = "changed"
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			got, e := x.Search(context.Background(), q, limits())
			if e != nil || !reflect.DeepEqual(got.Journeys, before.Journeys) {
				t.Error("concurrent identity differs", e)
			}
		}()
	}
	wg.Wait()
	c.Limits.MaxConnectionVisits = 1
	bad, e := ultra.Build(context.Background(), d, c)
	if e == nil || bad.Complete() || bad.Snapshot().Stats.GroupingComparisons != 1 || !strings.Contains(e.Error(), "connection budget") {
		t.Fatal("grouping limit not enforced", e, bad.Snapshot().Stats)
	}
	if r, e := bad.Search(context.Background(), q, limits()); e == nil || r.Complete {
		t.Fatal("partial grouping accepted")
	}
	l := limits()
	l.MaxConnectionVisits = 1
	if r, e := x.Search(context.Background(), q, l); e == nil || r.Complete {
		t.Fatal("probe work limit not enforced")
	}
}
