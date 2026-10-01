package model

import (
	"context"
	"strconv"
	"testing"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// The ledger read moved from one query per model to one query for the whole ledger, because
// rehydration restores every model and the per-model form made startup cost 1 + N strictly
// sequential round trips. These tests exist because the cost is invisible in the return value: a
// reader that went back to querying per model would return exactly the same Snapshot, and only a
// call count would notice.

// modelIDN ends its body with a single letter, so it can only mint ids for the letters Crockford
// Base32 admits. i, l, o and u are excluded from the alphabet, so the naive indices 0..N are not
// all valid; this maps a dense index onto one that is, and is why the count test below asks for
// twenty models rather than twenty-five.
var crockfordIndices = []int{0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 12, 13, 15, 16, 17, 18, 19, 21, 22, 23}

func validN(i int) int { return crockfordIndices[i] }

func registryRowForTest(t *testing.T, i int) dbgen.ModelRegistry {
	t.Helper()
	epoch := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	return dbgen.ModelRegistry{
		ModelID:                    modelIDN(t, validN(i)).String(),
		Version:                    "1.0.0",
		Owner:                      "owner-1",
		Author:                     "pipeline-1",
		TrainingDatasetFingerprint: "sha256:abc",
		CodeRevision:               "deadbeef",
		FeatureSpecification:       "spec-1",
		EvaluationResults:          "sha256:def",
		Limitations:                "none known",
		ApprovalRecord:             "sha256:aaa",
		DeploymentScope:            "SIMULATION",
		MonitoringPolicy:           "policy-1",
		RollbackArtifact:           "sha256:bbb",
		State:                      string(StateRegistered),
		RegisteredAtUtc:            epoch,
		LastAuditID:                "aud-1",
		UpdatedBy:                  "auditor-1",
		UpdatedAtUtc:               epoch,
	}
}

func ledgerRowForTest(t *testing.T, i, entry int) dbgen.ModelTransitionIdempotency {
	t.Helper()
	epoch := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	return dbgen.ModelTransitionIdempotency{
		IdempotencyScope:   "model.evaluation.recorded",
		IdempotencyKey:     "op-key-" + strconv.Itoa(entry),
		RequestFingerprint: "fp-" + strconv.Itoa(entry),
		ModelID:            modelIDN(t, validN(i)).String(),
		FromState:          string(StateRegistered),
		ToState:            string(StateEvaluated),
		AuditID:            "aud-" + strconv.Itoa(entry),
		AppliedAtUtc:       epoch.Add(time.Duration(entry) * time.Second),
	}
}

// The call count is the whole point: the same count for one model and for many is what proves
// the per-model query is gone. A count of 1 would mean the registry was not read.
func TestLoadSnapshotReadsTheRegistryInTwoQueriesHoweverManyModelsThereAre(t *testing.T) {
	modelCount := len(crockfordIndices)
	rows := make([]dbgen.ModelRegistry, 0, modelCount)
	ledger := map[string][]dbgen.ModelTransitionIdempotency{}
	entry := 0
	for i := 0; i < modelCount; i++ {
		row := registryRowForTest(t, i)
		rows = append(rows, row)
		// Every model gets a different number of transitions, so a reader that read only some
		// of them - or that read them in the wrong proportion - cannot pass.
		perModel := 1 + i%3
		for n := 0; n < perModel; n++ {
			ledger[row.ModelID] = append(ledger[row.ModelID], ledgerRowForTest(t, i, entry))
			entry++
		}
	}

	q := &fakeSnapshotQuerier{models: rows, ledger: ledger}
	reader, err := NewSQLSnapshotReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSnapshotReaderInTx: %v", err)
	}

	snap, err := reader.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}

	if q.calls != 2 {
		t.Errorf("LoadSnapshot made %d queries, expected exactly 2 (every model, then the whole "+
			"ledger). A count that grows with the registry means the per-model read is back, "+
			"which is the cost this change exists to remove.", q.calls)
	}
	if len(snap.Models) != modelCount {
		t.Errorf("snapshot holds %d models, expected %d", len(snap.Models), modelCount)
	}
	if len(snap.Idempotency) != entry {
		t.Errorf("snapshot holds %d idempotency entries, expected %d; a bulk read that dropped "+
			"rows would lose spent keys and let a retry apply a transition twice",
			len(snap.Idempotency), entry)
	}
}

// The bulk read must agree with the per-model read it replaced, field for field, not merely in
// count. A ledger row is attributed to the model named on the row, so a reader that grouped by
// the wrong key would produce a snapshot of the right size and the wrong contents.
func TestLoadSnapshotAttributesEachLedgerRowToTheModelItNames(t *testing.T) {
	q := &fakeSnapshotQuerier{
		models: []dbgen.ModelRegistry{registryRowForTest(t, 0), registryRowForTest(t, 1)},
		ledger: map[string][]dbgen.ModelTransitionIdempotency{
			modelIDN(t, 0).String(): {ledgerRowForTest(t, 0, 0), ledgerRowForTest(t, 0, 1)},
			modelIDN(t, 1).String(): {ledgerRowForTest(t, 1, 2)},
		},
	}
	reader, err := NewSQLSnapshotReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSnapshotReaderInTx: %v", err)
	}
	snap, err := reader.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}

	perModel := map[string]int{}
	for _, entry := range snap.Idempotency {
		perModel[entry.ModelID.String()]++
	}
	if perModel[modelIDN(t, 0).String()] != 2 {
		t.Errorf("model 0 has %d ledger entries, expected 2", perModel[modelIDN(t, 0).String()])
	}
	if perModel[modelIDN(t, 1).String()] != 1 {
		t.Errorf("model 1 has %d ledger entries, expected 1", perModel[modelIDN(t, 1).String()])
	}

	// Fields must survive the grouping, not just the row.
	want := ledgerRowForTest(t, 1, 2)
	var found bool
	for _, entry := range snap.Idempotency {
		if entry.ModelID != modelIDN(t, 1) {
			continue
		}
		found = true
		if entry.Key != want.IdempotencyKey {
			t.Errorf("key is %q, expected %q", entry.Key, want.IdempotencyKey)
		}
		if entry.Fingerprint != Digest(want.RequestFingerprint) {
			t.Errorf("fingerprint is %q, expected %q", entry.Fingerprint, Digest(want.RequestFingerprint))
		}
		if entry.From != State(want.FromState) || entry.To != State(want.ToState) {
			t.Errorf("transition is %s->%s, expected %s->%s",
				entry.From, entry.To, want.FromState, want.ToState)
		}
		if entry.AuditID != want.AuditID {
			t.Errorf("audit id is %q, expected %q", entry.AuditID, want.AuditID)
		}
		if !entry.At.Equal(want.AppliedAtUtc.UTC()) {
			t.Errorf("applied at is %s, expected %s", entry.At, want.AppliedAtUtc.UTC())
		}
	}
	if !found {
		t.Fatalf("no ledger entry was attributed to model 1")
	}
}

// A ledger row naming a model the registry does not contain is dropped, which is what the
// per-model query did by construction: it could only ask about a model it had already read.
//
// This is pinned because the bulk read makes the situation *visible* where it used to be
// invisible, and a future reader will reasonably want to hand such a row to Restore, which
// refuses a snapshot naming an unknown model. That is a better outcome than a key that is
// silently not reconstructed as spent - but it is a change in what a snapshot means, and it
// belongs to whoever decides that, not to a change about how many queries to make.
func TestLoadSnapshotDropsALedgerRowForAModelTheRegistryDoesNotContain(t *testing.T) {
	q := &fakeSnapshotQuerier{
		models: []dbgen.ModelRegistry{registryRowForTest(t, 0)},
		ledger: map[string][]dbgen.ModelTransitionIdempotency{
			modelIDN(t, 0).String(): {ledgerRowForTest(t, 0, 0)},
			modelIDN(t, 7).String(): {ledgerRowForTest(t, 7, 1)},
		},
	}
	reader, err := NewSQLSnapshotReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSnapshotReaderInTx: %v", err)
	}
	snap, err := reader.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	for _, entry := range snap.Idempotency {
		if entry.ModelID == modelIDN(t, 7) {
			t.Fatalf("snapshot carries a ledger entry for unregistered model %s; that row is "+
				"dropped, not reported, and Restore therefore cannot refuse the inconsistency",
				entry.ModelID)
		}
	}
	if len(snap.Idempotency) != 1 {
		t.Errorf("snapshot holds %d entries, expected only the registered model's 1", len(snap.Idempotency))
	}
}

// A failed read must be reported, not absorbed. The per-model form named the model it was
// reading; the bulk form cannot, so the message names the read instead.
func TestLoadSnapshotReportsAFailedLedgerRead(t *testing.T) {
	wantErr := context.DeadlineExceeded
	q := &fakeSnapshotQuerier{models: []dbgen.ModelRegistry{registryRowForTest(t, 0)}, err: wantErr}
	reader, err := NewSQLSnapshotReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSnapshotReaderInTx: %v", err)
	}
	if _, err := reader.LoadSnapshot(context.Background()); err == nil {
		t.Fatal("LoadSnapshot succeeded although the registry read failed")
	}
}
