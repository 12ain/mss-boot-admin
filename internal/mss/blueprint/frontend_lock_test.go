package blueprint

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

// A generated host installs this seed with --frozen-lockfile. Qualification must
// not rely on its subsequent local-tarball substitution to repair a stale seed.
func TestApplicationFrontendTemplateLockMatchesManifest(t *testing.T) {
	_, sourceFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve test source path")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(sourceFile), "..", "..", ".."))
	read := func(path string) []byte {
		t.Helper()
		data, err := os.ReadFile(filepath.Join(root, path))
		if err != nil {
			t.Fatal(err)
		}
		return data
	}
	var manifest struct {
		Dependencies    map[string]string `json:"dependencies"`
		DevDependencies map[string]string `json:"devDependencies"`
		Pnpm            struct {
			Overrides map[string]string `json:"overrides"`
		} `json:"pnpm"`
	}
	if err := json.Unmarshal(read("templates/application/web/package.json"), &manifest); err != nil {
		t.Fatal(err)
	}
	type dependency struct {
		Specifier string `yaml:"specifier"`
	}
	var lock struct {
		Overrides map[string]string `yaml:"overrides"`
		Importers map[string]struct {
			Dependencies    map[string]dependency `yaml:"dependencies"`
			DevDependencies map[string]dependency `yaml:"devDependencies"`
		} `yaml:"importers"`
		Packages map[string]any `yaml:"packages"`
	}
	if err := yaml.Unmarshal(read("templates/application/web/pnpm-lock.yaml"), &lock); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(manifest.Pnpm.Overrides, lock.Overrides) {
		t.Fatalf("template manifest/lock overrides differ: manifest=%v lock=%v", manifest.Pnpm.Overrides, lock.Overrides)
	}
	for section, declarations := range map[string]map[string]string{
		"dependencies": manifest.Dependencies, "devDependencies": manifest.DevDependencies,
	} {
		entries := lock.Importers["."].Dependencies
		if section == "devDependencies" {
			entries = lock.Importers["."].DevDependencies
		}
		if len(entries) != len(declarations) {
			t.Fatalf("template %s importer has %d entries, want %d", section, len(entries), len(declarations))
		}
		for name, version := range declarations {
			name = strings.ReplaceAll(name, "__MSS_DISTRIBUTION_FRONTEND_PACKAGE__", "@mss-boot-io/admin-web")
			if entries[name].Specifier != version {
				t.Errorf("template %s lock specifier = %q, want %q", name, entries[name].Specifier, version)
			}
		}
	}
	// Checking only the overrides header would miss a hand-edited header with
	// vulnerable packages still present in the resolved graph.
	for selector, expected := range manifest.Pnpm.Overrides {
		name, major := selector, ""
		if i := strings.LastIndex(selector, "@"); i > 0 {
			name, major = selector[:i], selector[i+1:]
		}
		for entry := range lock.Packages {
			if !strings.HasPrefix(entry, name+"@") {
				continue
			}
			resolved := strings.TrimPrefix(entry, name+"@")
			if major != "" && !strings.HasPrefix(resolved, major+".") {
				continue
			}
			if resolved != expected {
				t.Errorf("template lock %s resolves %s, override requires %s", selector, resolved, expected)
			}
		}
	}
	var distribution struct {
		Contract struct {
			RuntimeOverrides map[string]string `json:"runtimeOverrides"`
		} `json:"mssAdminDistribution"`
	}
	if err := json.Unmarshal(read("web/antd-v6/package.json"), &distribution); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(manifest.Pnpm.Overrides, distribution.Contract.RuntimeOverrides) {
		t.Fatal("template overrides differ from the published Admin Web runtime contract")
	}
}
