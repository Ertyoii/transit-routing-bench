package selection_test

import (
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/selection"
	"reflect"
	"testing"
)

func TestDistinctContractsAndEqualVectors(t *testing.T) {
	// Hand-written validated metrics isolate the objective contract from route search.
	a := model.Validated{Identity: "a", Metrics: model.Metrics{Arrival: 100, Boardings: 2, Transfers: 1, LegCount: 2}}
	b := model.Validated{Identity: "b", Metrics: model.Metrics{Arrival: 110, Boardings: 1, LegCount: 1}}
	c := model.Validated{Identity: "c", Metrics: b.Metrics}
	d := model.Validated{Identity: "d", Metrics: model.Metrics{Arrival: 120, Boardings: 1, LegCount: 1}}
	input := []model.Validated{d, c, b, a}
	cases := []struct {
		spec  selection.Spec
		want  []string
		exact bool
	}{{selection.Spec{Mode: selection.Earliest}, []string{"a"}, true}, {selection.Spec{Mode: selection.Pareto, ParetoCriteria: []string{"arrival", "boardings"}}, []string{"a", "b", "c"}, true}, {selection.Spec{Mode: selection.TopK, K: 4}, []string{"a", "b", "c", "d"}, true}, {selection.Spec{Mode: selection.Candidates, CandidateCap: 2}, []string{"a", "b"}, false}}
	for _, tt := range cases {
		r, e := selection.Select(input, true, tt.spec)
		if e != nil {
			t.Fatal(e)
		}
		ids := []string{}
		for _, j := range r.Journeys {
			ids = append(ids, j.Identity)
		}
		if !reflect.DeepEqual(ids, tt.want) || r.Exact != tt.exact {
			t.Fatalf("%s got %+v", tt.spec.Mode, r)
		}
	}
	if input[0].Identity != "d" {
		t.Fatal("selection mutated router input")
	}
	if _, e := selection.Select([]model.Validated{a, a}, true, selection.Spec{Mode: selection.TopK, K: 1}); e == nil {
		t.Fatal("duplicate identity accepted")
	}
	if _, e := selection.Select(input, false, selection.Spec{Mode: selection.TopK, K: 1}); e == nil {
		t.Fatal("incomplete exact output accepted")
	}
	r, e := selection.Select(input, false, selection.Spec{Mode: selection.Candidates, CandidateCap: 2})
	if e != nil || r.Exact || !r.Capped {
		t.Fatal("bounded candidates status lost")
	}
	if _, e := selection.Select(input, true, selection.Spec{Mode: selection.Pareto}); e == nil {
		t.Fatal("undeclared Pareto criteria accepted")
	}
}
