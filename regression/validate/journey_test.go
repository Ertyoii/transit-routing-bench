package validate_test

import (
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/validate"
	"testing"
)

func TestIndependentWitnessRejection(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	c, e := validate.New(b.Dataset)
	if e != nil {
		t.Fatal(e)
	}
	q := b.Queries[0]
	valid := model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "stay-0", Departure: 100, Arrival: 110}, {Kind: "ride", Ref: "stay-1", Departure: 110, Arrival: 130}}}
	v, e := c.Check(q, valid)
	if e != nil {
		t.Fatal(e)
	}
	v.Metrics.Arrival--
	if e = c.CheckClaim(q, v); e == nil {
		t.Fatal("forged metric accepted")
	}
	cases := []struct {
		name string
		q    model.Query
		j    model.Journey
	}{
		{"invented time", q, model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "tie-0", Departure: 105, Arrival: 129}}}},
		{"teleport", q, model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "fast-0", Departure: 120, Arrival: 125}}}},
		{"illegal alighting", q, model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "stay-0", Departure: 100, Arrival: 110}, {Kind: "ride", Ref: "fast-0", Departure: 120, Arrival: 125}}}},
		{"noncanonical walking wait", q, model.Journey{Legs: []model.Leg{{Kind: "walk", Ref: "ab", Departure: 91, Arrival: 96}, {Kind: "ride", Ref: "fast-0", Departure: 120, Arrival: 125}}}},
		{"unknown reference", q, model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "invented", Departure: 100, Arrival: 120}}}},
		{"empty wrong destination", q, model.Journey{}},
	}
	for _, tt := range cases {
		t.Run(tt.name, func(t *testing.T) {
			if _, e := c.Check(tt.q, tt.j); e == nil {
				t.Fatal("invalid witness accepted")
			}
		})
	}
	q.TransferBuffer = 500 // Staying onboard must ignore even an impossible new-boarding buffer.
	if _, e = c.Check(q, valid); e != nil {
		t.Fatalf("staying wrongly treated as transfer: %v", e)
	}
}
func TestTransferBufferOverlapsWalkingAndDeadlineIsInclusive(t *testing.T) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "transfer", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-17", Stops: []model.Stop{{ID: "A", Accessible: model.Yes}, {ID: "B", Accessible: model.Yes}, {ID: "C", Accessible: model.Yes}, {ID: "D", Accessible: model.Yes}}, Trips: []model.Trip{{ID: "one", Accessible: model.Yes}, {ID: "two", Accessible: model.Yes}}, Connections: []model.Connection{{ID: "one", TripID: "one", From: "A", To: "B", Departure: 100, Arrival: 110, Pickup: true, Dropoff: true}, {ID: "two", TripID: "two", From: "C", To: "D", Departure: 120, Arrival: 130, Pickup: true, Dropoff: true}}, Footpaths: []model.Footpath{{ID: "bc", From: "B", To: "C", Duration: 4, Accessible: model.Yes}}}
	q := model.Query{ID: "q", Origin: "A", Destination: "D", Departure: 90, LatestArrival: 130, TransferBuffer: 10, MaxWalkSeconds: 4, MaxBoardings: 2, MaxLegs: 3}
	c, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	j := model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "one", Departure: 100, Arrival: 110}, {Kind: "walk", Ref: "bc", Departure: 110, Arrival: 114}, {Kind: "ride", Ref: "two", Departure: 120, Arrival: 130}}}
	v, e := c.Check(q, j)
	if e != nil || v.Metrics.Transfers != 1 || v.Metrics.WalkingSeconds != 4 {
		t.Fatalf("exact deadline rejected: %+v %v", v, e)
	}
	q.TransferBuffer = 11
	if _, e = c.Check(q, j); e == nil {
		t.Fatal("missed transfer accepted")
	}
	q.TransferBuffer = 10
	q.MaxWalkSeconds = 3
	if _, e = c.Check(q, j); e == nil {
		t.Fatal("walk budget ignored")
	}
}
func TestDestinationCannotBeLeftAndNoPickupIsRespected(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	c, e := validate.New(b.Dataset)
	if e != nil {
		t.Fatal(e)
	}
	q := b.Queries[0]
	q.Origin = "B"
	if _, e = c.Check(q, model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "stay-1", Departure: 110, Arrival: 130}}}); e == nil {
		t.Fatal("pickup prohibition ignored")
	}
	q = b.Queries[0]
	q.Destination = "A"
	if _, e = c.Check(q, model.Journey{Legs: []model.Leg{{Kind: "walk", Ref: "ab", Departure: 90, Arrival: 95}}}); e == nil {
		t.Fatal("left completed destination")
	}
}
