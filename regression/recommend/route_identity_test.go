package recommend_test

import (
	"github.com/ertyoii/transit-routing-go/model"
	"testing"
)

func TestMissingRouteCannotCollideWithNamedRoute(t *testing.T) {
	d, q, js := fixture()
	d.Trips[6].RouteID = ""
	d.Trips[7].RouteID = "trip:direct"
	d.Connections[7].Arrival = 600
	js[2].Legs[0].Arrival = 600
	r := evaluate(t, d, q, js[1:])
	if len(r.Features) != 2 || r.Features[0].Pattern == r.Features[1].Pattern {
		t.Fatal("missing-route trip conflated with named route")
	}
	for _, s := range r.Selections {
		if len(s.Selected) != 2 {
			t.Fatal("distinct unknown/named routes collapsed")
		}
	}
	d, q, js = fixture()
	d.Trips[1].RouteID = ""
	d.Trips[2].RouteID = "trip:second"
	r = evaluate(t, d, q, []model.Journey{js[0]})
	if !r.Features[0].Transfers[0].Recovery[0].Censored {
		t.Fatal("unknown-route trip gained fabricated named-route recovery")
	}
}
