package contracts_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// forbiddenFloatTypes are the IEEE-754 binary floating-point type names.
//
// The rule is not stylistic. A float64 has a 53-bit mantissa, so 0.1 is not
// representable, and a value that rounds on the way into this platform is a defect no later
// stage can repair. decimal.schema.json states the contract directly: "No IEEE-754
// floating point may cross a financial contract". A type-level guarantee erodes silently,
// so this check exists to fail loudly the first time one appears.
var forbiddenFloatTypes = []string{"float64", "float32"}

// TestNoIEEEFloatInGoCode scans every Go file in the workspace and fails on any use of a
// binary floating-point type outside a comment or a string literal.
//
// It is a source scan rather than a type-level assertion because a float can be introduced
// by a single stray conversion, and by then the damage is already committed. The check runs
// over the whole workspace rather than only this module, so a float introduced in a
// component is caught even though the contracts package is clean.
func TestNoIEEEFloatInGoCode(t *testing.T) {
	root := workspaceRoot(t)

	// Third-party and generated code is out of scope. A JavaScript dependency under
	// node_modules ships Go source for its own benchmarks, and holding vendored code to
	// this repository's contract would be both wrong and unfixable here.
	skipDir := map[string]bool{
		"node_modules": true,
		"vendor":       true,
		"testdata":     true,
		"dist":         true,
		"build":        true,
	}

	var scanned int
	for _, dir := range moduleDirs(t, root) {
		err := filepath.Walk(dir, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return err
			}
			if info.IsDir() {
				name := info.Name()
				if path != dir && (skipDir[name] || strings.HasPrefix(name, ".")) {
					return filepath.SkipDir
				}
				return nil
			}
			if !strings.HasSuffix(path, ".go") {
				return nil
			}
			// Skip this file: it necessarily names the forbidden types in order to search
			// for them.
			if info.Name() == "no_float_test.go" {
				return nil
			}
			scanned++
			if line, token, bad := scanFileForFloats(path); bad {
				t.Errorf("%s contains %q in code: %s\n  a financial value that rounds on "+
					"the way in is a defect; use the exact decimal types instead",
					relTo(root, path), token, strings.TrimSpace(line))
			}
			return nil
		})
		if err != nil {
			t.Fatalf("walking %s: %v", relTo(root, dir), err)
		}
	}

	if scanned == 0 {
		t.Fatal("scanned zero Go files; the workspace root was probably resolved wrongly, " +
			"which would make this guard pass without checking anything")
	}
	t.Logf("scanned %d Go files across the workspace", scanned)
}

// scanFileForFloats returns the first line that uses a forbidden type in code, with the
// token and a flag. Comments and string literals are excluded, so prose explaining why
// floats are banned does not trip the guard, while an actual conversion does.
func scanFileForFloats(path string) (line, token string, found bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", "", false
	}
	for _, l := range strings.Split(string(data), "\n") {
		code := stripCommentsAndStrings(l)
		for _, bad := range forbiddenFloatTypes {
			if strings.Contains(code, bad) {
				return l, bad, true
			}
		}
	}
	return "", "", false
}

// stripCommentsAndStrings removes string and rune literal contents and everything from an
// unquoted "//" onward, leaving only executable code.
//
// It tracks quoting rather than using strings.Split, because a naive split on "//" would
// mangle a line containing a URL string and could hide a real violation later on that same
// line. For a guard, a false pass is worse than a false alarm.
func stripCommentsAndStrings(line string) string {
	var b strings.Builder
	inString, inRune, escaped := false, false, false
	for i := 0; i < len(line); i++ {
		c := line[i]
		switch {
		case escaped:
			escaped = false
		case c == '\\' && (inString || inRune):
			escaped = true
		case c == '"' && !inRune:
			inString = !inString
		case c == '\'' && !inString:
			inRune = !inRune
		case inString || inRune:
			// literal content, dropped
		case c == '/' && i+1 < len(line) && line[i+1] == '/':
			return b.String()
		default:
			b.WriteByte(c)
		}
	}
	return b.String()
}

// workspaceRoot walks up from the test's directory to the directory holding go.work.
func workspaceRoot(t *testing.T) string {
	t.Helper()
	dir, err := os.Getwd()
	if err != nil {
		t.Fatalf("Getwd: %v", err)
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.work")); err == nil {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			t.Fatal("could not find go.work above the test directory; " +
				"the workspace root is required to scan every module")
		}
		dir = parent
	}
}

// moduleDirs returns the module directories declared in the workspace file, so the scan
// covers exactly the modules the platform builds and no more.
func moduleDirs(t *testing.T, root string) []string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(root, "go.work"))
	if err != nil {
		t.Fatalf("reading go.work: %v", err)
	}
	var dirs []string
	inUse := false
	for _, raw := range strings.Split(string(data), "\n") {
		line := strings.TrimSpace(stripCommentsAndStrings(raw))
		if line == "" {
			continue
		}
		if line == "use (" {
			inUse = true
			continue
		}
		if inUse && line == ")" {
			inUse = false
			continue
		}
		if inUse {
			dirs = append(dirs, filepath.Join(root, strings.Trim(line, `"`)))
			continue
		}
		if rest, ok := strings.CutPrefix(line, "use "); ok {
			dirs = append(dirs, filepath.Join(root, strings.Trim(strings.TrimSpace(rest), `"`)))
		}
	}
	if len(dirs) == 0 {
		t.Fatal("go.work declared no modules; the guard would scan nothing")
	}
	return dirs
}

func relTo(root, path string) string {
	r, err := filepath.Rel(root, path)
	if err != nil {
		return path
	}
	return r
}
