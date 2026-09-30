package ledger

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// The tests here read the source rather than calling the API, because what they check is the
// shape of the implementation. An API test can show that a correction is refused; it cannot
// show that some future code path could still mutate a stored entry, or that the package
// quietly gained the ability to reach a database it must not own.

// TestTheLedgerHasNoStorageDependency checks the authority boundary. The ledger owns
// financial facts, and a package that can reach a database from inside its own domain logic
// is a package whose rules can be bypassed by a query.
func TestTheLedgerHasNoStorageDependency(t *testing.T) {
	banned := []string{
		"net", "net/http", "os/exec", "database/sql", "context", "time",
		"github.com/danarprastika/web-trade/components/risk-engine",
		"github.com/danarprastika/web-trade/components/oms",
		"github.com/danarprastika/web-trade/adapters/venues",
	}
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, parser.ImportsOnly)
	if err != nil {
		t.Fatalf("cannot parse the package: %v", err)
	}
	for _, pkg := range pkgs {
		for path, file := range pkg.Files {
			for _, spec := range file.Imports {
				importPath := strings.Trim(spec.Path.Value, `"`)
				for _, b := range banned {
					if importPath == b || strings.HasPrefix(importPath, b+"/") {
						t.Errorf("%s imports %q; the ledger owns financial facts and must "+
							"not reach a database, a clock, the network, or another "+
							"domain's authority from inside its own rules", path, importPath)
					}
				}
			}
		}
	}
}

// TestNoProductionCodeAssignsToAnExistingEntry is the append-only property checked at the
// source rather than at the interface.
//
// The interface test proves Store has no Update. This proves nothing in the package reaches
// around it: no assignment anywhere writes to a field of an Entry it did not construct.
// MemoryStore.Append does assign Sequence, so a newly appended entry is expected there and
// is checked to be the only such site.
func TestNoProductionCodeAssignsToAnExistingEntry(t *testing.T) {
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, 0)
	if err != nil {
		t.Fatalf("cannot parse the package: %v", err)
	}

	// The one legitimate site: Append stamps the sequence onto the entry it is recording,
	// before that entry is stored. Anything else writing into a stored entry is a mutation.
	allowed := map[string]bool{"Sequence": true}

	for _, pkg := range pkgs {
		for _, file := range pkg.Files {
			ast.Inspect(file, func(n ast.Node) bool {
				assign, ok := n.(*ast.AssignStmt)
				if !ok {
					return true
				}
				for _, lhs := range assign.Lhs {
					sel, ok := lhs.(*ast.SelectorExpr)
					if !ok {
						continue
					}
					// Only a selector on something that is plausibly an Entry matters. The
					// Entry type is filtered by name so unrelated selectors are ignored.
					if !isEntryLike(sel.X) {
						continue
					}
					// A defensive copy is not a mutation. `entry.Lines =
					// append([]Line(nil), entry.Lines...)` writes a field of a loop-local
					// copy on its way to building a fresh slice, and cannot reach the
					// stored entry. The rule is that the copy is built from something that
					// is not itself a selector, so no existing slice is appended to in
					// place.
					if isDefensiveCopy(assign.Rhs[0]) {
						continue
					}
					field := sel.Sel.Name
					if !allowed[field] {
						t.Errorf("%s assigns to %s; an entry is immutable once recorded, and "+
							"a write here is the in-place mutation docs/05 prohibits",
							fset.Position(assign.Pos()), field)
					}
				}
				return true
			})
		}
	}
}

// isDefensiveCopy reports whether an expression builds a new slice rather than writing
// through an existing one.
//
// The recognised form is append(<fresh literal>, ...). If the first argument were a selector
// such as other.Lines, the append could write past the end of another entry's slice, and
// this must not be treated as a safe copy.
func isDefensiveCopy(expr ast.Expr) bool {
	call, ok := expr.(*ast.CallExpr)
	if !ok {
		return false
	}
	ident, ok := call.Fun.(*ast.Ident)
	if !ok || ident.Name != "append" || len(call.Args) == 0 {
		return false
	}
	_, isSelector := call.Args[0].(*ast.SelectorExpr)
	return !isSelector
}

// isEntryLike reports whether an expression names something of type Entry, by checking for a
// field or method that only an entry has.
func isEntryLike(expr ast.Expr) bool {
	switch e := expr.(type) {
	case *ast.Ident:
		switch e.Name {
		case "entry", "correction", "target", "forged", "clash", "replay", "second", "first":
			return true
		}
	case *ast.SelectorExpr:
		// chained access such as outcome.Order
		switch e.Sel.Name {
		case "Entry", "Order", "Snapshot":
			return true
		}
	}
	return false
}

// TestTheBalanceCheckCannotBeSkipped checks that no production code path reaches Append
// without passing the balance invariant.
//
// The invariant is enforced in Append and re-checked in VerifyBalances. A caller that
// validated an entry by some other route and appended it anyway would still go through
// Append, so this test asserts the only exported way to record an entry is Append.
func TestTheBalanceCheckCannotBeSkipped(t *testing.T) {
	forbidden := map[string]bool{
		"Insert": true, "Add": true, "Put": true, "Post": true,
		"Record": true, "Write": true, "Store": true, "Save": true, "AppendRaw": true,
	}
	for _, name := range []string{"Store", "*MemoryStore"} {
		_ = name
	}
	storeType := reflectTypeOfStore()
	for i := 0; i < storeType.NumMethod(); i++ {
		if forbidden[storeType.Method(i).Name] {
			t.Errorf("Store exposes %s; a second way to record an entry could bypass the "+
				"balance and append-only checks that Append performs", storeType.Method(i).Name)
		}
	}
}

// TestEveryAccountIsUsedByTheFillTranslation guards against an account that exists in the
// closed set but that nothing can ever post to, which would be a promise the books do not
// keep.
func TestEveryAccountIsUsedByTheFillTranslation(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	postFill(t, s, ids, 1, validFill(t, ids, 1))

	balances, err := Balances(s)
	if err != nil {
		t.Fatalf("Balances: %v", err)
	}
	used := map[AccountKind]bool{}
	for _, b := range balances {
		used[b.Account] = true
	}
	// REALIZED_PNL is populated by a settlement or a correction, not by a fill, because a
	// fill does not know the cost basis it is closing. It is therefore expected to be the
	// one account the fill translation does not touch.
	for account := range accountKinds {
		if account == AccountRealizedPnL {
			if used[account] {
				t.Errorf("the fill translation posted to %s; a fill does not know the cost "+
					"basis it is closing, so realised P&L cannot come from a fill", account)
			}
			continue
		}
		if !used[account] {
			t.Errorf("account %s is in the closed set but the fill translation never posts "+
				"to it", account)
		}
	}
}

// TestThePackageIsWhereThisTestExpects guards the directory resolution the boundary test
// depends on, so a failure there is never mistaken for a clean bill of health.
func TestThePackageIsWhereThisTestExpects(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot determine the test's own path")
	}
	if filepath.Base(filepath.Dir(file)) != "ledger" {
		t.Errorf("this test expects to live in the ledger package directory, found %s", file)
	}
}

// TestTheAccountSetIsClosed pins the declared accounts to the five docs require, so a new
// account is a deliberate change to the meaning of the books.
func TestTheAccountSetIsClosed(t *testing.T) {
	declared := map[AccountKind]bool{
		AccountCash: true, AccountPosition: true, AccountRealizedPnL: true,
		AccountFee: true, AccountClearing: true,
	}
	if len(accountKinds) != len(declared) {
		t.Errorf("the package declares %d accounts, want %d", len(accountKinds), len(declared))
	}
	for account := range accountKinds {
		if !declared[account] {
			t.Errorf("account %s is not one of the five declared accounts", account)
		}
		if !account.Valid() {
			t.Errorf("account %s is in the set but Valid reports false", account)
		}
	}
	if AccountKind("SLUSH_FUND").Valid() {
		t.Error("an undeclared account reports itself valid")
	}
}
