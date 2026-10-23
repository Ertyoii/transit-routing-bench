package experiment

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"time"
)

type ArtifactIO struct {
	SerializationNS int64  `json:"serialization_ns"`
	WriteNS         int64  `json:"write_ns"`
	Bytes           int    `json:"bytes"`
	SHA256          string `json:"sha256"`
	Scope           string `json:"scope"`
}

// WriteArtifact exclusively creates a JSON artifact and a measured IO sidecar.
// The sidecar is necessary because an artifact cannot contain its own final write duration.
func WriteArtifact(path string, v any) (ArtifactIO, error) {
	record := ArtifactIO{Scope: "JSON marshal plus newline; file open/write/close; OS-buffered writes, no fsync; sidecar serialization/writing excluded"}
	for _, p := range []string{path, path + ".io.json"} {
		if _, e := os.Stat(p); e == nil {
			return record, fmt.Errorf("artifact path exists: %s", p)
		} else if !os.IsNotExist(e) {
			return record, e
		}
	}
	start := time.Now()
	b, e := json.Marshal(v)
	if e != nil {
		return record, e
	}
	b = append(b, '\n')
	record.SerializationNS = time.Since(start).Nanoseconds()
	record.Bytes = len(b)
	h := sha256.Sum256(b)
	record.SHA256 = hex.EncodeToString(h[:])
	start = time.Now()
	f, e := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		return record, e
	}
	_, e = f.Write(b)
	closeErr := f.Close()
	record.WriteNS = time.Since(start).Nanoseconds()
	if e != nil {
		return record, e
	}
	if closeErr != nil {
		return record, closeErr
	}
	sidecar, e := os.OpenFile(path+".io.json", os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if e != nil {
		return record, e
	}
	e = json.NewEncoder(sidecar).Encode(record)
	closeErr = sidecar.Close()
	if e != nil {
		return record, e
	}
	return record, closeErr
}

type Resources struct {
	Memory  Memory       `json:"runtime_memory"`
	Process ProcessUsage `json:"process"`
}

func SnapshotResources() Resources { return Resources{Memory: memory(), Process: processUsage()} }

// ThroughputConfidence is descriptive repetition-unit bootstrap, not a query-latency interval.
func ThroughputConfidence(samples []float64, seed uint64) (Interval, error) {
	if len(samples) < 2 {
		return Interval{}, fmt.Errorf("at least two repetitions required")
	}
	return bootstrap(samples, seed), nil
}
