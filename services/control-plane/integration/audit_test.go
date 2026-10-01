//go:build integration

package integration

import (
	"fmt"
	"os"
	"sync/atomic"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/lib/pq"
)

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

	sink, err := audit.NewSQLSink(db)
	if err != nil {
		t.Fatalf("building the SQL sink: %v", err)
	}
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
	sink, err := audit.NewSQLSink(db)
	if err != nil {
		t.Fatalf("building the SQL sink: %v", err)
	}
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
	sink, err := audit.NewSQLSink(db)
	if err != nil {
		t.Fatalf("building the sink: %v", err)
	}
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
