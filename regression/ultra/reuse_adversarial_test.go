package ultra_test

import (
	"context"
	"github.com/ertyoii/transit-routing-go/ultra"
	"reflect"
	"testing"
)

func TestReuseEqualOldWitnessAtEarlierBoardingIndex(t *testing.T) {
	d := dataset("S", "O", "A", "B", "C", "T", "Z")
	add(&d, "new", ride("S", "C", 0, 2))
	add(&d, "witness", ride("O", "A", 3, 4))
	add(&d, "second", ride("A", "B", 5, 6), ride("B", "T", 7, 8))
	add(&d, "later-run", ride("S", "Z", 2, 9))
	walk(&d, "so", "S", "O", 1)
	walk(&d, "cb", "C", "B", 1)
	for _, mode := range []string{ultra.IndependentTrips, ultra.NonOvertakingGroups} {
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
		t.Logf("mode=%s fresh=%q reused=%q", mode, shortcutKeys(base), shortcutKeys(x))
		if len(shortcutKeys(base)) != 0 || !reflect.DeepEqual(shortcutKeys(x), []string{"C\x00B\x001"}) {
			t.Fatal("expected a valid redundant shortcut after old-run equal-label repair")
		}
		support(t, d, x)
		for _, a := range d.Stops {
			for _, b := range d.Stops {
				for _, dep := range []int64{0, 1, 2, 3, 4, 5, 6, 7, 8} {
					compare(t, d, base, query(a.ID, b.ID, dep, 10))
					compare(t, d, x, query(a.ID, b.ID, dep, 10))
				}
			}
		}
	}
}
