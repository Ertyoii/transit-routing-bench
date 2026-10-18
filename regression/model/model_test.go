package model_test

import (
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"testing"
)

func TestMalformedEventChainsAndExplicitClock(t *testing.T) {
	b, _, e := fixtures.Load("../../testdata/tiny.manifest.json")
	if e != nil {
		t.Fatal(e)
	}
	d := b.Dataset
	d.TimeZone = "Local"
	if e = d.Validate(); e == nil {
		t.Fatal("machine-dependent timezone accepted")
	}
	d = b.Dataset
	d.ServiceDate = "2026-02-30"
	if e = d.Validate(); e == nil {
		t.Fatal("invalid date accepted")
	}
	d = b.Dataset
	d.Connections = append([]model.Connection{}, d.Connections...)
	d.Connections[1].Sequence = 2
	if e = d.Validate(); e == nil {
		t.Fatal("missing stop event accepted")
	}
	d = b.Dataset
	d.Footpaths = append([]model.Footpath{}, d.Footpaths...)
	d.Footpaths[0].Duration = 0
	if e = d.Validate(); e == nil {
		t.Fatal("unsupported zero-duration walk accepted")
	}
}
func TestJourneyIdentityIsUnambiguousAndWaitIndependent(t *testing.T) {
	a := model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "a|walk:b", Departure: 1, Arrival: 2}}}
	b := model.Journey{Legs: []model.Leg{{Kind: "ride", Ref: "a"}, {Kind: "walk", Ref: "b"}}}
	if model.Identity(a) == model.Identity(b) {
		t.Fatal("delimiter collision")
	}
	c := model.Journey{Legs: append([]model.Leg{}, a.Legs...)}
	c.Legs[0].Departure = 100
	c.Legs[0].Arrival = 200
	if model.Identity(a) != model.Identity(c) {
		t.Fatal("identity includes wait/event claims")
	}
}
