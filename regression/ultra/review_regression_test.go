package ultra_test

import (
	"context"
	"errors"
	"github.com/ertyoii/transit-routing-go/ultra"
	"testing"
)

func TestReviewedCanceledSelfFailsClosed(t *testing.T) {
	d := dataset("A", "B")
	add(&d, "only", ride("A", "B", 1, 2))
	for _, mode := range []string{ultra.IndependentTrips, ultra.NonOvertakingGroups} {
		c := config()
		c.RouteMode = mode
		x, e := ultra.Build(context.Background(), d, c)
		if e != nil {
			t.Fatal(e)
		}
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		r, e := x.Search(ctx, query("A", "A", 0, 10), limits())
		if !errors.Is(e, context.Canceled) || r.Complete || len(r.Journeys) != 0 {
			t.Errorf("%s: canceled self returned complete=%v err=%v journeys=%v", mode, r.Complete, e, r.Journeys)
		}
	}
}
func TestReviewedEqualArrivalTripsAreSeparateCanonicalRoutes(t *testing.T) {
	d := dataset("S", "O", "A", "B", "C")
	add(&d, "feeder", ride("S", "O", 0, 1))
	add(&d, "early", ride("A", "B", 0, 5), ride("B", "C", 5, 6))
	add(&d, "late", ride("A", "B", 2, 5), ride("B", "C", 5, 6))
	walk(&d, "oa", "O", "A", 1)
	walk(&d, "ob", "O", "B", 3)
	x, e := ultra.Build(context.Background(), d, groupedConfig())
	if e != nil {
		t.Fatal(e)
	}
	group := map[string]int{}
	for i, r := range x.Snapshot().Routes {
		for _, id := range r.TripIDs {
			group[id] = i
		}
	}
	if group["early"] == group["late"] {
		t.Fatal("distinct trips with equal arrivals share a canonical route")
	}
	compare(t, d, x, query("S", "C", 0, 10))
	support(t, d, x)
}

func TestRepeatedStopCrossPositionArrivalTiesUseSeparateRoutes(t *testing.T) {
	d := dataset("A", "B", "C", "D")
	add(&d, "early", ride("A", "B", 0, 1), ride("B", "C", 2, 3), ride("C", "B", 4, 5), ride("B", "D", 6, 7))
	add(&d, "late", ride("A", "B", 4, 5), ride("B", "C", 6, 7), ride("C", "B", 8, 9), ride("B", "D", 10, 11))
	c := groupedConfig()
	c.ActiveRoutes = true
	c.ReuseDepartures = true
	x, e := ultra.Build(context.Background(), d, c)
	if e != nil {
		t.Fatal(e)
	}
	if len(x.Snapshot().Routes) != 2 {
		t.Fatal("cross-position equal arrivals must not share a canonical route")
	}
	for _, dep := range []int64{0, 2, 4, 6} {
		compare(t, d, x, query("A", "D", dep, 12))
	}
}
