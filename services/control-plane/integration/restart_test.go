//go:build integration

package integration

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/danarprastika/web-trade/services/control-plane/bootstrap"
	"github.com/danarprastika/web-trade/services/control-plane/model"
)

// buildStack assembes the durable control plane over the real SQL ports.
//
// This is the production assembly path. bootstrap.Build takes ports rather than a *sql.DB
// precisely so the composition can be driven by whichever implementations are available; here
// they are the real ones, so the wiring, the SQL and the assembly order are all under test
// together.
func buildStack(t *testing.T, ctx context.Context, db *sql.DB, partition string, at time.Time) *bootstrap.Stack {
	t.Helper()

	sink, err := audit.NewSQLSink(db)
	if err != nil {
		t.Fatalf("building the SQL sink: %v", err)
	}
	chainReader, err := audit.NewSQLChainReader(db)
	if err != nil {
		t.Fatalf("building the SQL chain reader: %v", err)
	}
	store, err := model.NewSQLStore(db)
	if err != nil {
		t.Fatalf("building the model SQL store: %v", err)
	}
	snapshot, err := model.NewSQLSnapshotReader(db)
	if err != nil {
		t.Fatalf("building the model snapshot reader: %v", err)
	}
	identity, err := model.NewSQLIdentityStore(db)
	if err != nil {
		t.Fatalf("building the identity SQL store: %v", err)
	}
	identityReader, err := model.NewSQLIdentitySnapshotReader(db)
	if err != nil {
		t.Fatalf("building the identity snapshot reader: %v", err)
	}

	stack, err := bootstrap.Build(ctx, bootstrap.Deps{
		Clock:       func() time.Time { return at },
		Environment: "SIMULATION",
		GuardLimit:  1000,
		Partitions:  []string{partition},
		Sink:        sink,
		ChainReader: chainReader,
		Store:       store,
		Snapshot:    snapshot,
		Identity:    identity,
		Identities:  identityReader,
	})
	if err != nil {
		t.Fatalf("building the stack: %v", err)
	}
	return stack
}

// The G5.7 property, executed: a control plane registers a model through its real write path,
// the process state is discarded entirely, and a second stack is built from nothing but
// PostgreSQL. The model must come back.
//
// The discard is the point. The second Build receives a fresh chain, a fresh guard, a fresh
// journal and a fresh registry, sharing no memory with the first; the only thing carried
// across is the database. If the model is present afterwards then the durable layer is
// sufficient for a restart, which is what a running process does on startup and what no
// in-memory test can claim.
func TestAModelRegisteredByOneStackSurvivesAProcessRestart(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	// A unique partition and model id, because the audit and registry tables are append-only
	// and this test may run repeatedly against the same database.
	// The partition is derived from the owner by the journal, so it is computed here only
	// so the stack can be told which partitions to rehydrate; owner is what actually names them.
	owner := uniqueOwner()
	partition := owner
	modelID := uniqueModelID()
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	// --- First process ---
	first := buildStack(t, ctx, db, partition, at)

	entry := entryWithOwner(t, modelID, owner, at)
	outcome, err := first.Journal.RegisterContext(ctx, entry.Record, contracts.ActorSystem, "author-identity")
	if err != nil {
		t.Fatalf("registering the model: %v", err)
	}
	if outcome.AuditRecord == "" {
		t.Fatal("the registration produced no audit record identity")
	}

	// Drain the audit backlog so the record is durable, which is what a process would do
	// before it exited cleanly. Without this the second stack would correctly find nothing,
	// and the test would be measuring the guard rather than the restart.
	//
	// Export takes the accepted records themselves rather than a count, and Exported is what
	// releases the backlog, so both halves are needed.
	drain(t, ctx, first)

	// Confirm the record is really in PostgreSQL, so a later pass cannot be a false negative.
	var auditRows int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.audit_records WHERE partition = $1;`,
		partition).Scan(&auditRows); err != nil {
		t.Fatalf("counting audit rows: %v", err)
	}
	if auditRows == 0 {
		t.Fatal("no audit rows were written; the restart assertion below would be vacuous")
	}
	var modelRows int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.model_registry WHERE model_id = $1;`,
		modelID).Scan(&modelRows); err != nil {
		t.Fatalf("counting registry rows: %v", err)
	}
	if modelRows != 1 {
		t.Fatalf("registry holds %d rows for %s, expected 1", modelRows, modelID)
	}

	// Drop every in-memory component. `first` goes out of scope and is never consulted again.
	_ = first

	// --- Second process, rebuilt from PostgreSQL alone ---
	second := buildStack(t, ctx, db, partition, at.Add(time.Hour))

	// The model must be known to the rebuilt journal. This is the assertion G5.7 exists for.
	state, found := second.Journal.State(mustIdentifier(t, modelID))
	if !found {
		t.Fatal("the model registered by the first stack is unknown to the second; " +
			"a restarted control plane would report it as unregistered and a caller " +
			"registering it again would write a second SUCCEEDED audit record")
	}
	if state != model.StateRegistered {
		t.Errorf("the rebuilt model is in state %q, expected %q", state, model.StateRegistered)
	}

	record, found := second.Journal.Record(mustIdentifier(t, modelID))
	if !found {
		t.Fatal("the rebuilt journal knows the model's state but not its record")
	}
	if record.Owner != entry.Record.Owner {
		t.Errorf("the rebuilt model's owner is %q, expected %q",
			record.Owner, entry.Record.Owner)
	}
	if record.TrainingDatasetFingerprint != entry.Record.TrainingDatasetFingerprint {
		t.Error("the rebuilt model's dataset fingerprint does not match what was registered")
	}

	// The audit chain must have been rehydrated too, or the journal could not have verified
	// the model against it. The records are the first stack's, not placeholders.
	if got := second.Chain.Records(partition); len(got) == 0 {
		t.Error("the rebuilt chain holds no records for the partition; the journal's " +
			"verification against the chain would have had nothing to check")
	}
}

// A restarted control plane must refuse to accept a duplicate registration rather than
// silently writing a second one. This is the operational consequence of the previous test: if
// the model came back, the second attempt has to be refused.
func TestARestartedStackRefusesToRegisterTheSameModelTwice(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	owner := uniqueOwner()
	partition := owner
	modelID := uniqueModelID()
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	first := buildStack(t, ctx, db, partition, at)
	entry := entryWithOwner(t, modelID, owner, at)
	if _, err := first.Journal.RegisterContext(
		ctx, entry.Record, contracts.ActorSystem, "author-identity"); err != nil {
		t.Fatalf("registering: %v", err)
	}
	drain(t, ctx, first)
	_ = first

	second := buildStack(t, ctx, db, partition, at.Add(time.Hour))

	// The same registration, again, after the restart. A refusal is the expected outcome and
	// it arrives as an error rather than as a success carrying a refusal marker.
	if _, err := second.Journal.RegisterContext(
		ctx, entry.Record, contracts.ActorSystem, "author-identity"); err == nil {
		t.Fatal("the restarted journal accepted a duplicate registration; the durable " +
			"state it rehydrated did not stop it")
	} else {
		t.Logf("the restarted stack refused the duplicate as expected: %v", err)
	}
}

// acceptedFrom collects the records the journal accepted but has not yet exported.
//
// The guard holds a count, not the records, so the records are taken from the chain by the
// audit identities the journal reported. Going through the chain rather than reconstructing
// them keeps the export byte-identical to what the journal produced, which is the thing whose
// hash the second stack will verify.
// uniqueModelID returns a syntactically valid, run-unique model identifier.
//
// The payload must be exactly 26 characters (contracts.ParseIdentifier enforces it), so the
// suffix is a zero-padded 4-digit counter over a fixed 22-character stem. Deriving the length
// by construction rather than by formatting a timestamp is what keeps this correct: an
// earlier version used %.4d of a nanosecond timestamp and produced 24 characters.
var modelIDSequence atomic.Int64

func uniqueModelID() string {
	return fmt.Sprintf("mdl_01hq3k7m9x2f5rb8n0v6c4%04d", modelIDSequence.Add(1)%10000)
}

// drain exports everything the stack has accepted, in the order the exporter requires.
//
// The journal writes audit records to the chain; persisting them is the caller's job, and the
// two halves must happen in this order. Accept first, because Export's final step releases the
// backlog by calling guard.Exported, and releasing records the guard never accepted is refused
// as a count mismatch. The first version of this test skipped Accept and failed with
// "cannot mark 1 records exported with 0 pending", which is the guard refusing to lose track of
// a backlog it was never told about.
func drain(t *testing.T, ctx context.Context, stack *bootstrap.Stack) {
	t.Helper()

	records := stack.Chain.AllRecords()
	if len(records) == 0 {
		t.Fatal("the stack accepted work but wrote no audit records; nothing to persist")
	}
	if err := stack.Exporter.Accept(len(records)); err != nil {
		t.Fatalf("accepting %d records: %v", len(records), err)
	}
	if err := stack.Exporter.Export(ctx, records); err != nil {
		t.Fatalf("exporting %d records: %v", len(records), err)
	}
}

// uniqueOwner returns an owner identity unique to this process.
//
// The owner matters more than it looks. The journal derives an audit record's partition from
// the model's owner rather than from any caller-supplied scope, because records chained under
// one owner's scope are the isolation boundary. So the owner is what makes the audit rows
// unique, and a fixed owner means the second run of this test collides on
// audit_records_partition_sequence_key. Two earlier failures - a duplicate partition-sequence
// violation and then a duplicate primary key - were both this, not a defect in the code.
func uniqueOwner() string {
	return fmt.Sprintf("owner-%d-%d", os.Getpid(), modelIDSequence.Add(1))
}

// entryWithOwner builds a valid RegistryEntry under a chosen owner.
//
// Owner and author must differ (model_registry_owner_differs_from_author), and the owner is
// what names the audit partition, so this is the single place a test controls both.
func entryWithOwner(t *testing.T, modelID, owner string, at time.Time) model.RegistryEntry {
	t.Helper()

	entry := validEntry(t, modelID, at)
	entry.Record.Owner = owner
	entry.UpdatedBy = owner
	return entry
}

func mustIdentifier(t *testing.T, modelID string) contracts.Identifier {
	t.Helper()
	id, err := contracts.ParseIdentifier(modelID)
	if err != nil {
		t.Fatalf("parsing %q: %v", modelID, err)
	}
	return id
}
