package presentation_test

import (
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/presentation"
	"testing"
)

func TestPenaltyChangesDisplayOrderWithoutChangingArrival(t *testing.T) {
	q := model.Query{Departure: 0, MaxBoardings: 3}
	fast := model.Validated{Identity: "fast", Metrics: model.Metrics{Arrival: 100, Boardings: 2, Transfers: 1}}
	direct := model.Validated{Identity: "direct", Metrics: model.Metrics{Arrival: 200, Boardings: 1}}
	r, e := presentation.Rank(q, []model.Validated{fast, direct}, 2, 300)
	if e != nil {
		t.Fatal(e)
	}
	if r.Options[0].Journey.Identity != "direct" || r.Options[1].GeneralizedScore != 400 || r.Options[1].ActualDuration != 100 || r.Options[1].Journey.Metrics.Arrival != 100 || r.GlobalOptimalityClaim {
		t.Fatalf("penalty semantics wrong: %+v", r)
	}
	if fast.Metrics.Arrival != 100 {
		t.Fatal("input arrival mutated")
	}
}
