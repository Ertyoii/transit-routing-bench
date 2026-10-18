// walkingparity compares frozen outputs and witnesses. It reports no timings.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/raptor"
	"github.com/ertyoii/transit-routing-go/validate"
	"github.com/ertyoii/transit-routing-go/walking"
	"github.com/ertyoii/transit-routing-go/walking/graph"
	"github.com/ertyoii/transit-routing-go/walking/osm"
	"github.com/ertyoii/transit-routing-go/walking/transit"
	"os"
	"reflect"
	"sort"
	"strconv"
	"time"
)

type evidence struct {
	GraphSHA  string            `json:"graph_sha256"`
	PBF       string            `json:"pbf_sha256"`
	Terminals []int64           `json:"terminal_nodes"`
	Aliases   map[string]string `json:"node_aliases"`
	Shortest  []struct {
		From    int64 `json:"source"`
		To      int64 `json:"target"`
		Seconds int64 `json:"seconds"`
	} `json:"terminal_shortest_paths"`
	Witnesses []struct {
		ID      string   `json:"id"`
		From    int64    `json:"source"`
		To      int64    `json:"target"`
		Seconds int64    `json:"seconds"`
		Edges   []string `json:"raw_edges"`
	} `json:"walk_witnesses"`
	Edges []struct {
		ID      string `json:"id"`
		From    int64  `json:"from"`
		To      int64  `json:"to"`
		Seconds int64  `json:"seconds"`
	} `json:"raw_edges"`
}
type pass struct {
	Records []struct {
		Query     model.Query       `json:"query"`
		Raw       []model.Journey   `json:"raw"`
		Final     []model.Validated `json:"final"`
		Completed bool              `json:"completed"`
	} `json:"records"`
}

func read(path string, v any) (string, error) {
	b, e := os.ReadFile(path)
	if e != nil {
		return "", e
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), json.Unmarshal(b, v)
}
func canonical(js []model.Journey) []string {
	s := make([]string, 0, len(js))
	for _, j := range js {
		b, _ := json.Marshal(j)
		s = append(s, string(b))
	}
	sort.Strings(s)
	return s
}
func run() error {
	datasetPath := flag.String("dataset", "", "frozen nominal dataset")
	witnessPath := flag.String("walking", "", "frozen walking evidence")
	passPath := flag.String("pass", "", "frozen complete McRAPTOR pass")
	rawPath := flag.String("osm-graph", "", "optional full audited OSM graph")
	flag.Parse()
	lock, e := experiment.VerifyRoutingLock(".")
	if e != nil {
		return e
	}
	source, e := experiment.SourceHash(".")
	if e != nil {
		return e
	}
	var d model.Dataset
	var w evidence
	var p pass
	hashes := map[string]string{}
	for _, input := range []struct {
		path  string
		value any
	}{{*datasetPath, &d}, {*witnessPath, &w}, {*passPath, &p}} {
		h, e := read(input.path, input.value)
		if e != nil {
			return e
		}
		hashes[input.path] = h
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()
	g, e := transit.FromDataset(d, graph.DefaultLimits())
	if e != nil {
		return e
	}
	aliases := func(id int64) string { return w.Aliases[strconv.FormatInt(id, 10)] }
	paths := map[[2]int64]int64{}
	for _, p := range w.Shortest {
		paths[[2]int64{p.From, p.To}] = p.Seconds
	}
	endpoint := []walking.Endpoint{}
	for _, id := range w.Terminals {
		if aliases(id) == "" {
			return fmt.Errorf("missing alias")
		}
		endpoint = append(endpoint, walking.Endpoint{NodeID: aliases(id)})
	}
	req := walking.MatrixRequest{SnapshotID: g.Descriptor().SnapshotID, Sources: endpoint, Targets: endpoint, Options: walking.Options{Role: walking.Closure, MaxSeconds: 1200}}
	matrix, e := g.Matrix(ctx, req)
	if e != nil {
		return e
	}
	witnessByID := map[string]int{}
	for i, s := range w.Witnesses {
		witnessByID[s.ID] = i
	}
	edgeByID := map[string]int{}
	for i, s := range w.Edges {
		edgeByID[s.ID] = i
	}
	pairs, reachable, rawSegments := 0, 0, 0
	for i, from := range w.Terminals {
		for j, to := range w.Terminals {
			v := matrix.Rows[i][j]
			if from == to {
				if v.Path == nil || v.Path.Seconds != 0 {
					return fmt.Errorf("self path")
				}
				continue
			}
			pairs++
			want, ok := paths[[2]int64{from, to}]
			if !ok {
				if v.Status != walking.Unreachable {
					return fmt.Errorf("unexpected reachability %d/%d", from, to)
				}
				continue
			}
			reachable++
			if v.Path == nil || v.Path.Seconds != want {
				return fmt.Errorf("terminal distance mismatch %d/%d", from, to)
			}
			r := walking.Request{SnapshotID: req.SnapshotID, From: endpoint[i], To: endpoint[j], Options: req.Options}
			if e = g.ValidatePath(r, v); e != nil {
				return e
			}
			at := from
			var seconds int64
			for _, segment := range v.Path.Segments {
				wi, ok := witnessByID[segment.ID]
				if !ok {
					return fmt.Errorf("unknown contracted witness")
				}
				witness := w.Witnesses[wi]
				if witness.From != at || aliases(witness.From) != segment.From || aliases(witness.To) != segment.To || witness.Seconds != segment.Seconds {
					return fmt.Errorf("contracted witness mismatch")
				}
				var subtotal int64
				for _, id := range witness.Edges {
					ei, ok := edgeByID[id]
					if !ok {
						return fmt.Errorf("missing raw edge")
					}
					raw := w.Edges[ei]
					if raw.From != at {
						return fmt.Errorf("raw witness discontinuity")
					}
					at = raw.To
					subtotal += raw.Seconds
					rawSegments++
				}
				if at != witness.To || subtotal != witness.Seconds {
					return fmt.Errorf("raw witness totals")
				}
				seconds += subtotal
			}
			if at != to || seconds != want {
				return fmt.Errorf("expanded path mismatch")
			}
		}
	}
	rawPairs := 0
	if *rawPath != "" {
		f, e := os.Open(*rawPath)
		if e != nil {
			return e
		}
		raw, e := osm.Load(ctx, f, osm.Options{MaxBytes: 256 << 20, ExpectedGraphSHA256: w.GraphSHA, ExpectedSourceSHA256: w.PBF, PermissionPolicy: "pedestrian_allowlist_v2", Limits: graph.DefaultLimits()})
		_ = f.Close()
		if e != nil {
			return e
		}
		hashes[*rawPath] = w.GraphSHA
		endpoints := []walking.Endpoint{}
		for _, n := range w.Terminals {
			endpoints = append(endpoints, walking.Endpoint{NodeID: strconv.FormatInt(n, 10)})
		}
		result, e := raw.Matrix(ctx, walking.MatrixRequest{SnapshotID: raw.Descriptor().SnapshotID, Sources: endpoints, Targets: endpoints, Options: req.Options})
		if e != nil {
			return e
		}
		for i, from := range w.Terminals {
			for j, to := range w.Terminals {
				if from == to {
					continue
				}
				rawPairs++
				expected, ok := paths[[2]int64{from, to}]
				v := result.Rows[i][j]
				if ok && (v.Path == nil || v.Path.Seconds != expected) || !ok && v.Status != walking.Unreachable {
					return fmt.Errorf("raw provider terminal mismatch %d/%d", from, to)
				}
			}
		}
	}
	index, e := raptor.New(d)
	if e != nil {
		return e
	}
	checker, e := validate.New(d)
	if e != nil {
		return e
	}
	journeys := 0
	earlyVectors := 0
	for _, record := range p.Records {
		if !record.Completed {
			return fmt.Errorf("reference pass incomplete")
		}
		out, e := index.SearchMulti(ctx, record.Query, raptor.MultiConfig{Criterion: "walking_seconds", MaxLabels: 1000000, MaxConnectionVisits: 100000000})
		if e != nil || !out.Complete {
			return fmt.Errorf("query %s: %v", record.Query.ID, e)
		}
		if !reflect.DeepEqual(canonical(out.Journeys), canonical(record.Raw)) {
			return fmt.Errorf("full itinerary parity %s", record.Query.ID)
		}
		vectors := func(js []model.Journey) ([]string, error) {
			out := []string{}
			for _, j := range js {
				v, e := checker.Check(record.Query, j)
				if e != nil {
					return nil, e
				}
				out = append(out, fmt.Sprintf("%d/%d/%d", v.Metrics.Arrival, v.Metrics.Boardings, v.Metrics.WalkingSeconds))
			}
			sort.Strings(out)
			return out, nil
		}
		want, e := vectors(out.Journeys)
		if e != nil {
			return e
		}
		journeys += len(out.Journeys)
		early, e := index.SearchMulti(ctx, record.Query, raptor.MultiConfig{Criterion: "walking_seconds", MaxLabels: 1000000, MaxConnectionVisits: 100000000, EarlyPruning: true})
		if e != nil || !early.Complete {
			return fmt.Errorf("early query %s: %v", record.Query.ID, e)
		}
		got, e := vectors(early.Journeys)
		if e != nil {
			return e
		}
		if !reflect.DeepEqual(want, got) {
			return fmt.Errorf("early vector parity %s", record.Query.ID)
		}
		earlyVectors += len(got)
	}
	output := map[string]any{"success": true, "kind": "functional-parity-not-performance", "source_sha256": source, "routing_lock": lock, "inputs_sha256": hashes, "ordered_terminal_pairs": pairs, "reachable_terminal_pairs": reachable, "expanded_raw_segment_checks": rawSegments, "raw_osm_provider_pairs": rawPairs, "complete_query_itinerary_parity": len(p.Records), "journeys": journeys, "early_pruning_vector_parity": earlyVectors, "scope": "frozen bus-only modeled Singapore; bounded paths; no timing claim"}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	return enc.Encode(output)
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
