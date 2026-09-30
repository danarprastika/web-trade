package ledger

import (
	"reflect"
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Helpers shared by the test files. They exist so the tests can talk about intent
// ("the ledger has an update method") rather than about reflection boilerplate.

func reflectTypeOfStore() reflect.Type {
	return reflect.TypeOf((*Store)(nil)).Elem()
}

func reflectTypeOfMemoryStore() reflect.Type {
	return reflect.TypeOf((*MemoryStore)(nil))
}

func containsSubstring(haystack, needle string) bool {
	return strings.Contains(haystack, needle)
}

// decimalsEqual compares two decimals through Cmp, since contracts.Decimal has no Equal
// method: a test that used == on a Decimal would be comparing struct identity, not value.
func decimalsEqual(t *testing.T, a, b contracts.Decimal) bool {
	t.Helper()
	cmp, err := a.Cmp(b)
	if err != nil {
		t.Fatalf("comparing %s and %s: %v", a, b, err)
	}
	return cmp == 0
}
