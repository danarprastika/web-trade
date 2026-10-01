package migrate

import "testing"

// The store's central promise is that a migration body and the record of that body commit
// together, so a database can never be left with a schema ahead of its own record. That
// promise is now load-bearing on stripTxControl removing the body's own COMMIT, which means
// the stripping has to be shown not to break atomicity rather than assumed not to.
func TestStripTxControlRemovesEveryTransactionStatement(t *testing.T) {
	cases := []struct {
		name string
		body string
		want string
	}{
		{
			name: "the real 0001 shape, with a comment between the statements",
			body: "BEGIN;\n\n-- create the ledger schema\nCREATE SCHEMA ledger;\n\nCOMMIT;\n",
			want: "\n\n-- create the ledger schema\nCREATE SCHEMA ledger;\n\n\n",
		},
		{
			name: "start transaction spelled out",
			body: "START TRANSACTION;\nCREATE TABLE t (id int);\nCOMMIT;",
			want: "\nCREATE TABLE t (id int);\n",
		},
		{
			name: "rollback is removed too, so the store's own rollback governs",
			body: "BEGIN;\nROLLBACK;\nSELECT 1;",
			want: "\n\nSELECT 1;",
		},
		{
			// The pattern consumes the whole line, indentation included. Leaving the leading
			// spaces behind would put a whitespace-only line inside the transaction, which is
			// harmless but makes the stripped body harder to read in an error message.
			name: "indented control statements are removed with their indentation",
			body: "  BEGIN;\n  CREATE TABLE t (id int);\n  COMMIT;",
			want: "\n  CREATE TABLE t (id int);\n",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := stripTxControl(tc.body)
			if got != tc.want {
				t.Errorf("stripTxControl(%q)\n got: %q\nwant: %q", tc.body, got, tc.want)
			}
		})
	}
}

// A body whose statements survive stripping is the only thing that makes the store's
// transaction meaningful; if stripping ate real SQL the migrations would silently apply
// nothing and every other test in this package would pass against an empty catalog.
func TestStripTxControlLeavesRealStatementsAlone(t *testing.T) {
	body := "BEGIN;\n" +
		"CREATE TABLE example (id integer PRIMARY KEY);\n" +
		"CREATE INDEX example_id_idx ON example (id);\n" +
		"COMMENT ON TABLE example IS 'an example';\n" +
		"COMMIT;"

	got := stripTxControl(body)

	for _, want := range []string{
		"CREATE TABLE example",
		"CREATE INDEX example_id_idx",
		"COMMENT ON TABLE example",
	} {
		if !contains(got, want) {
			t.Errorf("stripTxControl dropped %q; body was %q", want, body)
		}
	}
	if contains(got, "BEGIN") || contains(got, "COMMIT") {
		t.Errorf("stripTxControl left transaction control behind: %q", got)
	}
}

// A word appearing inside a statement must not be mistaken for transaction control. The
// pattern is anchored to a whole line and requires a trailing semicolon precisely so that
// `COMMIT` inside a comment or an identifier cannot be stripped as if it were a statement.
func TestStripTxControlDoesNotStripWordsInsideStatements(t *testing.T) {
	body := "BEGIN;\n" +
		"CREATE TABLE commits (id int);\n" +
		"-- the rollback path is documented here;\n" +
		"INSERT INTO commits VALUES (1);\n" +
		"COMMIT;"

	got := stripTxControl(body)

	if !contains(got, "CREATE TABLE commits") {
		t.Error("stripTxControl mangled a table named commits")
	}
	if !contains(got, "INSERT INTO commits VALUES (1)") {
		t.Error("stripTxControl mangled a statement mentioning commits")
	}
	if !contains(got, "the rollback path is documented here") {
		t.Error("stripTxControl mangled a comment")
	}
}

func contains(haystack, needle string) bool {
	return len(haystack) >= len(needle) && indexOf(haystack, needle) >= 0
}

func indexOf(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}
