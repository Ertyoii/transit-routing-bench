package comparison_test

import (
	"context"
	"encoding/json"
	"github.com/ertyoii/transit-routing-go/comparison"
	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/validate"
	"slices"
	"testing"
)

func bindingFixture() (model.Dataset, model.Query) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "same-network-id", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-12", Stops: []model.Stop{{ID: "A", Accessible: model.Yes}, {ID: "D", Accessible: model.Yes}}, Trips: []model.Trip{{ID: "early", Accessible: model.Yes}, {ID: "late", Accessible: model.Yes}}, Connections: []model.Connection{{ID: "early", TripID: "early", From: "A", To: "D", Departure: 0, Arrival: 1, Pickup: true, Dropoff: true}, {ID: "late", TripID: "late", From: "A", To: "D", Departure: 2, Arrival: 3, Pickup: true, Dropoff: true}}}
	q := model.Query{ID: "target", Origin: "A", Destination: "D", LatestArrival: 4, MaxBoardings: 1, MaxLegs: 1}
	return d, q
}
func caps(t testing.TB, d model.Dataset, q model.Query) csa.Result {
	t.Helper()
	idx, e := csa.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := idx.StratifiedSingle(context.Background(), q, csa.Config{ExactTopK: 1, MaxLabels: 100, MaxJourneys: 1})
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func TestRankCapsRejectsForeignCertificates(t *testing.T) {
	for _, which := range []string{"foreign-id", "reused-id", "foreign-network", "rewritten-child-ids", "foreign-parent", "swapped-caps"} {
		t.Run(which, func(t *testing.T) {
			d, q := bindingFixture()
			other := q
			other.Departure = 2
			foreignData := d.Clone()
			if which == "foreign-id" || which == "rewritten-child-ids" {
				other.ID = "other"
			}
			if which == "foreign-network" {
				other = q
				foreignData.Connections = foreignData.Connections[1:]
				foreignData.Trips = foreignData.Trips[1:]
			}
			if which == "swapped-caps" {
				q.Destination = "A"
				other = q
			}
			target, foreign := caps(t, d, q), caps(t, foreignData, other)
			if which == "swapped-caps" {
				slices.Reverse(foreign.CapResults)
				for b := range foreign.CapResults {
					foreign.CapResults[b].MaxBoardings = b
				}
			}
			if which == "rewritten-child-ids" || which == "swapped-caps" {
				for b := range foreign.CapResults {
					id, _ := json.Marshal([]any{q.ID, b})
					foreign.CapResults[b].Result.QueryID = string(id)
				}
			}
			if which == "foreign-parent" {
				target = foreign
			} else {
				target.CapResults = foreign.CapResults
				target.Journeys = foreign.Journeys
			}
			checker, _ := validate.New(d)
			for _, j := range target.Journeys {
				if _, e := checker.Check(q, j); e != nil {
					t.Fatal("fixture must remain feasible", e)
				}
			}
			out, e := comparison.RankCaps(checker, q, target, 1, 300)
			if e == nil || out.StrictComplete || out.Ranked.GlobalOptimalityClaim {
				t.Fatalf("foreign completeness accepted: %s %+v %v", which, out, e)
			}
		})
	}
}
func TestRankCapsBindingSurvivesPermutationAndSerialization(t *testing.T) {
	d, q := bindingFixture()
	q.ID = "quoted\"[,]雪"
	r := caps(t, d, q)
	b, e := json.Marshal(r)
	if e != nil {
		t.Fatal(e)
	}
	var decoded csa.Result
	if e = json.Unmarshal(b, &decoded); e != nil {
		t.Fatal(e)
	}
	slices.Reverse(d.Connections)
	slices.Reverse(d.Stops)
	slices.Reverse(d.Trips)
	checker, e := validate.New(d)
	if e != nil {
		t.Fatal(e)
	}
	got, e := comparison.RankCaps(checker, q, decoded, 1, 300)
	if e != nil || !got.StrictComplete || got.Ranked.Options[0].Journey.Metrics.Arrival != 1 {
		t.Fatal(got, e)
	}
}

func TestAllQueryFieldsBindEvenForEmptyAnswers(t *testing.T) {
	d, q := bindingFixture()
	q.Origin = "D"
	q.Destination = "A"
	r := caps(t, d, q)
	checker, _ := validate.New(d)
	edits := map[string]func(*model.Query){
		"id": func(q *model.Query) { q.ID = "reused" }, "origin": func(q *model.Query) { q.Origin = "A" }, "destination": func(q *model.Query) { q.Destination = "D" }, "departure": func(q *model.Query) { q.Departure = 1 }, "horizon": func(q *model.Query) { q.LatestArrival = 5 }, "buffer": func(q *model.Query) { q.TransferBuffer = 1 }, "total walking": func(q *model.Query) { q.MaxWalkSeconds = 1 }, "boardings": func(q *model.Query) { q.MaxBoardings = 2 }, "legs": func(q *model.Query) { q.MaxLegs = 2 }, "accessible": func(q *model.Query) { q.AccessibleOnly = true }, "walk roles": func(q *model.Query) { q.Walking = &model.WalkingLimits{} },
	}
	for name, edit := range edits {
		t.Run(name, func(t *testing.T) {
			changed := q
			edit(&changed)
			if _, e := comparison.CheckBinding(checker, changed, r); e == nil {
				t.Fatal("changed query accepted")
			}
		})
	}
	// Unknown provenance and another normalized snapshot cannot certify no route.
	r.Binding = model.ResultBinding{}
	if _, e := comparison.CheckBinding(checker, q, r); e == nil {
		t.Fatal("unbound legacy result accepted")
	}
}
