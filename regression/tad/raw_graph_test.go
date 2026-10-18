package tad_test

import (
	"context"
	"fmt"
	"github.com/ertyoii/transit-routing-go/eacsa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/profilecsa"
	"github.com/ertyoii/transit-routing-go/profilequery"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/tad"
	"testing"
)

func TestIsolatedWalkingComponentInvariance(t *testing.T) {
	d, q := data(), query()
	q.MaxLegs = 1024
	trip(&d, "only", []string{"A", "D"}, 0, 1)
	check(t, d, q, 1)
	for i := 0; i < 260; i++ {
		id := fmt.Sprintf("N%d", i)
		d.Stops = append(d.Stops, model.Stop{ID: id, Accessible: model.Yes})
		if i > 0 {
			d.Footpaths = append(d.Footpaths, model.Footpath{ID: fmt.Sprintf("w%d", i), From: fmt.Sprintf("N%d", i-1), To: id, Duration: 1, Accessible: model.Yes})
		}
	}
	check(t, d, q, 1)
}
func connectedRaw(edges int) (model.Dataset, model.Query) {
	d, q := data(), query()
	q.MaxLegs = 1024
	q.MaxBoardings = 1
	q.LatestArrival = 10000
	q.MaxWalkSeconds = 3000
	q.Walking = &model.WalkingLimits{Access: 3000}
	prev := "A"
	for i := 1; i <= 5000; i++ {
		id := fmt.Sprintf("raw%d", i)
		if i == edges {
			id = "C"
		} else {
			d.Stops = append(d.Stops, model.Stop{ID: id, Accessible: model.Yes})
		}
		d.Footpaths = append(d.Footpaths, model.Footpath{ID: fmt.Sprintf("step%d", i), From: prev, To: id, Duration: 1, Accessible: model.Yes})
		prev = id
	}
	d.Footpaths = append(d.Footpaths, model.Footpath{ID: "cycle", From: "raw5000", To: "raw4999", Duration: 1, Accessible: model.Yes})
	trip(&d, "exit", []string{"C", "D"}, 3000, 3001)
	return d, q
}
func TestLargeConnectedRawWalkingWitness(t *testing.T) {
	d, q := connectedRaw(900)
	check(t, d, q, 3001)
}
func TestLongRawWitnessStillRejectsBindingLegs(t *testing.T) {
	d, q := connectedRaw(1100)
	x, e := tad.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.Search(context.Background(), q, cfg())
	if e == nil || r.Complete {
		t.Fatal("binding raw walking resource accepted", r)
	}
}

func TestLargeRawWalkingAcrossPaperPorts(t *testing.T) {
	d, q := connectedRaw(900)
	ea, e := eacsa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := ea.Search(context.Background(), q)
	if e != nil || !r.Complete || minimum(metrics(t, d, q, r.Journeys)) != 3001 {
		t.Fatal(r, e)
	}
	rap, e := raptor.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e = rap.Search(context.Background(), q)
	if e != nil || !r.Complete || minimum(metrics(t, d, q, r.Journeys)) != 3001 {
		t.Fatal(r, e)
	}
	mc, e := rap.SearchMulti(context.Background(), q, raptor.MultiConfig{Criterion: "walking_seconds", MaxLabels: 100000, MaxConnectionVisits: 100000})
	if e != nil || !mc.Complete {
		t.Fatal(mc, e)
	}
	ms := metrics(t, d, q, mc.Journeys)
	if len(ms) != 1 || ms[0].Arrival != 3001 || ms[0].WalkingSeconds != 900 || ms[0].Boardings != 1 {
		t.Fatal(ms)
	}
	pc, e := profilecsa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	window := profilequery.Query{Base: q, End: 1}
	limits := profilequery.Limits{MaxLabels: 100000, MaxConnectionVisits: 100000, MaxDepartures: 1000}
	for _, search := range []func(context.Context, profilequery.Query, profilequery.Limits) (profilequery.Result, error){pc.Search, rap.SearchRange} {
		pr, e := search(context.Background(), window, limits)
		if e != nil || !pr.Complete {
			t.Fatal(pr, e)
		}
		for ready := int64(0); ready <= 1; ready++ {
			js, e := pr.At(ready)
			if e != nil {
				t.Fatal(e)
			}
			at := q
			at.Departure = ready
			if minimum(metrics(t, d, at, js)) != 3001 {
				t.Fatal(pr)
			}
		}
	}
}
