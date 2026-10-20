package experiment

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/ertyoii/transit-routing-go/strictjson"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

type RoutingLock struct {
	Module               string            `json:"module"`
	Version              string            `json:"version"`
	Commit               string            `json:"commit"`
	Files                map[string]string `json:"files"`
	SourceSHA256         string            `json:"source_sha256"`
	Origin               string            `json:"origin"`
	BaselineSourceSHA256 string            `json:"baseline_source_sha256"`
}

// VerifyRoutingLock checks the complete vendored source set. A lock is a local
// reproducibility binding, not an authenticated remote provenance statement.
func VerifyRoutingLock(root string) (RoutingLock, error) {
	var lock RoutingLock
	b, e := os.ReadFile(filepath.Join(root, "routing.lock.json"))
	if e != nil {
		return lock, e
	}
	if e = strictjson.Decode(b, &lock); e != nil {
		return lock, e
	}
	if lock.Module != "github.com/ertyoii/transit-routing-go" || lock.Version != "v0.1.0-pre.3" || lock.Commit == "" || len(lock.Files) == 0 {
		return lock, fmt.Errorf("invalid routing pin")
	}
	dir := filepath.Join(root, "vendor", filepath.FromSlash(lock.Module))
	seen := map[string]bool{}
	e = filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("symlink in routing vendor")
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			return err
		}
		key := filepath.ToSlash(rel)
		expected, ok := lock.Files[key]
		if !ok {
			return fmt.Errorf("unlocked routing file %s", key)
		}
		bytes, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(bytes)
		if hex.EncodeToString(sum[:]) != expected {
			return fmt.Errorf("routing vendor changed: %s", key)
		}
		seen[key] = true
		return nil
	})
	if e != nil {
		return lock, e
	}
	if len(seen) != len(lock.Files) {
		return lock, fmt.Errorf("missing routing vendor file")
	}
	b, e = json.Marshal(lock.Files)
	if e != nil {
		return lock, e
	}
	sum := sha256.Sum256(b)
	if hex.EncodeToString(sum[:]) != lock.SourceSHA256 {
		return lock, fmt.Errorf("routing file-list digest mismatch")
	}
	b, e = os.ReadFile(filepath.Join(root, "vendor/modules.txt"))
	if e != nil {
		return lock, e
	}
	if !strings.Contains(string(b), "# "+lock.Module+" "+lock.Version+"\n") {
		return lock, fmt.Errorf("vendor version mismatch")
	}
	b, e = os.ReadFile(filepath.Join(root, "go.mod"))
	if e != nil {
		return lock, e
	}
	if !strings.Contains(string(b), "require "+lock.Module+" "+lock.Version) || strings.Contains(string(b), "replace ") {
		return lock, fmt.Errorf("module pin mismatch or replacement")
	}
	return lock, nil
}
