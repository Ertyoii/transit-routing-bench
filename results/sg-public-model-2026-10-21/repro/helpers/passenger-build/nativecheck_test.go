package main

import (
	"context"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"github.com/ertyoii/transit-routing-go/csa"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/validate"
)

// These tests exhaust the bounded path universes of deliberately tiny fixtures.
// They check the native source/sink-anchor representation, not equivalence of all
// routing algorithms or completeness on the full Singapore timetable.

type nativeWant struct {
	refs    []string
	metrics model.Metrics
}

func nativeDataset(t *testing.T, name string, stops []string, rides []model.Connection, walks []model.Footpath) model.Dataset {
	t.Helper()
	d := model.Dataset{
		SchemaVersion: model.SchemaVersion, ID: "native-anchor-" + name,
		TimeZone: "Asia/Singapore", ServiceDate: "2026-10-20",
		Connections: rides, Footpaths: walks,
	}
	for _, id := range stops {
		d.Stops = append(d.Stops, model.Stop{ID: id, Accessible: model.Yes})
	}
	seen := map[string]bool{}
	for _, c := range rides {
		if !seen[c.TripID] {
			d.Trips = append(d.Trips, model.Trip{ID: c.TripID, Accessible: model.Yes})
			seen[c.TripID] = true
		}
	}
	if err := d.Validate(); err != nil {
		t.Fatalf("invalid tiny fixture: %v", err)
	}
	return d
}

func nativeWalk(id, from, to string, seconds int64) model.Footpath {
	return model.Footpath{ID: id, From: from, To: to, Duration: seconds, Accessible: model.Yes}
}

func nativeRide(id, trip string, sequence int, from, to string, departure, arrival int64, pickup, dropoff bool) model.Connection {
	return model.Connection{ID: id, TripID: trip, Sequence: sequence, From: from, To: to,
		Departure: departure, Arrival: arrival, Pickup: pickup, Dropoff: dropoff}
}

func nativeQuery(id, from, to string) model.Query {
	return model.Query{ID: id, Origin: from, Destination: to, Departure: 0,
		LatestArrival: 100, MaxWalkSeconds: 100, MaxBoardings: 4, MaxLegs: 10}
}

func nativeIndexes(t *testing.T, d model.Dataset) (*csa.Index, *validate.Checker) {
	t.Helper()
	index, err := csa.New(d)
	if err != nil {
		t.Fatalf("csa.New: %v", err)
	}
	checker, err := validate.New(d)
	if err != nil {
		t.Fatalf("validate.New: %v", err)
	}
	return index, checker
}

// Enforce the graph invariant that makes simultaneously installed query anchors
// safe: origin anchors cannot be entered; destination anchors cannot be left.
func nativeAnchors(t *testing.T, d model.Dataset, sources, sinks []string) {
	t.Helper()
	source, sink := map[string]bool{}, map[string]bool{}
	for _, id := range sources {
		source[id] = true
	}
	for _, id := range sinks {
		sink[id] = true
	}
	out, in := map[string]int{}, map[string]int{}
	for _, w := range d.Footpaths {
		if w.Duration <= 0 {
			t.Fatalf("anchor fixture contains nonpositive walk %q", w.ID)
		}
		if source[w.To] || sink[w.From] {
			t.Fatalf("footpath %q violates source-only/sink-only anchors", w.ID)
		}
		out[w.From]++
		in[w.To]++
	}
	for _, c := range d.Connections {
		if source[c.From] || source[c.To] || sink[c.From] || sink[c.To] {
			t.Fatalf("ride %q touches a synthetic pedestrian anchor", c.ID)
		}
	}
	for _, id := range sources {
		if out[id] == 0 {
			t.Fatalf("source anchor %q has no outward connector", id)
		}
	}
	for _, id := range sinks {
		if in[id] == 0 {
			t.Fatalf("sink anchor %q has no inward connector", id)
		}
	}
}

func nativeSignature(j model.Journey) string {
	refs := make([]string, len(j.Legs))
	for i, l := range j.Legs {
		refs[i] = l.Ref
	}
	return strings.Join(refs, "/")
}

func nativeCheckResult(t *testing.T, checker *validate.Checker, q model.Query, result csa.Result, wants []nativeWant) []model.Validated {
	t.Helper()
	if !result.Complete || result.Error != "" || result.Stats.HeuristicDiscarded != 0 || result.TopK != 0 {
		t.Fatalf("tiny path enumeration was not complete: %+v", result)
	}
	if result.QueryID != q.ID {
		t.Fatalf("result query ID = %q, want %q", result.QueryID, q.ID)
	}
	expected := make(map[string]model.Metrics, len(wants))
	for _, w := range wants {
		key := strings.Join(w.refs, "/")
		if _, exists := expected[key]; exists {
			t.Fatalf("duplicate expected path %q", key)
		}
		expected[key] = w.metrics
	}
	got := map[string]model.Metrics{}
	validated := make([]model.Validated, 0, len(result.Journeys))
	// The independent checker reconstructs every returned path, including all
	// connector times, walking blocks, cumulative walking and boarding counts.
	for _, j := range result.Journeys {
		v, err := checker.Check(q, j)
		if err != nil {
			t.Fatalf("CSA returned invalid path %q: %v", nativeSignature(j), err)
		}
		if v.Identity != model.Identity(j) {
			t.Fatalf("checker identity differs for %q", nativeSignature(j))
		}
		key := nativeSignature(j)
		if _, exists := got[key]; exists {
			t.Fatalf("duplicate returned path %q", key)
		}
		got[key] = v.Metrics
		validated = append(validated, v)
	}
	if !reflect.DeepEqual(got, expected) {
		t.Fatalf("finite journey universe mismatch\n got: %#v\nwant: %#v", got, expected)
	}
	return validated
}

func nativeEnumerate(t *testing.T, index *csa.Index, checker *validate.Checker, q model.Query, wants ...nativeWant) []model.Validated {
	t.Helper()
	result, err := index.Single(context.Background(), q, csa.Config{MaxLabels: 10000, MaxJourneys: 1000})
	if err != nil {
		t.Fatalf("csa.Single: %v", err)
	}
	return nativeCheckResult(t, checker, q, result, wants)
}

// Build explicit negative-control witnesses without using any search result.
func nativeWitness(t *testing.T, d model.Dataset, q model.Query, refs ...string) model.Journey {
	t.Helper()
	walks, rides := map[string]model.Footpath{}, map[string]model.Connection{}
	for _, w := range d.Footpaths {
		walks[w.ID] = w
	}
	for _, c := range d.Connections {
		rides[c.ID] = c
	}
	now := q.Departure
	j := model.Journey{}
	for _, ref := range refs {
		if w, ok := walks[ref]; ok {
			j.Legs = append(j.Legs, model.Leg{Kind: "walk", Ref: ref, Departure: now, Arrival: now + w.Duration})
			now += w.Duration
		} else if c, ok := rides[ref]; ok {
			j.Legs = append(j.Legs, model.Leg{Kind: "ride", Ref: ref, Departure: c.Departure, Arrival: c.Arrival})
			now = c.Arrival
		} else {
			t.Fatalf("unknown explicit witness ref %q", ref)
		}
	}
	return j
}

func nativeReject(t *testing.T, checker *validate.Checker, q model.Query, j model.Journey) {
	t.Helper()
	if _, err := checker.Check(q, j); err == nil {
		t.Fatalf("checker accepted deliberately infeasible path %q", nativeSignature(j))
	}
}

func TestNativeAnchorDirectWalkingAndCap(t *testing.T) {
	d := nativeDataset(t, "direct", []string{"O", "A", "Z"}, nil, []model.Footpath{
		nativeWalk("direct", "O", "Z", 3), nativeWalk("via-a", "O", "A", 1), nativeWalk("a-egress", "A", "Z", 2),
	})
	nativeAnchors(t, d, []string{"O"}, []string{"Z"})
	index, checker := nativeIndexes(t, d)
	wants := []nativeWant{
		{[]string{"direct"}, model.Metrics{Arrival: 3, WalkingSeconds: 3, DirectWalking: 3, LegCount: 1}},
		{[]string{"via-a", "a-egress"}, model.Metrics{Arrival: 3, WalkingSeconds: 3, DirectWalking: 3, LegCount: 2}},
	}
	// Every cap in this finite range is checked. Access, transfer and egress
	// caps are zero: none may incorrectly reject a legal walking-only path.
	for direct := int64(0); direct <= 4; direct++ {
		for total := int64(0); total <= 4; total++ {
			t.Run(fmt.Sprintf("direct_%d_total_%d", direct, total), func(t *testing.T) {
				q := nativeQuery("direct-query", "O", "Z")
				q.MaxBoardings, q.MaxLegs, q.MaxWalkSeconds = 0, 2, total
				q.Walking = &model.WalkingLimits{Direct: direct}
				if direct >= 3 && total >= 3 {
					nativeEnumerate(t, index, checker, q, wants...)
				} else {
					nativeEnumerate(t, index, checker, q)
					nativeReject(t, checker, q, nativeWitness(t, d, q, "direct"))
				}
			})
		}
	}
	q := nativeQuery("legacy-total-only", "O", "Z")
	q.MaxBoardings, q.MaxLegs, q.MaxWalkSeconds = 0, 2, 3
	nativeEnumerate(t, index, checker, q, wants...)
}

func TestNativeAnchorMultiSeedKeepsWalkingResource(t *testing.T) {
	d := nativeDataset(t, "multi-seed", []string{"O", "A", "B", "M", "D", "Z"}, []model.Connection{
		nativeRide("a-to-merge", "first", 0, "A", "M", 10, 12, true, true),
		nativeRide("b-to-merge", "second", 0, "B", "M", 11, 13, true, true),
		nativeRide("shared-boarding", "out", 0, "M", "D", 20, 22, true, true),
	}, []model.Footpath{
		nativeWalk("a-first-seed", "O", "A", 6), nativeWalk("b-second-seed", "O", "B", 2),
		nativeWalk("egress", "D", "Z", 5),
	})
	nativeAnchors(t, d, []string{"O"}, []string{"Z"})
	index, checker := nativeIndexes(t, d)
	q := nativeQuery("two-access-seeds", "O", "Z")
	q.MaxBoardings, q.MaxLegs = 2, 4
	q.Walking = &model.WalkingLimits{Access: 6, Transfer: 0, Egress: 5, Direct: 0}
	firstRefs := []string{"a-first-seed", "a-to-merge", "shared-boarding", "egress"}
	second := nativeWant{[]string{"b-second-seed", "b-to-merge", "shared-boarding", "egress"},
		model.Metrics{Arrival: 27, Boardings: 2, Transfers: 1, AccessWalking: 2, EgressWalking: 5, WalkingSeconds: 7, LegCount: 4}}
	first := nativeWant{firstRefs,
		model.Metrics{Arrival: 27, Boardings: 2, Transfers: 1, AccessWalking: 6, EgressWalking: 5, WalkingSeconds: 11, LegCount: 4}}
	// The first seed reaches M at 12, earlier than the second seed at 13,
	// with the same boarding count and depth. It consumes MORE walking, so
	// arrival-only dominance at the common next boarding would be unsound.
	q.MaxWalkSeconds = 11
	nativeEnumerate(t, index, checker, q, first, second)
	for cap := int64(0); cap <= 12; cap++ {
		t.Run(fmt.Sprintf("total_%d", cap), func(t *testing.T) {
			bounded := q
			bounded.MaxWalkSeconds = cap
			switch {
			case cap >= 11:
				nativeEnumerate(t, index, checker, bounded, first, second)
			case cap >= 7:
				nativeEnumerate(t, index, checker, bounded, second)
				nativeReject(t, checker, bounded, nativeWitness(t, d, bounded, firstRefs...))
			default:
				nativeEnumerate(t, index, checker, bounded)
			}
		})
	}
}

func TestNativeAnchorWalkingCapIncludesAllBlocks(t *testing.T) {
	d := nativeDataset(t, "all-walking-blocks", []string{"O", "A", "B", "C", "D", "Z"}, []model.Connection{
		nativeRide("first-ride", "first", 0, "A", "B", 5, 7, true, true),
		nativeRide("second-ride", "second", 0, "C", "D", 12, 14, true, true),
	}, []model.Footpath{
		nativeWalk("access", "O", "A", 2), nativeWalk("transfer", "B", "C", 3), nativeWalk("egress", "D", "Z", 4),
	})
	nativeAnchors(t, d, []string{"O"}, []string{"Z"})
	index, checker := nativeIndexes(t, d)
	q := nativeQuery("all-blocks", "O", "Z")
	q.MaxBoardings, q.MaxLegs = 2, 5
	q.Walking = &model.WalkingLimits{Access: 2, Transfer: 3, Egress: 4, Direct: 0}
	want := nativeWant{[]string{"access", "first-ride", "transfer", "second-ride", "egress"},
		model.Metrics{Arrival: 18, Boardings: 2, Transfers: 1, AccessWalking: 2, TransferWalking: 3,
			EgressWalking: 4, WalkingSeconds: 9, LegCount: 5}}
	for total := int64(0); total <= 10; total++ {
		t.Run(fmt.Sprintf("total_%d", total), func(t *testing.T) {
			bounded := q
			bounded.MaxWalkSeconds = total
			if total >= 9 {
				nativeEnumerate(t, index, checker, bounded, want)
			} else {
				nativeEnumerate(t, index, checker, bounded)
				nativeReject(t, checker, bounded, nativeWitness(t, d, bounded, want.refs...))
			}
		})
	}
	// Each block individually fits in the total-8 negative case above; the
	// rejected constraint is specifically 2 + 3 + 4 > 8, not a block cap.
	for _, block := range []string{"access", "transfer", "egress"} {
		t.Run("block_"+block, func(t *testing.T) {
			bounded := q
			limits := *q.Walking
			bounded.Walking = &limits
			bounded.MaxWalkSeconds = 9
			switch block {
			case "access":
				limits.Access--
			case "transfer":
				limits.Transfer--
			case "egress":
				limits.Egress--
			}
			nativeEnumerate(t, index, checker, bounded)
			nativeReject(t, checker, bounded, nativeWitness(t, d, bounded, want.refs...))
		})
	}
}

func TestNativeAnchorStayingAboardPreservesRestrictions(t *testing.T) {
	d := nativeDataset(t, "staying-aboard", []string{"O", "A", "B", "C", "D", "Z"}, []model.Connection{
		nativeRide("through-0", "through", 0, "A", "B", 3, 4, true, false),
		nativeRide("through-1", "through", 1, "B", "C", 5, 6, false, false),
		nativeRide("through-2", "through", 2, "C", "D", 7, 8, false, true),
	}, []model.Footpath{
		nativeWalk("access", "O", "A", 1), nativeWalk("egress", "D", "Z", 1),
		nativeWalk("illegal-b-exit", "B", "Z", 1), nativeWalk("illegal-c-exit", "C", "Z", 1),
	})
	nativeAnchors(t, d, []string{"O"}, []string{"Z"})
	index, checker := nativeIndexes(t, d)
	q := nativeQuery("stay-on-one-vehicle", "O", "Z")
	q.MaxBoardings, q.MaxLegs, q.MaxWalkSeconds, q.TransferBuffer = 1, 5, 2, 100
	q.Walking = &model.WalkingLimits{Access: 1, Egress: 1}
	want := nativeWant{[]string{"access", "through-0", "through-1", "through-2", "egress"},
		model.Metrics{Arrival: 9, Boardings: 1, AccessWalking: 1, EgressWalking: 1, WalkingSeconds: 2, LegCount: 5}}
	nativeEnumerate(t, index, checker, q, want)
	// No-dropoff intermediates may not be converted to pedestrian labels,
	// while no-pickup next segments remain legal when staying on the trip.
	for _, refs := range [][]string{
		{"access", "through-0", "illegal-b-exit"},
		{"access", "through-0", "through-1", "illegal-c-exit"},
	} {
		nativeReject(t, checker, q, nativeWitness(t, d, q, refs...))
	}
	tooFewLegs := q
	tooFewLegs.MaxLegs = 4
	nativeEnumerate(t, index, checker, tooFewLegs)
	nativeReject(t, checker, tooFewLegs, nativeWitness(t, d, tooFewLegs, want.refs...))
}

func TestNativeAnchorMultipleQueriesDoNotCreateShortcuts(t *testing.T) {
	// Both O2 and Z1 touch A and B. If O2 connectors were reversible, an
	// O1 -> A -> O2 -> B -> Z2 shortcut would appear. If Z1 connectors
	// were reversible, O1 -> A -> Z1 -> B -> Z2 would appear instead.
	d := nativeDataset(t, "several-anchors", []string{"O1", "O2", "A", "B", "Z1", "Z2"}, nil, []model.Footpath{
		nativeWalk("o1-a", "O1", "A", 2), nativeWalk("o2-a", "O2", "A", 1), nativeWalk("o2-b", "O2", "B", 1),
		nativeWalk("a-z1", "A", "Z1", 1), nativeWalk("b-z1", "B", "Z1", 1), nativeWalk("b-z2", "B", "Z2", 2),
	})
	nativeAnchors(t, d, []string{"O1", "O2"}, []string{"Z1", "Z2"})
	index, checker := nativeIndexes(t, d)
	queries := []model.Query{
		nativeQuery("o1-z1", "O1", "Z1"), nativeQuery("o2-z2", "O2", "Z2"),
		nativeQuery("o2-z1", "O2", "Z1"), nativeQuery("o1-z2-no-shortcut", "O1", "Z2"),
	}
	wants := [][]nativeWant{
		{{[]string{"o1-a", "a-z1"}, model.Metrics{Arrival: 3, WalkingSeconds: 3, DirectWalking: 3, LegCount: 2}}},
		{{[]string{"o2-b", "b-z2"}, model.Metrics{Arrival: 3, WalkingSeconds: 3, DirectWalking: 3, LegCount: 2}}},
		{
			{[]string{"o2-a", "a-z1"}, model.Metrics{Arrival: 2, WalkingSeconds: 2, DirectWalking: 2, LegCount: 2}},
			{[]string{"o2-b", "b-z1"}, model.Metrics{Arrival: 2, WalkingSeconds: 2, DirectWalking: 2, LegCount: 2}},
		},
		nil,
	}
	for i := range queries {
		queries[i].MaxBoardings, queries[i].MaxLegs, queries[i].MaxWalkSeconds = 0, 6, 10
		queries[i].Walking = &model.WalkingLimits{Direct: 10}
		nativeEnumerate(t, index, checker, queries[i], wants[i]...)
	}
	// The same already-indexed graph is also safe under interleaved lanes.
	batch, err := index.Shared(context.Background(), queries, csa.Config{MaxLabels: 10000, MaxJourneys: 1000})
	if err != nil {
		t.Fatalf("csa.Shared: %v", err)
	}
	if len(batch.Results) != len(queries) {
		t.Fatalf("shared result count = %d, want %d", len(batch.Results), len(queries))
	}
	for i, result := range batch.Results {
		nativeCheckResult(t, checker, queries[i], result, wants[i])
	}
	// Repeating the unreachable lane after other queries cannot import any
	// label or connector belonging to those queries.
	nativeEnumerate(t, index, checker, queries[3])
}
