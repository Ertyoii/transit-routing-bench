package gtfs_test

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"github.com/ertyoii/transit-routing-go/gtfs"
	"github.com/ertyoii/transit-routing-go/model"
	"reflect"
	"sort"
	"strings"
	"testing"
)

// Raw CSV constants are independently specified, not generated from normalized model objects.
func rawTables() map[string]string {
	return map[string]string{
		"agency.txt":     "agency_id,agency_timezone\nA,Asia/Singapore\n",
		"stops.txt":      "stop_id,location_type,parent_station,wheelchair_boarding\nA,0,,1\nB,0,,1\n",
		"routes.txt":     "route_id\nR\n",
		"trips.txt":      "route_id,service_id,trip_id,wheelchair_accessible\nR,WD,T,1\n",
		"calendar.txt":   "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWD,1,1,1,1,1,0,0,20261001,20261031\n",
		"stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\nT,00:01:40,00:01:40,A,10,0,1\nT,00:01:50,00:01:50,B,20,1,0\n",
	}
}
func pack(t testing.TB, tables map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	z := zip.NewWriter(&buf)
	names := []string{}
	for n := range tables {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		w, e := z.Create(n)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = w.Write([]byte(tables[n])); e != nil {
			t.Fatal(e)
		}
	}
	if e := z.Close(); e != nil {
		t.Fatal(e)
	}
	return buf.Bytes()
}
func options() gtfs.Options {
	return gtfs.Options{ServiceDate: "2026-10-16", Start: 0, End: 1000, FrequencyPolicy: "reject", TransferEdges: "none", DataKind: "scheduled_snapshot", MaxConnections: 10000}
}
func TestRawScheduledEventsAndPickupDropoff(t *testing.T) {
	d, a, e := gtfs.Import(pack(t, rawTables()), options())
	if e != nil {
		t.Fatal(e)
	}
	if len(d.Connections) != 1 || len(d.Trips) != 1 {
		t.Fatalf("unexpected instance count: %+v", a)
	}
	c := d.Connections[0]
	if c.Departure != 100 || c.Arrival != 110 || c.From != "A" || c.To != "B" || !c.Pickup || !c.Dropoff || c.Sequence != 0 {
		t.Fatalf("raw event semantics changed: %+v", c)
	}
	if d.Trips[0].SourceID != "T" || d.Trips[0].ServiceDate != "2026-10-16" || d.Trips[0].Accessible != model.Yes {
		t.Fatal("trip identity/provenance lost")
	}
	if a.RawSHA256 == "" || a.NormalizedSHA256 == "" || a.HeadwayRows != 0 {
		t.Fatal("missing audit")
	}
}
func TestFrequencyAbsentZeroAndExactAreDifferent(t *testing.T) {
	for _, exact := range []string{"", "0", "1"} {
		t.Run("exact="+exact, func(t *testing.T) {
			tables := rawTables()
			tables["frequencies.txt"] = "trip_id,start_time,end_time,headway_secs,exact_times\nT,00:00:00,00:00:25,10," + exact + "\n"
			opt := options()
			d, a, e := gtfs.Import(pack(t, tables), opt)
			if exact != "1" {
				if e == nil {
					t.Fatal("headways became exact scheduled departures")
				}
				opt.FrequencyPolicy = "deterministic_model"
				opt.DataKind = "modeled_snapshot"
				d, a, e = gtfs.Import(pack(t, tables), opt)
			}
			if e != nil {
				t.Fatal(e)
			}
			deps := []int64{}
			for _, c := range d.Connections {
				deps = append(deps, c.Departure)
			}
			if !reflect.DeepEqual(deps, []int64{0, 10, 20}) {
				t.Fatalf("frequency interval/offset wrong: %v", deps)
			}
			if exact == "1" && a.ExactFrequencyRows != 1 || exact != "1" && a.HeadwayRows != 1 {
				t.Fatal("frequency provenance lost")
			}
		})
	}
}
func TestPreviousServiceDateAndCalendarExceptions(t *testing.T) {
	tables := rawTables()
	tables["stop_times.txt"] = "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT,25:00:00,25:00:00,A,1\nT,25:10:00,25:10:00,B,2\n"
	opt := options()
	opt.Start = 3600
	opt.End = 7200
	d, _, e := gtfs.Import(pack(t, tables), opt)
	if e != nil {
		t.Fatal(e)
	}
	if len(d.Connections) != 1 || d.Connections[0].Departure != 3600 || d.Connections[0].Arrival != 4200 || d.Trips[0].ServiceDate != "2026-10-15" {
		t.Fatalf("previous service day lost: %+v", d)
	}
	tables["calendar_dates.txt"] = "service_id,date,exception_type\nWD,20261015,2\n"
	d, _, e = gtfs.Import(pack(t, tables), opt)
	if e != nil || len(d.Connections) != 0 {
		t.Fatal("calendar removal ignored")
	}
	tables = rawTables()
	delete(tables, "calendar.txt")
	tables["calendar_dates.txt"] = "service_id,date,exception_type\nWD,20261017,1\n"
	opt = options()
	opt.ServiceDate = "2026-10-17"
	d, _, e = gtfs.Import(pack(t, tables), opt)
	if e != nil || len(d.Connections) != 1 {
		t.Fatal("exception-only added service lost")
	}
}
func TestRawTripSpecificTransferAndProxyProvenance(t *testing.T) {
	tables := rawTables()
	tables["trips.txt"] = "route_id,service_id,trip_id\nR,WD,T\nR,WD,U\n"
	tables["stop_times.txt"] += "U,00:03:00,00:03:00,B,1,0,0\nU,00:04:00,00:04:00,A,2,0,0\n"
	tables["transfers.txt"] = "from_stop_id,to_stop_id,from_trip_id,to_trip_id,transfer_type,min_transfer_time\nB,B,T,U,3,\nA,B,,,2,30\n"
	opt := options()
	opt.TransferEdges = "minimum_time_proxy"
	d, a, e := gtfs.Import(pack(t, tables), opt)
	if e != nil {
		t.Fatal(e)
	}
	if len(d.Transfers) != 2 || d.Transfers[0].FromTrip != "T" || d.Transfers[0].ToTrip != "U" || d.Transfers[0].Type != 3 {
		t.Fatal("trip-specific prohibition changed")
	}
	if len(d.Footpaths) != 1 || d.Footpaths[0].Duration != 30 || d.Footpaths[0].Provenance != "inferred_gtfs_minimum_transfer_time_proxy" || d.Footpaths[0].Accessible != model.Unknown || a.FootpathCount != 1 {
		t.Fatal("proxy provenance/accessibility wrong")
	}
}
func TestUnsupportedSemanticsAndBudgetFailClosed(t *testing.T) {
	for _, kind := range []string{"1", "4", "5"} {
		tables := rawTables()
		tables["transfers.txt"] = "from_stop_id,to_stop_id,transfer_type\nA,B," + kind + "\n"
		if _, _, e := gtfs.Import(pack(t, tables), options()); e == nil {
			t.Fatalf("unsupported transfer type %s accepted", kind)
		}
	}
	tables := rawTables()
	tables["pathways.txt"] = "pathway_id\nP\n"
	if _, _, e := gtfs.Import(pack(t, tables), options()); e == nil {
		t.Fatal("pathways silently ignored")
	}
	tables = rawTables()
	tables["frequencies.txt"] = "trip_id,start_time,end_time,headway_secs,exact_times\nT,00:00:00,00:00:25,10,1\n"
	opt := options()
	opt.MaxConnections = 1
	d, _, e := gtfs.Import(pack(t, tables), opt)
	if e == nil || len(d.Connections) > 0 {
		t.Fatal("partial normalized snapshot returned as usable")
	}
}

func TestExplicitStationAccessFailsVisiblyUntilModeled(t *testing.T) {
	for _, value := range []string{"0", "1", "invalid"} {
		t.Run(value, func(t *testing.T) {
			tables := rawTables()
			tables["stops.txt"] = "stop_id,location_type,parent_station,wheelchair_boarding,stop_access\nS,1,,1,\nA,0,S,1," + value + "\nB,0,,1,\n"
			d, _, err := gtfs.Import(pack(t, tables), options())
			if err == nil || !strings.Contains(err.Error(), "stop_access") || len(d.Connections) > 0 {
				t.Fatalf("explicit station access must not silently become unrestricted: value=%q error=%v", value, err)
			}
		})
	}
	tables := rawTables()
	tables["stops.txt"] = "stop_id,location_type,parent_station,wheelchair_boarding,stop_access\nS,1,,1,\nA,0,S,1,\nB,0,,1,\n"
	if _, _, err := gtfs.Import(pack(t, tables), options()); err != nil {
		t.Fatalf("undefined stop_access adds no supported restriction: %v", err)
	}
}
func TestInputOrderDoesNotAlterNormalizedResults(t *testing.T) {
	tables := rawTables()
	first, a, e := gtfs.Import(pack(t, tables), options())
	if e != nil {
		t.Fatal(e)
	}
	tables["stop_times.txt"] = "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type\nT,00:01:50,00:01:50,B,20,1,0\nT,00:01:40,00:01:40,A,10,0,1\n"
	second, b, e := gtfs.Import(pack(t, tables), options())
	if e != nil {
		t.Fatal(e)
	}
	// Dataset ID is deliberately raw-source-dependent; connection semantics are invariant.
	first.ID = ""
	second.ID = ""
	if !reflect.DeepEqual(first, second) || a.RawSHA256 == b.RawSHA256 {
		t.Fatal("row order affects semantics or provenance hash fails to distinguish raw input")
	}
}
func FuzzServiceTime(f *testing.F) {
	f.Add("25:10:00")
	f.Add("07:00:00")
	f.Add("+1:00:00")
	f.Fuzz(func(t *testing.T, s string) {
		n, e := gtfs.Time(s)
		if e == nil {
			if n < 0 || n > model.MaxServiceSecond {
				t.Fatal("accepted out-of-range time")
			}
			b, e := json.Marshal(n)
			if e != nil || len(b) == 0 {
				t.Fatal("invalid integer")
			}
		}
	})
}
