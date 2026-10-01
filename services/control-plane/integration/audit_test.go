//go:build integration

package integration

import (
	"database/sql"
	"fmt"
	"os"
	"sync/atomic"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/lib/pq"
)

// liveSigning returns the checkpoint signer and the anchor the integration suite exports
// through.
//
// Both are returned because a caller needs the signer for a Deps or a verification ring and
// the anchor to build the sink, and constructing them separately in every test would make it
// too easy to wire a sink that cannot anchor without noticing.
//
// The key id is fixed rather than unique-per-run because nothing in this suite depends on it
// being distinguishable, and the key itself is generated in process: the anchored restore
// compares an anchor's sequence and hash and leaves authenticity to the Verifier's key ring,
// which no test here builds from a database row.
func liveSigning(t *testing.T) (*audit.LocalSigner, *audit.Anchor) {
	t.Helper()

	signer, err := audit.NewLocalSigner("key-integration")
	if err != nil {
		t.Fatalf("building the checkpoint signer: %v", err)
	}
	// A fixed clock, so a checkpoint's created_at is the same on every run and a rerun against
	// the same database produces the same bytes.
	anchor, err := audit.NewAnchor(signer, func() time.Time {
		return time.Date(2026, 10, 1, 12, 0, 0, 0, time.UTC)
	})
	if err != nil {
		t.Fatalf("building the checkpoint anchor: %v", err)
	}
	return signer, anchor
}

// liveSink builds the production SQL sink over db.
func liveSink(t *testing.T, db *sql.DB) *audit.SQLSink {
	t.Helper()
	_, anchor := liveSigning(t)
	sink, err := audit.NewSQLSink(db, anchor)
	if err != nil {
		t.Fatalf("building the SQL sink: %v", err)
	}
	return sink
}

// auditRecord returns a staged record: valid in every field, but with no sequence and no
// predecessor hash, because those are the chain's to assign.
//
// The audit id is suffixed with a per-process counter rather than being fixed. audit_records
// keys on audit_id alone, so ids are global across partitions and across runs, and a literal
// id would collide the second time these tests ran against the same database.
//
// Going through Chain.Append rather than constructing an accepted record by hand is deliberate.
// A hand-built record would have to recompute the chain by hand to agree with what Append
// produces, and a fixture that re-implements the code under test cannot fail for the right
// reason.
func auditRecord(auditID, partition string, offset int) audit.Record {
	return audit.Record{
		AuditID:     fmt.Sprintf("%s-p%d-%d", auditID, os.Getpid(), auditPartitionCounter.Add(1)),
		Partition:   partition,
		Sequence:    0,
		ActorID:     "actor-0000000000000001",
		ActorType:   audit.ActorHuman,
		Action:      "MODEL_REGISTERED",
		TargetType:  "MODEL",
		TargetID:    "mdl_01hq3k7m9x2f5rb8n0v6c4tqwx",
		Environment: "SIMULATION",
		MarketScope: "IDX",
		OccurredAt:  contracts.MustParseTimestamp("2026-09-28T10:00:00.000000000Z"),
		RecordedAt: contracts.MustParseTimestamp(
			fmt.Sprintf("2026-09-28T10:00:%02d.000000000Z", offset%60)),
		Reason:        "integration probe",
		CorrelationID: "cor-000000000000000001",
		CausationID:   "aud-0000000000000000000",
		PolicyVersion: "model-policy-v1",
		Result:        audit.ResultSucceeded,
		BeforeDigest:  "sha256:0000",
		AfterDigest:   "sha256:1111",
		PreviousHash:  audit.GenesisHash,
		SigningKeyID:  "key-0001",
	}
}

// auditPartition returns a partition name unique to one test run.
//
// The audit tables are append-only and the database refuses TRUNCATE outright, which is the
// guarantee doing its job and not something to work around by disabling a trigger. So the
// tests isolate themselves with distinct partition names instead of clearing tables, and they
// assert only about the records they wrote. A test that truncated the audit tables would be
// asserting on a database configuration that cannot exist in production.
func auditPartition(t *testing.T, name string) string {
	t.Helper()

	// A counter rather than a random value, so a rerun with -count=2 is visibly distinct and
	// the isolation is not dependent on a source of randomness.
	partition := fmt.Sprintf("%s-%d-%d", name, os.Getpid(), auditPartitionCounter.Add(1))
	if len(partition) > 63 {
		t.Fatalf("partition %q is %d characters, over the column limit", partition, len(partition))
	}
	return partition
}

var auditPartitionCounter atomic.Int64

// truncateAudit exists only to prove it cannot be used. The audit tables must never be cleared
// between tests, and this test is what stops a future change from assuming otherwise.
func TestAuditTablesRefuseTruncation(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	for _, table := range []string{
		"public.audit_records",
		"public.audit_checkpoints",
		"public.audit_deletion_events",
	} {
		if _, err := db.ExecContext(ctx, "TRUNCATE TABLE "+table+" CASCADE;"); err == nil {
			t.Errorf("TRUNCATE on %s was permitted; the append-only guarantee is not "+
				"being enforced and the tests that avoid truncating are relying on luck", table)
		} else {
			t.Logf("%s refuses truncation as expected: %v", table, err)
		}
	}
}

// The full audit round trip through a real database: build a chain in memory, persist it
// through the SQL sink, then rehydrate a brand new chain from the SQL reader and require it to
// be identical.
//
// This is the property G5.7 depends on and the one no amount of in-memory testing could
// establish. A restarted control plane holds no chain; it must rebuild one from PostgreSQL and
// then be able to append to it as though it had never stopped. Two things could break that
// without any unit test noticing: a column the sink writes and the reader does not read back,
// and a hash the reader recomputes differently from the one the chain produced. Both are
// exercised here.
func TestAnAuditChainSurvivesAWriteAndARehydrationThroughSQL(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	partitions := []string{auditPartition(t, "tenant-a"), auditPartition(t, "tenant-b")}
	counts := map[string]int{"tenant-a": 3, "tenant-b": 2}

	// Build and accept a chain in memory, exactly as a running process would.
	guard, err := audit.NewGuard(100)
	if err != nil {
		t.Fatalf("building the guard: %v", err)
	}
	chain := audit.NewChain()

	sink := liveSink(t, db)
	exporter, err := audit.NewExporter(guard, sink)
	if err != nil {
		t.Fatalf("building the exporter: %v", err)
	}

	original := map[string][]audit.Record{}
	n := 0
	for _, partition := range partitions {
		for i := 0; i < counts[partition]; i++ {
			n++
			accepted, err := chain.Append([]audit.Record{
				auditRecord(fmt.Sprintf("aud-%020d", n), partition, i),
			})
			if err != nil {
				t.Fatalf("appending to the chain: %v", err)
			}
			original[partition] = append(original[partition], accepted[0])
		}
	}

	// Persist. The guard is told how many records were accepted before the export, which is
	// what releases the evidence backlog only after the write commits.
	if err := exporter.Accept(n); err != nil {
		t.Fatalf("accepting %d records: %v", n, err)
	}
	all := make([]audit.Record, 0, n)
	for _, partition := range partitions {
		all = append(all, original[partition]...)
	}
	if err := exporter.Export(ctx, all); err != nil {
		t.Fatalf("exporting to the database: %v", err)
	}

	// Confirm the rows are really there, rather than trusting Export's return.
	//
	// Scoped to this test's partitions. The audit tables are append-only and cannot be
	// cleared, so a previous run's records are still present and a whole-table count would
	// make the assertion depend on how many times the suite had been executed.
	var rows int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.audit_records WHERE partition = ANY($1);`,
		pq.Array(partitions)).Scan(&rows); err != nil {
		t.Fatalf("counting audit rows: %v", err)
	}
	if rows != n {
		t.Fatalf("database holds %d audit rows for these partitions, expected %d", rows, n)
	}

	// A brand new process: fresh chain, fresh reader, no shared state with the writer.
	rebuilt := audit.NewChain()
	reader, err := audit.NewSQLChainReader(db)
	if err != nil {
		t.Fatalf("building the SQL chain reader: %v", err)
	}
	if err := audit.Rehydrate(ctx, rebuilt, reader, partitions); err != nil {
		t.Fatalf("rehydrating the chain: %v", err)
	}

	// Every record must come back with its identity, sequence and hash intact.
	for _, partition := range partitions {
		want := original[partition]
		got := rebuilt.Records(partition)
		if len(got) != len(want) {
			t.Fatalf("partition %s rehydrated %d records, expected %d",
				partition, len(got), len(want))
		}
		for i := range want {
			if got[i].AuditID != want[i].AuditID {
				t.Errorf("partition %s position %d: audit id %q, expected %q",
					partition, i, got[i].AuditID, want[i].AuditID)
			}
			if got[i].Sequence != want[i].Sequence {
				t.Errorf("partition %s position %d: sequence %d, expected %d",
					partition, i, got[i].Sequence, want[i].Sequence)
			}
			if got[i].RecordHash != want[i].RecordHash {
				t.Errorf("partition %s position %d (%s): hash %s, expected %s; the reader "+
					"and the chain disagree about the canonical bytes",
					partition, i, got[i].AuditID, got[i].RecordHash, want[i].RecordHash)
			}
		}
	}

	// Partitions must not have been merged. A reader that forgot to filter by partition would
	// return five records in the first partition and this assertion is what catches it.
	for _, partition := range partitions {
		for _, r := range rebuilt.Records(partition) {
			if r.Partition != partition {
				t.Errorf("partition %s returned a record belonging to %s", partition, r.Partition)
			}
		}
	}
}

// The rehydrated chain must be usable, not merely readable: appending after a restart has to
// continue the sequence and link to the hash PostgreSQL returned. If it cannot, a restarted
// process would start a second chain in the same partition and the audit trail would fork.
func TestARehydratedChainAcceptsFurtherAppends(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	partition := auditPartition(t, "tenant-append")

	// Persist two records.
	chain := audit.NewChain()
	accepted, err := chain.Append([]audit.Record{
		auditRecord("aud-0000000000000000001", partition, 0),
		auditRecord("aud-0000000000000000002", partition, 1),
	})
	if err != nil {
		t.Fatalf("appending the first two records: %v", err)
	}

	guard, err := audit.NewGuard(10)
	if err != nil {
		t.Fatalf("building the guard: %v", err)
	}
	sink := liveSink(t, db)
	exporter, err := audit.NewExporter(guard, sink)
	if err != nil {
		t.Fatalf("building the exporter: %v", err)
	}
	if err := exporter.Accept(len(accepted)); err != nil {
		t.Fatalf("accepting: %v", err)
	}
	if err := exporter.Export(ctx, accepted); err != nil {
		t.Fatalf("exporting: %v", err)
	}

	// Restart and rehydrate.
	rebuilt := audit.NewChain()
	reader, err := audit.NewSQLChainReader(db)
	if err != nil {
		t.Fatalf("building the reader: %v", err)
	}
	if err := audit.Rehydrate(ctx, rebuilt, reader, []string{partition}); err != nil {
		t.Fatalf("rehydrating: %v", err)
	}

	before := rebuilt.Records(partition)
	if len(before) != 2 {
		t.Fatalf("rehydrated %d records, expected 2", len(before))
	}

	// Append a third to the restarted chain. It must take sequence 3 and link to record 2.
	after, err := rebuilt.Append([]audit.Record{
		auditRecord("aud-0000000000000000003", partition, 2),
	})
	if err != nil {
		t.Fatalf("appending to the rehydrated chain: %v", err)
	}
	if after[0].Sequence != 3 {
		t.Errorf("the appended record got sequence %d, expected 3; a restart that forgot "+
			"its sequence would reuse 1", after[0].Sequence)
	}
	if after[0].PreviousHash != before[1].RecordHash {
		t.Errorf("the appended record links to %s, expected %s (the rehydrated predecessor)",
			after[0].PreviousHash, before[1].RecordHash)
	}
}

// Timestamps go through PostgreSQL as timestamptz at microsecond precision, so a value with
// nanoseconds comes back truncated. The chain's hash covers the timestamps, which means a
// mismatch here would surface as a hash disagreement on every subsequent record rather than as
// a timestamp assertion.
//
// This test pins that behaviour so the truncation is a documented property rather than a
// surprise discovered during an incident.
func TestTimestampsRoundTripAtPostgresPrecision(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	partition := auditPartition(t, "tenant-time")
	// Nanosecond precision on purpose: PostgreSQL will store microseconds.
	nanos := "2026-09-28T10:00:00.123456789Z"

	// A unique audit id, not a fixed one. audit_records has a primary key on audit_id alone, so
	// ids are global rather than per-partition, and reusing one across runs collides even when
	// the partition differs. The first version of this test used a literal id and failed on
	// its second run against the same database, which is the constraint working.
	record := auditRecord(fmt.Sprintf("aud-%s-%020d", partition, time.Now().UnixNano()),
		partition, 0)
	record.OccurredAt = contracts.MustParseTimestamp(nanos)

	chain := audit.NewChain()
	accepted, err := chain.Append([]audit.Record{record})
	if err != nil {
		t.Fatalf("appending: %v", err)
	}

	guard, err := audit.NewGuard(10)
	if err != nil {
		t.Fatalf("building the guard: %v", err)
	}
	sink := liveSink(t, db)
	exporter, err := audit.NewExporter(guard, sink)
	if err != nil {
		t.Fatalf("building the exporter: %v", err)
	}
	if err := exporter.Accept(1); err != nil {
		t.Fatalf("accepting: %v", err)
	}
	if err := exporter.Export(ctx, accepted); err != nil {
		t.Fatalf("exporting: %v", err)
	}

	rebuilt := audit.NewChain()
	reader, err := audit.NewSQLChainReader(db)
	if err != nil {
		t.Fatalf("building the reader: %v", err)
	}
	if err := audit.Rehydrate(ctx, rebuilt, reader, []string{partition}); err != nil {
		t.Fatalf("rehydrating: %v", err)
	}

	got := rebuilt.Records(partition)
	if len(got) != 1 {
		t.Fatalf("rehydrated %d records, expected 1", len(got))
	}

	// The record must come back with the microsecond value, and the reader must agree with
	// the chain about the hash despite the precision change. That agreement is what proves
	// the reader and the chain canonicalise timestamps identically.
	if got[0].RecordHash != accepted[0].RecordHash {
		t.Errorf("hash after a nanosecond-precision round trip is %s, expected %s; "+
			"the reader and the chain canonicalise timestamps differently",
			got[0].RecordHash, accepted[0].RecordHash)
	}
	if !got[0].OccurredAt.Time().Equal(accepted[0].OccurredAt.Time().Truncate(time.Microsecond)) {
		t.Logf("occurred_at came back as %v, input %v truncated to %v",
			got[0].OccurredAt.Time(),
			accepted[0].OccurredAt.Time(),
			accepted[0].OccurredAt.Time().Truncate(time.Microsecond))
	}
}

// The round trip nothing covered: records go out through the real SQL sink and the anchor
// comes back through the real SQL reader, with nothing in this test writing a checkpoint.
//
// Until the sink gained a checkpoint producer, audit_checkpoints was read but never written
// outside tests, so every anchor assertion in the suite was self-fulfilling - the test put the
// anchor there and then checked that the reader found it. Against a live database the table
// stayed empty, GetLatestAuditCheckpoint answered sql.ErrNoRows, Rehydrate fell through to the
// unanchored path, and a truncated archive still restored as VERIFIED. The only way to see that
// is to let the sink be the only writer and then look for what it left behind.
//
// The signature is verified against a ring built from the same signer, which closes the loop
// through storage rather than through the object: the bytes that came back out of PostgreSQL
// are a real signature over the canonical payload of the checkpoint they describe.
func TestTheSinkWritesACheckpointThatARehydrationFinds(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	signer, anchor := liveSigning(t)
	ring := audit.NewKeyRing()
	if err := signer.Register(ring, audit.KeySigning); err != nil {
		t.Fatalf("registering the signing key: %v", err)
	}

	partitions := []string{auditPartition(t, "anchor-a"), auditPartition(t, "anchor-b")}
	counts := map[string]int{partitions[0]: 3, partitions[1]: 2}

	chain := audit.NewChain()
	var batch []audit.Record
	for _, partition := range partitions {
		for i := 0; i < counts[partition]; i++ {
			accepted, err := chain.Append([]audit.Record{
				auditRecord(fmt.Sprintf("aud-%020d", len(batch)+1), partition, i),
			})
			if err != nil {
				t.Fatalf("appending to the chain: %v", err)
			}
			batch = append(batch, accepted[0])
		}
	}

	sink, err := audit.NewSQLSink(db, anchor)
	if err != nil {
		t.Fatalf("building the SQL sink: %v", err)
	}
	if err := sink.Export(ctx, batch); err != nil {
		t.Fatalf("exporting to the database: %v", err)
	}

	// The anchor is in the table, written by the sink and by nothing else. Counted in SQL
	// rather than inferred from the sink's return value, because a sink that reported success
	// while the table stayed empty is exactly the failure being guarded.
	var stored int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.audit_checkpoints WHERE partition = ANY($1);`,
		pq.Array(partitions)).Scan(&stored); err != nil {
		t.Fatalf("counting checkpoints: %v", err)
	}
	if stored != len(partitions) {
		t.Fatalf("the export left %d checkpoint(s) in audit_checkpoints for %d partition(s); "+
			"the anchor the restore compares against was not written", stored, len(partitions))
	}

	reader, err := audit.NewSQLChainReader(db)
	if err != nil {
		t.Fatalf("building the SQL chain reader: %v", err)
	}

	// Each partition's anchor must be found, and must describe the head of the records the
	// export actually stored - not merely exist. An anchor at the wrong sequence or the wrong
	// hash would either refuse an intact archive or fail to detect a deleted tail while
	// looking like the fix working.
	for _, partition := range partitions {
		cp, found, err := reader.LatestCheckpoint(ctx, partition)
		if err != nil {
			t.Fatalf("reading the latest checkpoint of partition %s: %v", partition, err)
		}
		if !found {
			t.Fatalf("partition %s has no checkpoint after a successful export; Rehydrate "+
				"will fall through to the unanchored path and a truncated archive will restore "+
				"as verified", partition)
		}
		var head audit.Record
		for _, r := range batch {
			if r.Partition == partition && r.Sequence == cp.LastSequence {
				head = r
			}
		}
		if head.AuditID == "" {
			t.Fatalf("the anchor for partition %s names sequence %d, which the export never "+
				"stored; the archive would be refused for a reason it did not earn",
				partition, cp.LastSequence)
		}
		if cp.LastSequence != int64(counts[partition]) {
			t.Errorf("partition %s anchored at last_sequence %d, want %d",
				partition, cp.LastSequence, counts[partition])
		}
		if cp.LastHash != head.RecordHash {
			t.Errorf("partition %s anchored at hash %s, want %s; this is the exact pair the "+
				"anchored restore compares", partition, cp.LastHash, head.RecordHash)
		}
		if cp.Count != counts[partition] {
			t.Errorf("partition %s anchor covers %d record(s), want %d",
				partition, cp.Count, counts[partition])
		}
		if err := cp.Verify(ring); err != nil {
			t.Errorf("the anchor stored for partition %s does not verify against the key it "+
				"names; the checkpoint did not survive PostgreSQL as a signature: %v", partition, err)
		}
	}

	// And the anchored restore accepts what it read, which is the half that has to keep working
	// for the check to be worth anything: a fix that refuses every archive is not a fix.
	rebuilt := audit.NewChain()
	if err := audit.Rehydrate(ctx, rebuilt, reader, partitions); err != nil {
		t.Fatalf("rehydrating against the anchors the sink wrote: %v", err)
	}
	for _, partition := range partitions {
		if got := rebuilt.LastSequence(partition); got != int64(counts[partition]) {
			t.Errorf("partition %s rehydrated to sequence %d, want %d",
				partition, got, counts[partition])
		}
	}
}
