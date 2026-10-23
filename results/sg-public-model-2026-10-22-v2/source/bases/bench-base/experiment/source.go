package experiment

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// SourceHash identifies Go source contents, module metadata and the routing lock, including their relative paths.
func SourceHash(root string) (string, error) {
	paths := []string{}
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, e error) error {
		if e != nil {
			return e
		}
		if d.IsDir() {
			if p != root && (d.Name() == ".git" || d.Name() == ".cache" || d.Name() == "artifacts") {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.HasSuffix(p, ".go") || d.Name() == "go.mod" || d.Name() == "routing.lock.json" || filepath.ToSlash(p) == filepath.ToSlash(filepath.Join(root, "vendor/modules.txt")) {
			paths = append(paths, p)
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	sort.Strings(paths)
	h := sha256.New()
	for _, p := range paths {
		rel, e := filepath.Rel(root, p)
		if e != nil {
			return "", e
		}
		b, e := os.ReadFile(p)
		if e != nil {
			return "", e
		}
		fmt.Fprintf(h, "%d:%s:%d:", len(rel), rel, len(b))
		h.Write(b)
	}
	if len(paths) == 0 {
		return "", fmt.Errorf("no Go sources under %q", root)
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
