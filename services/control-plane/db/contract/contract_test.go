// Package contract holds checks between the checked-in SQL and the code generated from it.
//
// The generated package says DO NOT EDIT, so nothing stops someone adding a query and
// forgetting to regenerate, and nothing stops them editing the generated file by hand. Both
// leave the repository in a state that builds and behaves unexpectedly: a query with no
// accessor is a query nothing can call, and a hand-edited accessor is code that the next
// `sqlc generate` silently discards. Neither shows up as a compile error.
package contract

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

const (
	queriesDir = "../queries"
	generated  = "../dbgen/querier.go"
)

// queryName matches a sqlc query header: `-- name: GetEntry :one`.
var queryName = regexp.MustCompile(`(?m)^--\s+name:\s+(\w+)\s+:(\w+)`)

// generatedMethod matches a method on the generated Querier interface.
var generatedMethod = regexp.MustCompile(`(?m)^\t([A-Z]\w*)\(ctx context\.Context`)

// declaredQueryNames returns every query declared across the query files.
func declaredQueryNames(t *testing.T) map[string]string {
	t.Helper()
	entries, err := os.ReadDir(queriesDir)
	if err != nil {
		t.Fatalf("reading %s: %v", queriesDir, err)
	}
	found := map[string]string{}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".sql") {
			continue
		}
		body, err := os.ReadFile(filepath.Join(queriesDir, e.Name()))
		if err != nil {
			t.Fatalf("reading %s: %v", e.Name(), err)
		}
		for _, m := range queryName.FindAllStringSubmatch(string(body), -1) {
			name := m[1]
			if prev, dup := found[name]; dup {
				t.Fatalf("query %s is declared in both %s and %s; one of them is unreachable",
					name, prev, e.Name())
			}
			found[name] = e.Name()
		}
	}
	if len(found) == 0 {
		t.Fatalf("no queries declared in %s; the pattern or the directory is wrong", queriesDir)
	}
	return found
}

func generatedMethodNames(t *testing.T) map[string]bool {
	t.Helper()
	body, err := os.ReadFile(generated)
	if err != nil {
		t.Fatalf("reading %s: %v (has `sqlc generate` been run?)", generated, err)
	}
	if !strings.Contains(string(body), "DO NOT EDIT") {
		t.Fatalf("%s is missing the DO NOT EDIT header, so this is not sqlc output", generated)
	}
	out := map[string]bool{}
	for _, m := range generatedMethod.FindAllStringSubmatch(string(body), -1) {
		out[m[1]] = true
	}
	return out
}

// A query with no accessor is a query nothing can call. This is the check that fails when
// someone adds a query file and does not regenerate.
func TestEveryDeclaredQueryHasAGeneratedAccessor(t *testing.T) {
	declared := declaredQueryNames(t)
	methods := generatedMethodNames(t)

	var missing []string
	for name, file := range declared {
		if !methods[name] {
			missing = append(missing, name+" ("+file+")")
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		t.Fatalf("these queries have no generated accessor: %s\nrun `sqlc generate`",
			strings.Join(missing, ", "))
	}
}

// The reverse direction. A method with no query means the generated file was hand-edited,
// which the next `sqlc generate` will remove.
func TestEveryGeneratedAccessorHasADeclaredQuery(t *testing.T) {
	declared := declaredQueryNames(t)
	methods := generatedMethodNames(t)

	var orphans []string
	for name := range methods {
		if _, ok := declared[name]; !ok {
			orphans = append(orphans, name)
		}
	}
	if len(orphans) > 0 {
		sort.Strings(orphans)
		t.Fatalf("these accessors have no query: %s\nthe generated file has been edited by "+
			"hand, and `sqlc generate` will discard the change", strings.Join(orphans, ", "))
	}
}

// The header records the generator version, so a stale generated file is identifiable from
// the file itself rather than only by noticing behaviour that no longer matches.
func TestTheGeneratedFileRecordsItsGeneratorVersion(t *testing.T) {
	body, err := os.ReadFile(generated)
	if err != nil {
		t.Fatalf("reading %s: %v", generated, err)
	}
	if !regexp.MustCompile(`sqlc v\d+\.\d+\.\d+`).Match(body) {
		t.Fatalf("%s does not record the sqlc version that produced it", generated)
	}
}
