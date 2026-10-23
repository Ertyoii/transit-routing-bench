// Check replays every fixture using the frozen Go full-itinerary validator.
package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/validate"
	"io"
	"os"
	"strings"
)

func main() {
	if len(os.Args) != 3 {
		panic("usage: check dataset.json fixtures.json")
	}
	var d model.Dataset
	read(os.Args[1], &d)
	var rows []struct {
		ID      string        `json:"id"`
		Query   model.Query   `json:"query"`
		Journey model.Journey `json:"journey"`
	}
	read(os.Args[2], &rows)
	c, e := validate.New(d)
	must(e)
	results := []any{}
	for _, r := range rows {
		v, e := c.Check(r.Query, r.Journey)
		must(e)
		results = append(results, map[string]any{"id": r.ID, "metrics": v.Metrics, "valid": true})
	}
	must(json.NewEncoder(os.Stdout).Encode(map[string]any{"schema_valid": true, "fixtures": results}))
}
func read(p string, v any) {
	b, e := os.ReadFile(p)
	must(e)
	if strings.HasSuffix(p, ".gz") {
		r, e := gzip.NewReader(bytes.NewReader(b))
		must(e)
		b, e = io.ReadAll(r)
		must(e)
		must(r.Close())
	}
	must(json.Unmarshal(b, v))
}
func must(e error) {
	if e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
