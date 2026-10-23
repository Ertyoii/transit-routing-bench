package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"github.com/ertyoii/transit-routing-bench/experiment"
	"github.com/ertyoii/transit-routing-bench/fixtures"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"math/rand/v2"
	"os"
	"sort"
)

type item struct {
	Stratum string      `json:"stratum"`
	Query   model.Query `json:"query"`
}

func run() error {
	input := flag.String("dataset", "", "normalized source")
	out := flag.String("out", "", "new query workload")
	n := flag.Int("per-stratum", 6, "six per five generated strata plus four pilot cases")
	flag.Parse()
	if *input == "" || *out == "" || *n < 1 || *n > 100 {
		return fmt.Errorf("invalid args")
	}
	b, e := os.ReadFile(*input)
	if e != nil {
		return e
	}
	var d model.Dataset
	if e = strictjson.Decode(b, &d); e != nil {
		return e
	}
	if e = d.Validate(); e != nil {
		return e
	}
	if d.Window == nil || len(d.Connections) == 0 || len(d.Footpaths) == 0 {
		return fmt.Errorf("generator requires nonempty bounded model and walks")
	}
	const seed = 20261017
	rng := rand.New(rand.NewPCG(seed, 73491))
	cs := append([]model.Connection{}, d.Connections...)
	sort.Slice(cs, func(i, j int) bool { return cs[i].ID < cs[j].ID })
	stops := []string{}
	for _, s := range d.Stops {
		if s.LocationType == 0 {
			stops = append(stops, s.ID)
		}
	}
	sort.Strings(stops)
	walks := append([]model.Footpath{}, d.Footpaths...)
	sort.Slice(walks, func(i, j int) bool { return walks[i].ID < walks[j].ID })
	chains := map[string][]model.Connection{}
	for _, c := range cs {
		chains[c.TripID] = append(chains[c.TripID], c)
	}
	long := []string{}
	for id, chain := range chains {
		sort.Slice(chain, func(i, j int) bool { return chain[i].Sequence < chain[j].Sequence })
		if len(chain) >= 8 {
			long = append(long, id)
		}
	}
	sort.Strings(long)
	if len(long) == 0 || len(stops) == 0 {
		return fmt.Errorf("generator requires passenger stops and trips of at least eight normalized segments")
	}
	items := []item{}
	add := func(stratum, origin, destination string, departure int64) {
		departure = max(d.Window.Start, min(departure, d.Window.End))
		q := model.Query{ID: fmt.Sprintf("%s-%02d", stratum, len(items)), Origin: origin, Destination: destination, Departure: departure, LatestArrival: d.Window.End, MaxBoardings: 3, MaxLegs: 1024, MaxWalkSeconds: 3600, Walking: &model.WalkingLimits{Access: 600, Egress: 600, Transfer: 1200, Direct: 600}}
		items = append(items, item{stratum, q})
	}
	for _, pair := range [][2]string{{"EW23", "EW22"}, {"NS1", "EW23"}, {"EW23", "NS15"}, {"EW23", "EW23"}} {
		add("legacy_pilot_bounds_expanded", pair[0], pair[1], d.Window.Start)
	}
	for i := 0; i < *n; i++ {
		c := cs[rng.IntN(len(cs))]
		add("scheduled_adjacent", c.From, c.To, c.Departure-int64(i%2))
	}
	for i := 0; i < *n; i++ {
		chain := chains[long[rng.IntN(len(long))]]
		from := rng.IntN(len(chain) - 7)
		to := min(from+7+rng.IntN(5), len(chain)-1)
		add("on_trip_8_to_12_segments", chain[from].From, chain[to].To, chain[from].Departure)
	}
	for i := 0; i < *n; i++ {
		add("uniform_stop_od", stops[rng.IntN(len(stops))], stops[rng.IntN(len(stops))], d.Window.Start+int64(rng.IntN(int(d.Window.End-d.Window.Start))))
	}
	for i := 0; i < *n; i++ {
		w := walks[rng.IntN(len(walks))]
		add("transfer_proxy_endpoint", w.From, w.To, d.Window.Start+int64(i*60))
	}
	for i := 0; i < *n; i++ {
		c := cs[rng.IntN(len(cs))]
		departure := c.Departure + 1
		if i%2 == 0 {
			departure = d.Window.End - 1
		}
		add("missed_event_or_window_end", c.From, c.To, departure)
	}
	for _, v := range items {
		if e = v.Query.Validate(d); e != nil {
			return e
		}
	}
	artifact := struct {
		Seed          uint64 `json:"seed"`
		Method        string `json:"method"`
		DatasetSHA256 string `json:"dataset_sha256"`
		Items         []item `json:"items"`
	}{seed, "PCG(20261017,73491), sorted IDs; five convenience strata plus four earlier pilot OD pairs with expanded MaxBoardings=3/MaxLegs=1024. Stratification describes construction, not proven reachability. No rejection sampling on algorithm outcomes.", fixtures.Sum(b), items}
	if _, e = experiment.WriteArtifact(*out, artifact); e != nil {
		return e
	}
	counts := map[string]int{}
	for _, i := range items {
		counts[i.Stratum]++
	}
	summary, _ := json.Marshal(counts)
	fmt.Printf("saved %d queries: %s\n", len(items), summary)
	return nil
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
