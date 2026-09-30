package authz

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// These tests assert properties of the package as a codebase rather than of any single
// function: which packages it may reach, and which of its own files exist.
//
// The risk boundary in ADR-018 is only real if it is structural. If this package could
// import the Risk Engine, "authorization cannot override financial risk" would be a
// convention that any future edit could quietly break, and the test suite would keep
// passing while the guarantee stopped being true.

// repoRoot is the root import path of this repository.
//
// The authz package sits in the control-plane module, so the module path in go.mod is not
// a prefix of the authorities it must stay away from. Deriving the root from go.mod keeps
// the rename burden in one place.
const repoRoot = "github.com/danarprastika/web-trade"

// modulePath is this module's path, read from go.mod rather than hardcoded.
func modulePath(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "go.mod"))
	if err != nil {
		t.Fatalf("reading go.mod: %v", err)
	}
	for _, line := range strings.Split(string(raw), "\n") {
		if strings.HasPrefix(line, "module ") {
			return strings.TrimSpace(strings.TrimPrefix(line, "module "))
		}
	}
	t.Fatal("go.mod has no module line")
	return ""
}

// packageFiles returns the non-test Go files of this package.
func packageFiles(t *testing.T) []string {
	t.Helper()
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("reading the package directory: %v", err)
	}
	var out []string
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		out = append(out, name)
	}
	return out
}

// parseImports returns the import paths a file declares.
func parseImports(t *testing.T, file string) []string {
	t.Helper()
	fset := token.NewFileSet()
	parsed, err := parser.ParseFile(fset, file, nil, parser.ImportsOnly)
	if err != nil {
		t.Fatalf("parsing %s: %v", file, err)
	}
	var out []string
	for _, imp := range parsed.Imports {
		out = append(out, strings.Trim(imp.Path.Value, `"`))
	}
	return out
}

// The authorization package must not reach the Risk Engine, the OMS, the ledger, or any
// external service. It decides permission; it does not act.
func TestThePackageCannotReachAnyOtherAuthority(t *testing.T) {
	for _, file := range packageFiles(t) {
		for _, imp := range parseImports(t, file) {
			switch {
			case strings.HasPrefix(imp, repoRoot+"/components/risk-engine"):
				t.Fatalf("%s imports the Risk Engine (%s); the risk authority must stay outside authorization", file, imp)
			case strings.HasPrefix(imp, repoRoot+"/components/oms"):
				t.Fatalf("%s imports the OMS (%s); authorization decides permission, it does not place orders", file, imp)
			case strings.HasPrefix(imp, repoRoot+"/services/control-plane/ledger"):
				t.Fatalf("%s imports the ledger (%s); authorization does not read financial facts", file, imp)
			case imp == "net/http", imp == "database/sql", imp == "os/exec", imp == "context",
				strings.HasPrefix(imp, "net/"), strings.HasPrefix(imp, "os/") && imp != "os":
				t.Fatalf("%s imports %q; the authorization package is pure domain logic and reaches nothing external", file, imp)
			}
		}
	}
}

// The one thing it does import from the platform is the canonical contracts package, which
// is what makes the actor type and error codes shared rather than duplicated.
func TestThePackageSharesContractsRatherThanDuplicatingIt(t *testing.T) {
	if modulePath(t) != repoRoot+"/services/control-plane" {
		t.Fatalf("this package should live in the control-plane module, but the module path is %q", modulePath(t))
	}
	found := false
	for _, file := range packageFiles(t) {
		for _, imp := range parseImports(t, file) {
			if imp == repoRoot+"/contracts/go" {
				found = true
			}
		}
	}
	if !found {
		t.Fatal("the package should use the canonical contracts package, not its own copies of shared types")
	}
}

// AC5: negative policy test vectors must exist as data, so a policy change is checked
// against a set that a reviewer can read rather than against assertions scattered through
// the suite. This pins that the vector table is non-empty and that every vector in it
// refuses.
func TestTheNegativeVectorSuiteIsNonEmptyAndEveryVectorRefuses(t *testing.T) {
	if len(negativeVectors) == 0 {
		t.Fatal("the negative vector suite is empty; AC5 requires policy test vectors")
	}
	for _, v := range negativeVectors {
		t.Run(v.name, func(t *testing.T) {
			age := v.policyAge
			if age == 0 {
				age = time.Minute
			}
			ev, err := New(Context{
				Policy:             v.policy,
				PolicyFetchedAt:    base.Add(-age),
				PermissionRevision: 7,
				FailClosed:         v.failClosed,
			})
			if err != nil {
				t.Fatalf("New: %v", err)
			}
			d := ev.Evaluate(v.request)
			if d.Allowed {
				t.Fatalf("vector %q was allowed; a negative vector that passes is not testing anything", v.name)
			}
			if d.Refusal == "" {
				t.Fatalf("vector %q was refused without naming a reason", v.name)
			}
			// The code, not just the fact of refusal. A vector that accepts any refusal
			// keeps passing after its own control is deleted, because an unrelated check
			// usually catches the same request. This is the assertion that makes removing a
			// control turn its own vector red.
			if v.expect != "" && d.Refusal != v.expect {
				t.Fatalf("vector %q was refused as %s (%s), but the control under test is supposed to refuse as %s",
					v.name, d.Refusal, d.Reason, v.expect)
			}
		})
	}
}
