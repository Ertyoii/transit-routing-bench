package recommend_test

import (
	"context"
	"errors"
	"fmt"
	"math/bits"
	"math/rand/v2"
	"reflect"
	"sort"
	"testing"

	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/recommend"
)

type optionFact struct {
	elapsed, walk int64
	transfers     int
}

// Each literal vector has its own disjoint platform/ride chain. No routing or
// production feature/dominance code constructs the expected utility values.
func optionFixture(facts []optionFact) (model.Dataset, model.Query, []model.Journey) {
	d := model.Dataset{SchemaVersion: model.SchemaVersion, ID: "choice-facts", TimeZone: "Asia/Singapore", ServiceDate: "2026-10-19", Stops: []model.Stop{{ID: "O", Accessible: model.Yes}, {ID: "D", Accessible: model.Yes}}}
	js := []model.Journey{}
	for i, f := range facts {
		at := fmt.Sprintf("a%02d", i)
		d.Stops = append(d.Stops, model.Stop{ID: at, Accessible: model.Yes})
		w := fmt.Sprintf("walk%02d", i)
		d.Footpaths = append(d.Footpaths, model.Footpath{ID: w, From: "O", To: at, Duration: f.walk, Accessible: model.Yes})
		j := model.Journey{Legs: []model.Leg{{Kind: "walk", Ref: w, Departure: 0, Arrival: f.walk}}}
		for b := 0; b <= f.transfers; b++ {
			to := fmt.Sprintf("x%02d_%d", i, b)
			arr := max(int64(500), f.walk+50) + int64(5+10*b)
			if b == f.transfers {
				to = "D"
				arr = f.elapsed
			} else {
				d.Stops = append(d.Stops, model.Stop{ID: to, Accessible: model.Yes})
			}
			id := fmt.Sprintf("ride%02d_%d", i, b)
			d.Trips = append(d.Trips, model.Trip{ID: id, RouteID: id, Accessible: model.Yes})
			c := model.Connection{ID: id, TripID: id, From: at, To: to, Departure: max(int64(500), f.walk+50) + int64(10*b), Arrival: arr, Pickup: true, Dropoff: true}
			d.Connections = append(d.Connections, c)
			j.Legs = append(j.Legs, model.Leg{Kind: "ride", Ref: id, Departure: c.Departure, Arrival: c.Arrival})
			at = to
		}
		js = append(js, j)
	}
	q := model.Query{ID: "q", Origin: "O", Destination: "D", Departure: 0, LatestArrival: 10000, MaxBoardings: 5, MaxWalkSeconds: 1000, MaxLegs: 10}
	return d, q, js
}
func choiceConfig(prefs []recommend.Preference) recommend.ChoiceConfig {
	return recommend.ChoiceConfig{MaxSubsets: 200000, MaxCandidates: 1024, Groups: []recommend.PreferenceGroup{{Name: "explicit_test_hypotheses", Description: "literal scenario weights, not learned preferences", Preferences: prefs}}}
}
func bruteChoice(facts []optionFact, prefs []recommend.Preference, k int) (int64, int64, int) {
	costs := make([][]int64, len(facts))
	opt := make([]int64, len(prefs))
	for i, f := range facts {
		for j, p := range prefs {
			v := f.elapsed + int64(f.transfers)*p.TransferSeconds + f.walk*p.ExtraWalkWeight
			costs[i] = append(costs[i], v)
			if i == 0 || v < opt[j] {
				opt[j] = v
			}
		}
	}
	bestMax, bestSum := int64(1<<62), int64(1<<62)
	bestCount := len(facts) + 1
	// Full bit-mask universe, including dominated/equal vectors. No pruning.
	for mask := 1; mask < 1<<len(facts); mask++ {
		count := bits.OnesCount(uint(mask))
		if count > k {
			continue
		}
		var worst, sum int64
		for j := range prefs {
			value := int64(1 << 62)
			for i := range facts {
				if mask&(1<<i) != 0 && costs[i][j] < value {
					value = costs[i][j]
				}
			}
			loss := value - opt[j]
			if loss > worst {
				worst = loss
			}
			sum += loss
		}
		if worst < bestMax || (worst == bestMax && (sum < bestSum || (sum == bestSum && count < bestCount))) {
			bestMax, bestSum, bestCount = worst, sum, count
		}
	}
	return bestMax, bestSum, bestCount
}
func TestFinitePreferenceMinimaxAgainstFullSubsetUniverse(t *testing.T) {
	rng := rand.New(rand.NewPCG(61019, 71))
	prefs := []recommend.Preference{}
	for _, p := range []int64{0, 120, 300, 600} {
		for _, w := range []int64{0, 1, 2, 4, 8} {
			prefs = append(prefs, recommend.Preference{ID: fmt.Sprintf("p%dw%d", p, w), TransferSeconds: p, ExtraWalkWeight: w})
		}
	}
	for trial := 0; trial < 80; trial++ {
		facts := []optionFact{}
		for n := 3 + rng.IntN(7); len(facts) < n; {
			facts = append(facts, optionFact{elapsed: 600 + int64(rng.IntN(1000)), walk: 1 + int64(rng.IntN(100)), transfers: rng.IntN(4)})
		}
		d, q, js := optionFixture(facts)
		x, e := recommend.New(d)
		if e != nil {
			t.Fatal(e)
		}
		cfg := choiceConfig(prefs)
		r, e := x.EvaluateChoices(context.Background(), q, js, cfg)
		if e != nil {
			t.Fatal(e)
		}
		for _, s := range r.Choices.Groups[0].Selections {
			if s.Method != "preference_minimax" {
				continue
			}
			wm, sm, sz := bruteChoice(facts, prefs, s.Limit)
			if !s.Complete || !s.PoolOptimal || s.GlobalOptimalityClaim || *s.WorstRegret != wm || *s.TotalRegret != sm || len(s.Selected) != sz {
				t.Fatalf("trial%d cap%d: %+v expected %d/%d/%d", trial, s.Limit, s, wm, sm, sz)
			}
		}
		for i, j := 0, len(js)-1; i < j; i, j = i+1, j-1 {
			js[i], js[j] = js[j], js[i]
		}
		again, e := x.EvaluateChoices(context.Background(), q, js, cfg)
		if e != nil || !reflect.DeepEqual(r, again) {
			t.Fatal("input order changed result")
		}
	}
}
func TestCapacityLossReportedInsteadOfEnvelopeFiltering(t *testing.T) {
	facts := []optionFact{}
	prefs := []recommend.Preference{}
	for i := 1; i <= 7; i++ {
		facts = append(facts, optionFact{elapsed: int64(600 + 10*(7-i)*(7-i)), walk: int64(10 * i)})
	}
	for w := int64(0); w <= 12; w += 2 {
		prefs = append(prefs, recommend.Preference{ID: fmt.Sprint(w), ExtraWalkWeight: w})
	}
	d, q, js := optionFixture(facts)
	x, e := recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	r, e := x.EvaluateChoices(context.Background(), q, js, choiceConfig(prefs))
	if e != nil {
		t.Fatal(e)
	}
	for _, s := range r.Choices.Groups[0].Selections {
		if s.Method == "preference_minimax" {
			if *s.WorstRegret != 10 || len(s.Selected) != s.Limit || s.CoveredScenarios != s.Limit || *s.TotalRegret != int64((7-s.Limit)*10) {
				t.Fatalf("finite capacity loss: %+v", s)
			}
		}
	}
	cfg := choiceConfig(prefs)
	cfg.MaxSubsets = 1
	partial, e := x.EvaluateChoices(context.Background(), q, js, cfg)
	if !errors.Is(e, recommend.ErrSelectionBudget) || partial.Choices.Complete || len(partial.Choices.Groups) != 0 {
		t.Fatal("truncated set claimed complete")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e = x.EvaluateChoices(ctx, q, js, choiceConfig(prefs)); !errors.Is(e, context.Canceled) {
		t.Fatal("cancel ignored")
	}
}
func TestEnvelopeLossRemovedWithoutForcingExtraChoices(t *testing.T) {
	// Literal reviewed711 case: the extra transfer cost is a hypothesis, not a
	// physical feasibility restriction. Two candidates fit either display cap.
	facts := []optionFact{{elapsed: 2093, walk: 660, transfers: 0}, {elapsed: 1944, walk: 379, transfers: 2}}
	d, q, js := optionFixture(facts)
	x, e := recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	prefs := []recommend.Preference{{ID: "walk", ExtraWalkWeight: 2}, {ID: "transfers", TransferSeconds: 300}}
	r, e := x.EvaluateChoices(context.Background(), q, js, choiceConfig(prefs))
	if e != nil {
		t.Fatal(e)
	}
	for _, s := range r.Selections {
		if s.Envelope == 300 && (len(s.Selected) != 1 || s.Selected[0] != model.Identity(js[0])) {
			t.Fatal("negative envelope control changed")
		}
	}
	for _, s := range r.Choices.Groups[0].Selections {
		if len(s.Selected) != 2 || *s.WorstRegret != 0 {
			t.Fatalf("preferred walk option lost despite available slots: %+v", s)
		}
		if *s.Scores[0].CandidateBest != 2702 || *s.Scores[0].SelectedBest != 2702 {
			t.Fatal("literal 711-loss repair score mismatch")
		}
	}
	single, e := x.EvaluateChoices(context.Background(), q, js[:1], choiceConfig(prefs))
	if e != nil {
		t.Fatal(e)
	}
	for _, s := range single.Choices.Groups[0].Selections {
		if len(s.Selected) != 1 {
			t.Fatal("forced fictitious alternatives")
		}
	}
	empty, e := x.EvaluateChoices(context.Background(), q, nil, choiceConfig(prefs))
	if e != nil {
		t.Fatal(e)
	}
	for _, s := range empty.Choices.Groups[0].Selections {
		if s.WorstRegret != nil || len(s.Selected) != 0 {
			t.Fatal("empty pool invented zero regret or option")
		}
	}
}
func TestChoiceValidationAndEqualVectorIdentity(t *testing.T) {
	facts := []optionFact{{elapsed: 800, walk: 20}, {elapsed: 800, walk: 20}}
	d, q, js := optionFixture(facts)
	x, e := recommend.New(d)
	if e != nil {
		t.Fatal(e)
	}
	cfg := choiceConfig([]recommend.Preference{{ID: "duration"}})
	r, e := x.EvaluateChoices(context.Background(), q, js, cfg)
	if e != nil {
		t.Fatal(e)
	}
	ids := []string{model.Identity(js[0]), model.Identity(js[1])}
	sort.Strings(ids)
	for _, s := range r.Choices.Groups[0].Selections {
		if len(s.Selected) != 1 || s.Selected[0] != ids[0] {
			t.Fatal("equivalent-vector tie not canonical")
		}
	}
	js[0].Legs[0].Arrival--
	if _, e = x.EvaluateChoices(context.Background(), q, js, cfg); e == nil {
		t.Fatal("forged movement time accepted")
	}
	cfg.Groups[0].Preferences[0].ExtraWalkWeight = -1
	if _, e = x.EvaluateChoices(context.Background(), q, nil, cfg); e == nil {
		t.Fatal("negative preference bypassed monotonicity contract")
	}
}

// A physical-vector-dominated option can tie every scored objective when walking
// has zero weight. Identity canonicalization is among retained representatives,
// while regret and minimum cardinality are optimal over the original pool.
func TestChoiceDominatedButScoreTiedRepresentativeIdentity(t *testing.T) {
	d, q, js := optionFixture([]optionFact{{elapsed: 800, walk: 100}, {elapsed: 800, walk: 50}})
	x, err := recommend.New(d)
	if err != nil {
		t.Fatal(err)
	}
	first, second := model.Identity(js[0]), model.Identity(js[1])
	if first >= second {
		t.Fatal("fixture identity order changed")
	}
	out, err := x.EvaluateChoices(context.Background(), q, js, choiceConfig([]recommend.Preference{{ID: "elapsed_only"}}))
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range out.Choices.Groups[0].Selections {
		if s.Method != "preference_minimax" {
			continue
		}
		if !s.PoolOptimal || *s.WorstRegret != 0 || *s.TotalRegret != 0 || len(s.Selected) != 1 || s.Selected[0] != second {
			t.Fatalf("representative tie or original-pool score/cardinality contract changed: %+v", s)
		}
	}
	if out.Choices.Exclusions[first] != "monotone_score_vector_dominated" {
		t.Fatal("dominated score-tied option was not explicitly accounted for")
	}
}
