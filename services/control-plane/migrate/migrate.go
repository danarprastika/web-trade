// Package migrate implements the expand/contract migration runner for the control plane.
//
// docs/24 section 6 and docs/20 require expand/contract discipline, which means two things
// this package has to make true rather than merely attempt:
//
//   - A migration applies in both directions. A schema change that cannot be reversed
//     cannot be rehearsed, and docs/09 lists migration rehearsal as a release gate. An
//     up-only runner cannot satisfy that gate because it never proves the reverse.
//   - The applied set is recorded in the database, not in process memory, so that the
//     migration state is a fact about the database rather than a fact about whichever
//     process last ran.
//
// The package is split so that everything except the SQL execution is pure: the file set is
// parsed, ordered, and checked for drift without touching a database, which is what makes
// the failure modes testable. A migration runner is exactly the kind of component that
// fails silently -- it applies nothing, reports success, and the schema is simply wrong --
// so the ordering and drift checks are deliberately separate and separately tested.
package migrate

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io/fs"
	"path"
	"sort"
	"strings"
)

// Direction is which way the migration set is being applied.
type Direction string

const (
	// Up applies pending migrations.
	Up Direction = "up"
	// Down reverts applied migrations, newest first.
	Down Direction = "down"
	// Status reports without changing anything.
	Status Direction = "status"
)

// Valid reports whether the direction is one this runner implements.
func (d Direction) Valid() bool {
	switch d {
	case Up, Down, Status:
		return true
	default:
		return false
	}
}

// Migration is one migration file, parsed.
type Migration struct {
	// Version is the numeric prefix, parsed to an int so ordering is numeric rather than
	// lexical. Lexical ordering puts 00010 before 0002, which is a migration applied in the
	// wrong order against a database that happened to reach ten.
	Version int
	// Name is the full filename.
	Name string
	// SQL is the up body.
	SQL string
	// DownSQL is the down body, taken from the `-- migrate:down` marker.
	DownSQL string
	// Digest is the SHA-256 of the up body.
	//
	// It exists so that editing an already-applied migration is detected rather than
	// silently ignored. A migration that was applied and then edited leaves the database
	// and the repository disagreeing about what the schema is, and the only symptom is a
	// drift that surfaces weeks later as a query that should work and does not.
	Digest string
}

// ID is the canonical identity of a migration, used in the applied-set ledger.
func (m Migration) ID() string { return fmt.Sprintf("%06d", m.Version) }

// Set is the ordered migration set for a direction.
type Set struct {
	// Applied is the ordered set of migrations, ascending by version.
	Applied []Migration
	// Reversible is every migration that declares a down body. A set that is not fully
	// reversible cannot satisfy the down rehearsal, and the runner reports that rather
	// than quietly applying the reversible ones and stopping.
	Reversible bool
}

// Describe renders the whole set for a human, one migration per line with its state.
//
// It is separate from Plan.Describe because the two answer different questions: this one
// describes what the repository contains, and that one describes what a run would do about
// it. A --dry-run needs both, and merging them would make the output say nothing about the
// migrations that are already applied.
func (s Set) Describe() string {
	if len(s.Applied) == 0 {
		return "no migrations found"
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%d migration(s):\n", len(s.Applied))
	for _, m := range s.Applied {
		reversible := "reversible"
		if !hasStatement(m.DownSQL) {
			reversible = "NOT REVERSIBLE"
		}
		fmt.Fprintf(&b, "  %06d  %-28s %s  %s\n", m.Version, m.Name, m.Digest[:12], reversible)
	}
	return b.String()
}

// Version returns the migration with the given version.
func (s Set) Version(version int) (Migration, bool) {
	for _, m := range s.Applied {
		if m.Version == version {
			return m, true
		}
	}
	return Migration{}, false
}

// Next returns the migration to apply going up.
func (s Set) Next(applied map[int]bool) (Migration, bool) {
	for _, m := range s.Applied {
		if !applied[m.Version] {
			return m, true
		}
	}
	return Migration{}, false
}

// Last returns the migration to revert going down.
func (s Set) Last(applied map[int]bool) (Migration, bool) {
	for i := len(s.Applied) - 1; i >= 0; i-- {
		if applied[s.Applied[i].Version] {
			return s.Applied[i], true
		}
	}
	return Migration{}, false
}

// ErrDrift is returned when the database's record of what was applied disagrees with the
// repository's.
type ErrDrift struct {
	// Version is the migration that disagrees.
	Version int
	// Recorded is the digest the database holds.
	Recorded string
	// Repository is the digest the file has.
	Repository string
}

func (e ErrDrift) Error() string {
	return fmt.Sprintf(
		"migration %06d was applied with digest %s but the file now hashes to %s; "+
			"an applied migration must not be edited, add a new migration instead",
		e.Version, e.Recorded, e.Repository,
	)
}

// Option narrows a plan.
//
// The zero state is the unbounded plan, so a caller that asks for nothing keeps the whole
// applied set. That is deliberate rather than merely convenient: an unbounded down run is the
// behaviour this package shipped with, and narrowing it must not narrow it for everyone.
type Option func(*planOptions)

type planOptions struct {
	// to is the version a down plan reverts down to. Zero means no bound.
	to int
}

// DownTo bounds a down plan to the applied migrations above version.
//
// The bound exists because an unbounded down reverts the entire applied set, and on the real
// set that drops the ledger, the audit records, and every authz table CASCADE. An operator who
// has just shipped one bad migration wants that migration back, not an empty database: the
// failure this prevents is a rollback that destroys data rather than restoring the schema the
// release before it ran on.
//
// The bound is a floor, not a target to search for: the plan is the applied migrations above
// version, newest first. Everything at or below version is left alone even when it is applied.
func DownTo(version int) Option {
	return func(o *planOptions) {
		if version <= 0 {
			// Versions start at 1, so a non-positive version carries no information rather
			// than meaning "revert everything". The command refuses it explicitly, where the
			// operator can see the message; here it is simply the absence of a bound.
			return
		}
		o.to = version
	}
}

// ErrTarget is returned when a requested revert bound cannot be honoured.
//
// It is distinct from a drift error and from a plan error because the fault is not in the
// database or in the repository: the operator asked to revert to a version the database is not
// in a position to be reverted to. Rounding to a nearby version instead would revert more or
// less than was asked for, which is the one outcome a rollback must never produce, so the
// request is refused and named rather than approximated.
var ErrTarget = errors.New("the requested revert target cannot be used")

// downMarker separates the up body from the down body inside one file.
//
// A marker rather than a second file, because a down migration that lives somewhere other
// than next to its up migration is a down migration that will eventually not be found. The
// two live in one file, so they cannot drift apart in the filesystem and the pairing is
// visible in a single review.
const downMarker = "-- migrate:down"

// Parse reads an ordered migration set from a filesystem.
//
// The returned error is on the first file that is malformed, naming the file, because a
// runner that silently skips a migration it does not understand produces a schema that is
// missing something nobody was told about.
func Parse(fsys fs.FS) (Set, error) {
	entries, err := fs.Glob(fsys, "*.sql")
	if err != nil {
		return Set{}, fmt.Errorf("listing migrations: %w", err)
	}
	// Glob is sorted, but the sort is lexical and the ordering must be numeric, so the set
	// is sorted again after parsing.
	sort.Strings(entries)

	var out []Migration
	seen := map[int]string{}
	for _, name := range entries {
		raw, err := fs.ReadFile(fsys, name)
		if err != nil {
			return Set{}, fmt.Errorf("reading %s: %w", name, err)
		}
		m, err := parseOne(name, string(raw))
		if err != nil {
			return Set{}, err
		}
		// A duplicate version is a genuine hazard: the second file would never be applied
		// in ordering terms, and whichever lost is invisible. It is refused rather than
		// resolved, because picking a winner is a decision nobody should make silently.
		if other, dup := seen[m.Version]; dup {
			return Set{}, fmt.Errorf(
				"migrations %s and %s both declare version %06d; renumber one of them",
				other, name, m.Version,
			)
		}
		seen[m.Version] = name
		out = append(out, m)
	}

	sort.Slice(out, func(i, j int) bool { return out[i].Version < out[j].Version })

	reversible := true
	for _, m := range out {
		if !hasStatement(m.DownSQL) {
			reversible = false
		}
	}
	return Set{Applied: out, Reversible: reversible}, nil
}

// hasStatement reports whether a SQL fragment contains at least one real statement.
//
// A fragment that is only comments and whitespace is not a statement, and treating it as one
// makes a migration look reversible in a diff and revert nothing at runtime. This is the
// same class of problem as a silent no-op: the run reports success, the schema is unchanged,
// and the difference is only visible when someone relies on the revert having happened.
func hasStatement(fragment string) bool {
	var kept strings.Builder
	rest := fragment
	for {
		line := rest
		next := ""
		if i := strings.IndexByte(rest, '\n'); i >= 0 {
			line, next = rest[:i], rest[i+1:]
		}
		// A line comment removes the rest of the line but not the newline, so adjacent
		// commented lines do not join into one token.
		if i := strings.Index(line, "--"); i >= 0 {
			line = line[:i]
		}
		kept.WriteString(line)
		kept.WriteByte('\n')
		rest = next
		if rest == "" {
			break
		}
	}

	// Block comments are removed too, because a down body of /* nothing to do */ is the
	// same silent no-op in a different syntax.
	cleaned := kept.String()
	for {
		start := strings.Index(cleaned, "/*")
		if start < 0 {
			break
		}
		tail := cleaned[start+2:]
		end := strings.Index(tail, "*/")
		if end < 0 {
			// Unterminated block comment: nothing executable can follow it.
			return false
		}
		cleaned = cleaned[:start] + tail[end+2:]
	}
	return strings.TrimSpace(cleaned) != ""
}

// parseOne parses a single migration file.
func parseOne(name, body string) (Migration, error) {
	base := path.Base(name)
	underscore := strings.Index(base, "_")
	if underscore <= 0 {
		return Migration{}, fmt.Errorf(
			"migration %s must be named NNNN_name.sql with a numeric version prefix", name)
	}
	var version int
	if _, err := fmt.Sscanf(base[:underscore], "%d", &version); err != nil {
		return Migration{}, fmt.Errorf("migration %s: %q is not a numeric version prefix", name, base[:underscore])
	}
	if version < 1 {
		return Migration{}, fmt.Errorf("migration %s: version must be positive, got %d", name, version)
	}

	up, down, found := strings.Cut(body, downMarker)
	if !found {
		down = ""
	}

	// The digest covers the up body only. A down body is added in a later change far more
	// often than an up body is edited, and refusing to start a database because a
	// down script gained a comment would make the drift check unusable.
	sum := sha256.Sum256([]byte(up))
	return Migration{
		Version: version,
		Name:    base,
		SQL:     up,
		// A down body with no statement in it is not a down body. Stripping comments and
		// whitespace before testing means `-- nothing to do` does not count as reversible.
		DownSQL: down,
		Digest:  hex.EncodeToString(sum[:]),
	}, nil
}

// CheckDrift compares the database's applied-set ledger against the repository's files.
//
// This is the check that makes an edited migration an error rather than a surprise. It
// runs before any migration is applied, in both directions, because the direction does not
// change the fact that the two records disagree.
func CheckDrift(set Set, applied map[int]string) error {
	versions := make([]int, 0, len(applied))
	for v := range applied {
		versions = append(versions, v)
	}
	sort.Ints(versions)

	for _, v := range versions {
		recorded := applied[v]
		m, ok := set.Version(v)
		if !ok {
			return fmt.Errorf(
				"migration %06d is recorded as applied but no such file exists; "+
					"the database was migrated from a branch that is not this one", v)
		}
		if recorded != m.Digest {
			return ErrDrift{Version: v, Recorded: recorded, Repository: m.Digest}
		}
	}
	return nil
}

// Plan is what a run would do, computed without touching the database.
//
// It exists so the runner can print a plan and a dry run can print the same plan, without
// the two being separate implementations that can disagree. A dry run that reports
// something different from what the real run does is worse than no dry run.
type Plan struct {
	// Direction is the direction being applied.
	Direction Direction
	// Steps are the migrations to apply or revert, in execution order.
	Steps []Migration
}

// Describe renders the plan for a human, one migration per line.
//
// The rendering names the version and filename rather than the version alone, because a
// person reviewing a plan needs to recognise the file, and a version number does not tell
// them what is in it.
func (p Plan) Describe() string {
	if len(p.Steps) == 0 {
		return fmt.Sprintf("nothing to %s: the database is already at the repository's state", p.verb())
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%s %d migration(s):\n", p.verb(), len(p.Steps))
	for _, m := range p.Steps {
		fmt.Fprintf(&b, "  %06d  %s\n", m.Version, m.Name)
	}
	return b.String()
}

// verb is the human-facing action for a direction.
//
// It is a function of the direction rather than of the call site so the empty-plan message
// and the non-empty one cannot disagree: "nothing to up" is a message no reader can act on.
func (p Plan) verb() string {
	switch p.Direction {
	case Down:
		return "revert"
	case Status:
		return "report on"
	default:
		return "apply"
	}
}

// Plan computes the run against a known applied-set ledger.
//
// The options narrow what the plan covers; see Option. The reversal check at the end applies
// to the steps the plan actually contains, so a bounded revert is only refused when a
// migration it would revert is irreversible, not because some migration it would leave in
// place is.
func (s Set) Plan(d Direction, applied map[int]bool, opts ...Option) (Plan, error) {
	var o planOptions
	for _, opt := range opts {
		opt(&o)
	}
	if o.to > 0 && d != Down {
		return Plan{}, fmt.Errorf("%w: a revert target applies to a down run, not to %q", ErrTarget, d)
	}

	p := Plan{Direction: d}
	switch d {
	case Up:
		for _, m := range s.Applied {
			if !applied[m.Version] {
				p.Steps = append(p.Steps, m)
			}
		}
	case Down:
		if err := s.checkTarget(o.to, applied); err != nil {
			return Plan{}, err
		}
		for i := len(s.Applied) - 1; i >= 0; i-- {
			m := s.Applied[i]
			if !applied[m.Version] {
				continue
			}
			if o.to > 0 && m.Version <= o.to {
				// Versions ascend, so the first applied migration at or below the bound ends
				// the suffix. Everything applied above it is reverted; nothing below it is
				// touched, which is the whole point of the bound.
				break
			}
			p.Steps = append(p.Steps, m)
		}
	case Status:
		for _, m := range s.Applied {
			p.Steps = append(p.Steps, m)
		}
	default:
		return Plan{}, fmt.Errorf("unknown direction %q", d)
	}
	if d == Down && len(p.Steps) > 0 {
		// The down rehearsal is a gate, so a set that cannot be fully reverted is reported
		// rather than partially reverted. Reverting three of four and stopping looks like
		// success in a log and leaves the schema in a state no release ever planned.
		var missing []string
		for _, m := range p.Steps {
			if !hasStatement(m.DownSQL) {
				missing = append(missing, m.Name)
			}
		}
		if len(missing) > 0 {
			return Plan{}, fmt.Errorf(
				"cannot revert: %s declare no %s body; the down rehearsal requires every "+
					"applied migration to be reversible", strings.Join(missing, ", "), downMarker)
		}
	}
	return p, nil
}

// checkTarget refuses a bound the database cannot be reverted to.
//
// Two refusals and no third. A version the repository does not have is a typo or a version
// from another branch, and a version the database has not applied is a version that is
// already reverted or was never applied. Both are refused rather than resolved, because the
// nearest sensible-looking interpretation of a wrong target is a rollback that reverts more
// than the operator asked for.
func (s Set) checkTarget(version int, applied map[int]bool) error {
	if version <= 0 {
		return nil
	}
	if _, ok := s.Version(version); !ok {
		newest := 0
		if len(s.Applied) > 0 {
			newest = s.Applied[len(s.Applied)-1].Version
		}
		return fmt.Errorf("%w: migration %06d is not in the repository set; "+
			"the newest migration here is %06d, so there is nothing to revert down to %06d",
			ErrTarget, version, newest, version)
	}
	if !applied[version] {
		return fmt.Errorf("%w: migration %06d is in the repository but is not in the "+
			"database's applied set, so the database is already below it or was never "+
			"migrated that far; revert to a version the applied set actually contains",
			ErrTarget, version)
	}
	return nil
}
