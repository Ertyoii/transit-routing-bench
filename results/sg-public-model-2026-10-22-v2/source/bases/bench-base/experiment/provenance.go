package experiment

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
)

// BuildSourceSHA256 is injected only by scripts/build.sh at compile time.
// It is a reproducibility binding from the local build process, not a signed attestation.
var BuildSourceSHA256 string

type Provenance struct {
	RoutingModule       string `json:"routing_module"`
	RoutingVersion      string `json:"routing_version"`
	RoutingCommit       string `json:"routing_commit"`
	RoutingSourceSHA256 string `json:"routing_source_sha256"`
	ExecutableSHA256    string `json:"executable_sha256"`
	BuildSourceSHA256   string `json:"build_source_sha256,omitempty"`
	RuntimeTreeSHA256   string `json:"runtime_tree_sha256"`
	RuntimeMatchesBuild bool   `json:"runtime_matches_build"`
	SourceBinding       string `json:"source_binding"`
}

func Identify(root string) (Provenance, error) {
	p := Provenance{BuildSourceSHA256: BuildSourceSHA256, SourceBinding: "unverified_runtime_tree"}
	lock, e := VerifyRoutingLock(root)
	if e != nil {
		return p, e
	}
	p.RoutingModule = lock.Module
	p.RoutingVersion = lock.Version
	p.RoutingCommit = lock.Commit
	p.RoutingSourceSHA256 = lock.SourceSHA256
	executable, e := os.Executable()
	if e != nil {
		return p, e
	}
	b, e := os.ReadFile(executable)
	if e != nil {
		return p, e
	}
	h := sha256.Sum256(b)
	p.ExecutableSHA256 = hex.EncodeToString(h[:])
	p.RuntimeTreeSHA256, e = SourceHash(root)
	if e != nil {
		return p, e
	}
	if p.BuildSourceSHA256 != "" {
		p.RuntimeMatchesBuild = p.BuildSourceSHA256 == p.RuntimeTreeSHA256
		p.SourceBinding = "embedded_build_source"
		if !p.RuntimeMatchesBuild {
			return p, fmt.Errorf("runtime source tree does not match the source fingerprint embedded at build time")
		}
	}
	return p, nil
}
