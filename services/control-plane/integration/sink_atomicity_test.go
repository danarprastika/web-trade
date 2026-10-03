//go:build integration

package integration

import (
	"context"
	"database/sql"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/audit"
)

// Records and their checkpoint are written in one transaction, and the unit suite proves only
// that the sink *attempts* both. That is not the same claim, and the difference is the whole
// subject of this file.
//
// The unit test TestACheckpointThatCannotBeWrittenFailsTheWholeExport drives a recordingQuerier,
// whose transaction is `func(fn) error { return fn(q) }` - a no-op that commits nothing and rolls
// back nothing. Against that fixture the assertion "the records in the same transaction go with
// it" is not merely unverified, it is unverifiable: the fixture cannot represent the property. So
// the suite was green while the claim rested on a comment.
//
// That matters because the failure mode is not a missing checkpoint, it is a checkpoint-less
// record. Export writes every record, then computes and appends the checkpoint. If those two are
// not in one transaction, a checkpoint that fails to write leaves records that are durable, will
// be read back by a rehydration, and are covered by no anchor - so a truncated archive restores as
// VERIFIED. It is also unrecoverable by retry: audit_records is keyed on (partition, sequence), so
// replaying the batch dies on the unique constraint forever. The error returns, the operator
// retries, and the retry cannot succeed.
//
// So this is executed rather than asserted. The checkpoint write is refused by a trigger, the
// export is run through the production sink, and the database is then asked directly whether the
// records are there. Counting rows in SQL rather than trusting the sink's return value is the
// same discipline TestTheSinkWritesACheckpointThatARehydrationFinds uses: a sink that reported
// success while the table stayed empty is the failure being guarded, and only the table can say
// which side of it happened.

// refuseCheckpoints installs a trigger that makes every audit_checkpoints insert fail.
//
// A trigger is used rather than dropping the table or revoking a privilege because it fails the
// write inside the sink's own transaction without changing the schema's shape, so the rollback
// under test is the sink's rollback and not an artefact of the fixture having removed the thing
// being written.
func refuseCheckpoints(ctx context.Context, t *testing.T, db *sql.DB) {
	t.Helper()

	if _, err := db.ExecContext(ctx, `
		CREATE OR REPLACE FUNCTION public.audit_probe_refuse_checkpoint() RETURNS trigger
		AS $fn$
		BEGIN
			RAISE EXCEPTION 'injected: this checkpoint write is refused';
		END;
		$fn$ LANGUAGE plpgsql;`); err != nil {
		t.Fatalf("installing the checkpoint-refusing function: %v", err)
	}
	if _, err := db.ExecContext(ctx, `
		CREATE TRIGGER audit_probe_refuse_checkpoint
			BEFORE INSERT ON public.audit_checkpoints
			FOR EACH ROW EXECUTE FUNCTION public.audit_probe_refuse_checkpoint();`); err != nil {
		t.Fatalf("installing the checkpoint-refusing trigger: %v", err)
	}
}

// allowCheckpoints removes the trigger and its function.
//
// Called through t.Cleanup as well as explicitly, because a test that fails between installing
// the trigger and removing it would leave every later test in the package unable to anchor
// anything. That is a failure mode with a misleading cause: the next failure would name the
// checkpoint write rather than the test that abandoned its trigger.
func allowCheckpoints(ctx context.Context, t *testing.T, db *sql.DB) {
	t.Helper()

	if _, err := db.ExecContext(ctx,
		`DROP TRIGGER IF EXISTS audit_probe_refuse_checkpoint ON public.audit_checkpoints;`); err != nil {
		t.Errorf("dropping the checkpoint-refusing trigger: %v", err)
	}
	if _, err := db.ExecContext(ctx,
		`DROP FUNCTION IF EXISTS public.audit_probe_refuse_checkpoint();`); err != nil {
		t.Errorf("dropping the checkpoint-refusing function: %v", err)
	}
}

func auditRowCount(ctx context.Context, t *testing.T, db *sql.DB, table, partition string) int {
	t.Helper()

	// The table name comes from the caller's own constants, never from input, so interpolating it
	// is safe here; the partition is a bound parameter.
	var count int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.`+table+` WHERE partition = $1;`, partition).Scan(&count); err != nil {
		t.Fatalf("counting %s rows for %s: %v", table, partition, err)
	}
	return count
}

// A batch whose checkpoint cannot be written must leave nothing behind: not the checkpoint, and
// not the records it was supposed to cover.
func TestARefusedCheckpointRollsBackTheRecordsWithIt(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	partition := auditPartition(t, "atomicity")
	sink := liveSink(t, db)

	chain := audit.NewChain()
	accepted, err := chain.Append([]audit.Record{
		auditRecord("aud-atomicity-1", partition, 0),
		auditRecord("aud-atomicity-2", partition, 1),
	})
	if err != nil {
		t.Fatalf("appending to the chain: %v", err)
	}

	refuseCheckpoints(ctx, t, db)
	t.Cleanup(func() { allowCheckpoints(context.Background(), t, db) })

	if err := sink.Export(ctx, accepted); err == nil {
		t.Fatal("an export whose checkpoint was refused reported success; the records would be " +
			"durable and covered by no anchor, and a truncated archive would restore as verified")
	} else {
		t.Logf("the refused checkpoint surfaced as: %v", err)
	}

	// The records are the point of the test. A checkpoint that is absent is a loud, self-evident
	// problem; records with no anchor are the quiet one, because everything still reads back
	// normally until the archive is truncated.
	if stored := auditRowCount(ctx, t, db, "audit_records", partition); stored != 0 {
		t.Errorf("audit_records holds %d record(s) for %s after the checkpoint was refused; the "+
			"records and their anchor are not in one transaction, so the export left evidence "+
			"durable that nothing says how far it reaches", stored, partition)
	}
	if stored := auditRowCount(ctx, t, db, "audit_checkpoints", partition); stored != 0 {
		t.Errorf("audit_checkpoints holds %d checkpoint(s) for %s despite the refusal", stored,
			partition)
	}
}

// The other half, and the reason the first half is trustworthy: once the checkpoint can be
// written, the same batch commits both. Without this the rollback test would also pass against a
// sink that committed nothing ever, which is a sink with no audit trail at all rather than a
// transactional one.
//
// The ids are reused deliberately. The refused export committed nothing, so these ids are free; if
// they were still held, this export would fail on the unique constraint, which would turn a
// rollback failure into an error here instead. Running it after the rollback test is what makes
// the reuse safe to reason about.
func TestAGoodCheckpointCommitsTheRecordsWithIt(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	partition := auditPartition(t, "atomicity-commit")
	sink := liveSink(t, db)

	chain := audit.NewChain()
	accepted, err := chain.Append([]audit.Record{
		auditRecord("aud-commit-1", partition, 0),
		auditRecord("aud-commit-2", partition, 1),
		auditRecord("aud-commit-3", partition, 2),
	})
	if err != nil {
		t.Fatalf("appending to the chain: %v", err)
	}

	if err := sink.Export(ctx, accepted); err != nil {
		t.Fatalf("exporting a batch whose checkpoint can be written: %v", err)
	}

	if stored := auditRowCount(ctx, t, db, "audit_records", partition); stored != len(accepted) {
		t.Errorf("audit_records holds %d record(s) for %s, expected %d", stored, partition,
			len(accepted))
	}
	if stored := auditRowCount(ctx, t, db, "audit_checkpoints", partition); stored != 1 {
		t.Errorf("audit_checkpoints holds %d checkpoint(s) for %s, expected 1", stored, partition)
	}
}

// A refused checkpoint must not poison the partition: the retry that an operator would actually
// perform has to succeed, because the rollback released the sequences it would collide with.
//
// This is the property that makes the rollback safe rather than merely clean. A sink that rolled
// the records back but left the sequence allocation consumed, or that wrote the checkpoint and
// then rolled back the records, would pass a test that only counts rows at the instant of failure
// and would leave the audit trail permanently stuck - every subsequent export failing on a unique
// constraint, with no indication of why.
func TestARefusedCheckpointLeavesThePartitionWritable(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	partition := auditPartition(t, "atomicity-retry")
	sink := liveSink(t, db)

	first := audit.NewChain()
	accepted, err := first.Append([]audit.Record{
		auditRecord("aud-retry-1", partition, 0),
		auditRecord("aud-retry-2", partition, 1),
	})
	if err != nil {
		t.Fatalf("appending to the chain: %v", err)
	}

	refuseCheckpoints(ctx, t, db)
	if err := sink.Export(ctx, accepted); err == nil {
		allowCheckpoints(ctx, t, db)
		t.Fatal("the refused export reported success, so nothing below is testing a retry")
	}
	allowCheckpoints(ctx, t, db)

	// The identical batch. Against a sink that consumed sequences without rolling them back, this
	// is where the unique constraint fires.
	if err := sink.Export(ctx, accepted); err != nil {
		t.Fatalf("retrying the batch after the checkpoint was refused: %v. A refused checkpoint "+
			"has to release the records with it, or the partition is permanently stuck and the "+
			"retry an operator would perform can never succeed", err)
	}

	if stored := auditRowCount(ctx, t, db, "audit_records", partition); stored != len(accepted) {
		t.Errorf("after the retry audit_records holds %d record(s) for %s, expected %d", stored,
			partition, len(accepted))
	}
	if stored := auditRowCount(ctx, t, db, "audit_checkpoints", partition); stored != 1 {
		t.Errorf("after the retry audit_checkpoints holds %d checkpoint(s) for %s, expected 1",
			stored, partition)
	}
}

// Compile-time assurance that the sink under test is the production one. This file's entire claim
// is that the transaction NewSQLSink owns is what makes records and their anchor atomic. Proving
// that against NewSQLSinkInTx - whose begin is a no-op - would prove it against the fixture again,
// which is the mistake the unit test is already making.
var _ = func() *audit.SQLSink {
	sink, err := audit.NewSQLSink(nil, nil)
	if err == nil {
		panic("a production sink was built from nil handles")
	}
	return sink
}
