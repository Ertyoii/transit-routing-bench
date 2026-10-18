package transfer_test

import (
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/transfer"
	"testing"
)

func TestMaximumSpecificityResolvesLowerPriorityOverlap(t *testing.T) {
	d := model.Dataset{Stops: []model.Stop{{ID: "B", ParentStation: "S"}, {ID: "S", LocationType: 1}, {ID: "C"}}, Trips: []model.Trip{{ID: "a", RouteID: "R1"}, {ID: "b", RouteID: "R2"}}, Transfers: []model.TransferRule{
		{ID: "station", FromStop: "S", ToStop: "C", Type: 3},
		{ID: "platform", FromStop: "B", ToStop: "C", Type: 2, MinSeconds: 30},
		{ID: "trip-exception", FromStop: "B", ToStop: "C", FromTrip: "a", ToTrip: "b", Type: 0},
	}}
	r, e := transfer.New(d).Resolve(model.Connection{TripID: "a", To: "B"}, model.Connection{TripID: "b", From: "C"}, 99)
	if e != nil || !r.Allowed || r.Minimum != 0 || r.RuleID != "trip-exception" {
		t.Fatalf("maximal override must win after lower-priority overlap: %+v %v", r, e)
	}
	d.Transfers = d.Transfers[:2]
	if _, e = transfer.New(d).Resolve(model.Connection{TripID: "a", To: "B"}, model.Connection{TripID: "b", From: "C"}, 0); e == nil {
		t.Fatal("maximal ambiguity accepted")
	}
}
func TestSpecificityAndDirection(t *testing.T) {
	a, b := model.Connection{TripID: "a", To: "B"}, model.Connection{TripID: "b", From: "C"}
	d := model.Dataset{Stops: []model.Stop{{ID: "B"}, {ID: "C"}}, Trips: []model.Trip{{ID: "a", SourceID: "template-a", RouteID: "R1"}, {ID: "b", RouteID: "R2"}}}
	rules := []model.TransferRule{
		{ID: "stop", FromStop: "B", ToStop: "C", Type: 3},
		{ID: "route", FromStop: "B", ToStop: "C", FromRoute: "R1", Type: 2, MinSeconds: 10},
		{ID: "routes", FromStop: "B", ToStop: "C", FromRoute: "R1", ToRoute: "R2", Type: 2, MinSeconds: 20},
		{ID: "trip", FromStop: "B", ToStop: "C", FromTrip: "template-a", FromRoute: "R1", Type: 2, MinSeconds: 30},
		{ID: "trip-route", FromStop: "B", ToStop: "C", FromTrip: "template-a", ToRoute: "R2", Type: 2, MinSeconds: 40},
		{ID: "trips", FromStop: "B", ToStop: "C", FromTrip: "template-a", ToTrip: "b", Type: 2, MinSeconds: 50},
	}
	for i := range rules {
		d.Transfers = rules[:i+1]
		r, e := transfer.New(d).Resolve(a, b, 0)
		if e != nil || r.RuleID != rules[i].ID {
			t.Fatalf("priority %d: %+v %v", i, r, e)
		}
	}
	r, e := transfer.New(d).Resolve(model.Connection{TripID: "b", To: "C"}, model.Connection{TripID: "a", From: "B"}, 7)
	if e != nil || !r.Allowed || r.Minimum != 7 {
		t.Fatal("directed rule applied backwards")
	}
}
