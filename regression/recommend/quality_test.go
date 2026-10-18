package recommend_test

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/recommend"
)

// Literal movement, transfer and alternative-service facts, not router output.
func fixture() (model.Dataset, model.Query, []model.Journey) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "quality-literal", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-19"}
	for _, s := range []string{"O", "A", "B", "C", "D"} {
		d.Stops = append(d.Stops, model.Stop{ID: s, Accessible: model.Yes})
	}
	for _, id := range []string{"first", "second", "backup", "last", "unknown", "wrong", "direct", "later"} {
		route := "R"
		if id == "direct" || id == "later" {
			route = "D"
		}
		d.Trips = append(d.Trips, model.Trip{ID: id, RouteID: route, Accessible: model.Yes})
	}
	add := func(id, trip, from, to string, dep, arr int64) {
		d.Connections = append(d.Connections, model.Connection{ID: id, TripID: trip, From: from, To: to, Departure: dep, Arrival: arr, Pickup: true, Dropoff: true})
	}
	add("first", "first", "A", "B", 100, 200)
	add("second", "second", "C", "D", 260, 400)
	add("backup", "backup", "C", "D", 320, 470)
	add("last", "last", "C", "D", 600, 750)
	add("unknown", "unknown", "C", "D", 380, 500)
	d.Trips[4].Accessible = model.Unknown
	add("wrong", "wrong", "C", "A", 380, 400) // Same line, wrong boarded sequence: not recovery.
	add("direct", "direct", "O", "D", 90, 600)
	add("later", "later", "O", "D", 110, 620)
	d.Footpaths = []model.Footpath{{ID: "oa", From: "O", To: "A", Duration: 40, Accessible: model.Yes}, {ID: "bc", From: "B", To: "C", Duration: 30, Accessible: model.Yes}}
	d.Transfers = []model.TransferRule{{ID: "min", FromStop: "B", ToStop: "C", Type: 2, MinSeconds: 50}}
	q := model.Query{ID: "q", Origin: "O", Destination: "D", Departure: 50, LatestArrival: 800, MaxWalkSeconds: 200, MaxBoardings: 3, MaxLegs: 8}
	js := []model.Journey{{Legs: []model.Leg{{Kind: "walk", Ref: "oa", Departure: 50, Arrival: 90}, {Kind: "ride", Ref: "first", Departure: 100, Arrival: 200}, {Kind: "walk", Ref: "bc", Departure: 200, Arrival: 230}, {Kind: "ride", Ref: "second", Departure: 260, Arrival: 400}}}, {Legs: []model.Leg{{Kind: "ride", Ref: "direct", Departure: 90, Arrival: 600}}}, {Legs: []model.Leg{{Kind: "ride", Ref: "later", Departure: 110, Arrival: 620}}}}
	return d, q, js
}
func evaluate(t *testing.T, d model.Dataset, q model.Query, js []model.Journey) recommend.Result {
	t.Helper()
	x, e := recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.Evaluate(q, js)
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func TestPhysicalFeaturesRecoveryAndPatternChoices(t *testing.T) {
	d, q, js := fixture()
	r := evaluate(t, d, q, js)
	features := map[string]recommend.Feature{}
	for _, f := range r.Features {
		features[f.Identity] = f
	}
	f := features[model.Identity(js[0])]
	if f.Duration != 350 || f.InitialWait != 10 || f.Wait != 40 || f.Ride != 240 || f.LongestWalk != 40 || f.SameRouteReboardings != 1 || f.Metrics.WalkingSeconds != 70 {
		t.Fatalf("literal features: %+v", f)
	}
	if len(f.Transfers) != 1 || f.Transfers[0].Ready != 250 || f.Transfers[0].Slack != 10 {
		t.Fatalf("minimum overlaps walking, never adds it twice: %+v", f.Transfers)
	}
	rs := f.Transfers[0].Recovery
	for i, want := range []int64{320, 380, 600} {
		if rs[i].Censored || rs[i].Departure == nil || *rs[i].Departure != want {
			t.Fatalf("recovery %d: %+v", i, rs[i])
		}
	}
	a, b := features[model.Identity(js[1])], features[model.Identity(js[2])]
	if a.Pattern != b.Pattern {
		t.Fatal("departure duplicates not collapsed")
	}
	for _, s := range r.Selections {
		if len(s.Selected) != 2 || s.Selected[0] != model.Identity(js[1]) || s.Selected[1] != model.Identity(js[0]) || s.Decisions[model.Identity(js[2])] != "repeated_physical_pattern" || s.GlobalOptimalityClaim {
			t.Fatalf("selection: %+v", s)
		}
	}
	q.AccessibleOnly = true
	r = evaluate(t, d, q, js)
	for _, f := range r.Features {
		if len(f.Transfers) > 0 && *f.Transfers[0].Recovery[1].Departure != 600 {
			t.Fatal("unknown accessible recovery selected")
		}
	}
}
func TestCandidateOrderIdentityAndTimeShift(t *testing.T) {
	d, q, js := fixture()
	expected := evaluate(t, d, q, js)
	shuffled := []model.Journey{js[2], js[0], js[1], js[0]}
	if !reflect.DeepEqual(expected, evaluate(t, d, q, shuffled)) {
		t.Fatal("pool order/duplicate changes result")
	}
	// >24h shift is legitimate service time, not modulo-day arithmetic.
	const shift int64 = 86400
	for i := range d.Connections {
		d.Connections[i].Departure += shift
		d.Connections[i].Arrival += shift
	}
	q.Departure += shift
	q.LatestArrival += shift
	for i := range js {
		for j := range js[i].Legs {
			js[i].Legs[j].Departure += shift
			js[i].Legs[j].Arrival += shift
		}
	}
	shifted := evaluate(t, d, q, js)
	for i, f := range shifted.Features {
		old := expected.Features[i]
		if f.Duration != old.Duration || f.Pattern != old.Pattern || f.InitialWait != old.InitialWait || f.Wait != old.Wait {
			t.Fatal("service-time translation changed relative feature")
		}
		for j, tr := range f.Transfers {
			if tr.Slack != old.Transfers[j].Slack || tr.Ready != old.Transfers[j].Ready+shift {
				t.Fatal("shifted transfer")
			}
		}
	}
	if !reflect.DeepEqual(shifted.Selections, expected.Selections) {
		t.Fatal("time shift changed selection")
	}
}
func TestInvalidWitnessNeverBecomesRecommendation(t *testing.T) {
	d, q, js := fixture()
	x, e := recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	for _, mutate := range []func(*model.Journey){func(j *model.Journey) { j.Legs[0].Arrival-- }, func(j *model.Journey) { j.Legs[0].Ref = "missing" }, func(j *model.Journey) { j.Legs = j.Legs[1:] }} {
		b, _ := json.Marshal(js[0])
		var j model.Journey
		json.Unmarshal(b, &j)
		mutate(&j)
		if _, e := x.Evaluate(q, []model.Journey{js[1], j}); e == nil {
			t.Fatal("invalid candidate accepted")
		}
	}
	q.AccessibleOnly = true
	d.Footpaths[0].Accessible = model.Unknown
	x, e = recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = x.Evaluate(q, js); e == nil {
		t.Fatal("unknown-access walking accepted")
	}
}
func TestRecoveryCensoringAndContinuousVehicle(t *testing.T) {
	d, q, js := fixture()
	d.Connections = d.Connections[:2]
	d.Connections[1].TripID = "first"
	d.Connections[1].Sequence = 1
	d.Connections[1].From = "B"
	d.Connections[1].Departure = 210
	js[0].Legs = []model.Leg{js[0].Legs[0], js[0].Legs[1], {Kind: "ride", Ref: "second", Departure: 210, Arrival: 400}}
	q.TransferBuffer = 500
	r := evaluate(t, d, q, js[:1])
	f := r.Features[0]
	if f.Metrics.Boardings != 1 || len(f.Transfers) != 0 || f.SameRouteReboardings != 0 {
		t.Fatal("staying on vehicle treated as transfer")
	}
	d, q, js = fixture()
	d.Connections = d.Connections[:2]
	r = evaluate(t, d, q, js[:1])
	for _, recovery := range r.Features[0].Transfers[0].Recovery {
		if !recovery.Censored || recovery.Departure != nil || recovery.Arrival != nil {
			t.Fatal("invented future service")
		}
	}
}

func TestEmptyPoolStillValidatesQuery(t *testing.T) {
	d, q, _ := fixture()
	x, e := recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	q.MaxLegs = 4096
	if _, e = x.Evaluate(q, nil); e == nil {
		t.Fatal("invalid query accepted with empty candidate pool")
	}
}
