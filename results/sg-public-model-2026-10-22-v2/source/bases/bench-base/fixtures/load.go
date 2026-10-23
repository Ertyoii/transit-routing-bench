// Package fixtures loads pinned original synthetic inputs; it is not a GTFS importer.
package fixtures

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"github.com/ertyoii/transit-routing-go/model"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"os"
	"path/filepath"
)

type Bundle struct {
	Dataset model.Dataset `json:"dataset"`
	Queries []model.Query `json:"queries"`
}
type Manifest struct {
	SchemaVersion string `json:"schema_version"`
	ID            string `json:"id"`
	Kind          string `json:"kind"`
	Source        string `json:"source"`
	CreatedUTC    string `json:"created_utc"`
	License       string `json:"license"`
	LicenseFile   string `json:"license_file"`
	LicenseSHA256 string `json:"license_sha256"`
	DataFile      string `json:"data_file"`
	DataSHA256    string `json:"data_sha256"`
	Seed          int64  `json:"seed"`
	Generator     string `json:"generator"`
}

func strict(data []byte, v any) error { return strictjson.Decode(data, v) }

func Sum(data []byte) string { h := sha256.Sum256(data); return hex.EncodeToString(h[:]) }
func readRelative(dir, name string) ([]byte, error) {
	if name == "" || filepath.IsAbs(name) || filepath.Base(name) != name {
		return nil, fmt.Errorf("manifest file must be a sibling basename")
	}
	return os.ReadFile(filepath.Join(dir, name))
}
func Load(manifestPath string) (Bundle, Manifest, error) {
	var b Bundle
	var m Manifest
	data, err := os.ReadFile(manifestPath)
	if err != nil {
		return b, m, err
	}
	if err = strict(data, &m); err != nil {
		return b, m, err
	}
	if !model.SupportedVersion(m.SchemaVersion) || m.ID == "" || m.Kind != "original_synthetic" || m.Source == "" || m.License == "" || m.CreatedUTC == "" || m.Generator == "" {
		return b, m, fmt.Errorf("invalid synthetic manifest metadata")
	}
	dir := filepath.Dir(manifestPath)
	data, err = readRelative(dir, m.LicenseFile)
	if err != nil {
		return b, m, err
	}
	if Sum(data) != m.LicenseSHA256 {
		return b, m, fmt.Errorf("license SHA-256 mismatch")
	}
	data, err = readRelative(dir, m.DataFile)
	if err != nil {
		return b, m, err
	}
	if Sum(data) != m.DataSHA256 {
		return b, m, fmt.Errorf("data SHA-256 mismatch")
	}
	if err = strict(data, &b); err != nil {
		return b, m, err
	}
	if err = b.Dataset.Validate(); err != nil {
		return b, m, err
	}
	seen := map[string]bool{}
	if len(b.Queries) == 0 {
		return b, m, fmt.Errorf("empty fixture query set")
	}
	for _, q := range b.Queries {
		if seen[q.ID] {
			return b, m, fmt.Errorf("duplicate query ID %q", q.ID)
		}
		seen[q.ID] = true
		if err = q.Validate(b.Dataset); err != nil {
			return b, m, err
		}
	}
	return b, m, nil
}
