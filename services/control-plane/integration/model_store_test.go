//go:build integration

package integration

import (
	"context"
	"database/sql"
	"fmt"
	"testing"
	"time"

	"github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/model"
)

// truncate empties the durable tables so each test starts from a known state.
//
// Truncating rather than deleting: the tables carry foreign keys and triggers, and TRUNCATE
// ... CASCADE resets them in one statement. Restricted to the registry tables this package
// owns so a failure in one test cannot silently cascade into an unrelated table.
func truncate(t *testing.T, ctx context.Context, db *sql.DB) {
	t.Helper()

	for _, table := range []string{
		"public.workload_revocations",
		"public.workload_identities",
		"public.model_transition_idempotency",
		"public.model_registry",
	} {
		if _, err := db.ExecContext(ctx, "TRUNCATE TABLE "+table+" CASCADE;"); err != nil {
			t.Fatalf("truncating %s: %v", table, err)
		}
	}
}

// validEntry builds a RegistryEntry that satisfies the model's own invariants and the nine
// check constraints on public.model_registry.
//
// The digest columns are constrained to 64-character lowercase hex, the model_id must carry
// the mdl_ prefix and be at most 34 characters, and owner must differ from author. Writing
// this once here rather than per test keeps the constraint knowledge in a single place.
func validEntry(t *testing.T, modelID string, at time.Time) model.RegistryEntry {
	t.Helper()

	const digest = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

	identifier, err := contracts.ParseIdentifier(modelID)
	if err != nil {
		t.Fatalf("parsing the model identifier %q: %v", modelID, err)
	}

	return model.RegistryEntry{
		Record: model.Record{
			ModelID:                    identifier,
			Version:                    "v1",
			Owner:                      "owner-identity",
			Author:                     "author-identity",
			TrainingDatasetFingerprint: digest,
			CodeRevision:               "rev-abc123",
			FeatureSpecification:       "spec://features/v1",
			EvaluationResults:          digest,
			Limitations:                "does not handle out-of-distribution inputs",
			DeploymentScope:            "paper",
			MonitoringPolicy:           "policy://monitoring/v1",
			RollbackArtifact:           digest,
		},
		State:        model.StateRegistered,
		AuditID:      "",
		UpdatedBy:    "author-identity",
		At:           at,
		RegisteredAt: at,
	}
}

// The durable round trip: write through the real SQL store, then rebuild from a real snapshot
// read, as a restarted control plane would.
//
// Every other test of this path uses an in-memory fake, which means it proves the algorithm
// and not the SQL. This proves the SQL: that a row written by the Go store is readable by the
// Go reader, that the digests and timestamps survive the round trip, and that a model in a
// terminal state is still there afterwards.
func TestAModelWrittenThroughSQLComesBackThroughASnapshotRead(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	const modelID = "mdl_01hq3k7m9x2f5rb8n0v6c4tqwx"
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	// Write.
	store, err := model.NewSQLStore(db)
	if err != nil {
		t.Fatalf("building the SQL store: %v", err)
	}
	entry := validEntry(t, modelID, at)
	if err := store.InsertModel(ctx, entry); err != nil {
		t.Fatalf("inserting the model: %v", err)
	}

	// Read back through a fresh reader, as a restart would.
	reader, err := model.NewSQLSnapshotReader(db)
	if err != nil {
		t.Fatalf("building the snapshot reader: %v", err)
	}
	snapshot, err := reader.LoadSnapshot(ctx)
	if err != nil {
		t.Fatalf("loading the snapshot: %v", err)
	}

	if len(snapshot.Models) != 1 {
		t.Fatalf("snapshot holds %d models, expected 1", len(snapshot.Models))
	}
	got := snapshot.Models[0]

	if got.Record.ModelID.String() != modelID {
		t.Errorf("model_id is %q, expected %q", got.Record.ModelID.String(), modelID)
	}
	if got.State != model.StateRegistered {
		t.Errorf("state is %q, expected %q", got.State, model.StateRegistered)
	}
	if got.Record.Owner != entry.Record.Owner {
		t.Errorf("owner is %q, expected %q", got.Record.Owner, entry.Record.Owner)
	}
	if got.Record.TrainingDatasetFingerprint != entry.Record.TrainingDatasetFingerprint {
		t.Errorf("dataset fingerprint did not survive the round trip: %q",
			got.Record.TrainingDatasetFingerprint)
	}
	if got.Record.RollbackArtifact != entry.Record.RollbackArtifact {
		t.Errorf("rollback artifact did not survive the round trip: %q", got.Record.RollbackArtifact)
	}

	// The timestamp is the interesting one. PostgreSQL stores timestamptz at microsecond
	// precision, so a value with nanoseconds comes back truncated. A caller that compared
	// timestamps for equality would see a mismatch here, and this test documents the real
	// behaviour rather than the one the in-memory store exhibits.
	if got.RegisteredAt.IsZero() {
		t.Error("registered_at is zero after the round trip")
	}
	if !got.RegisteredAt.Equal(at.Truncate(time.Microsecond)) {
		t.Errorf("registered_at is %v, expected %v truncated to microseconds",
			got.RegisteredAt, at)
	}
	t.Logf("registered_at round-tripped as %v (input %v)", got.RegisteredAt, at)
}

// A terminal-state model must still be present after a restart.
//
// This is the specific reason LoadAllModels exists: a restore that cannot see a retired model
// would let it be registered again from scratch, which is the failure EV-049's rehydration
// exists to prevent. A query that filters to active states would pass every unit test built on
// a fake and would lose the row here.
func TestARetiredModelSurvivesTheRoundTrip(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	const modelID = "mdl_01hq3k7m9x2f5rb8n0v6c4tqwy"
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	store, err := model.NewSQLStore(db)
	if err != nil {
		t.Fatalf("building the SQL store: %v", err)
	}

	// Register first; the lifecycle walk below starts from REGISTERED.
	entry := validEntry(t, modelID, at)
	if err := store.InsertModel(ctx, entry); err != nil {
		t.Fatalf("inserting the model: %v", err)
	}

	// Walk the declared lifecycle to RETIRED rather than forcing the state.
	//
	// The database declares a single chain: REGISTERED -> EVALUATED -> VALIDATED -> APPROVED ->
	// PAPER -> SHADOW -> PROMOTED -> MONITORED -> RETIRED, with QUARANTINED reachable from any
	// non-terminal state. An earlier version of this test tried REGISTERED -> RETIRED and the
	// trigger refused it, which is the guard doing its job, so the test follows the real chain
	// instead. That makes it a stronger test: every hop is one the database accepts, so a
	// failure anywhere means a real defect rather than an illegal request.
	states := []model.State{
		model.StateEvaluated,
		model.StateValidated,
		model.StateApproved,
		model.StatePaper,
		model.StateShadow,
		model.StatePromoted,
		model.StateMonitored,
		model.StateRetired,
	}

	from := model.StateRegistered
	for i, to := range states {
		entry.AuditID = fmt.Sprintf("aud_probe_step_%02d", i)
		entry.UpdatedBy = "owner-identity"
		entry.At = at.Add(time.Duration(i+1) * time.Hour)

		if err := store.ApplyTransition(ctx, model.TransitionEntry{
			Scope:       "probe",
			Key:         fmt.Sprintf("probe-step-%02d", i),
			Fingerprint: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
			ModelID:     entry.Record.ModelID,
			From:        from,
			To:          to,
			AuditID:     entry.AuditID,
			At:          entry.At,
		}); err != nil {
			t.Fatalf("walking the lifecycle to %s (step %d): %v", to, i, err)
		}
		from = to
		entry.State = to
	}

	reader, err := model.NewSQLSnapshotReader(db)
	if err != nil {
		t.Fatalf("building the snapshot reader: %v", err)
	}
	snapshot, err := reader.LoadSnapshot(ctx)
	if err != nil {
		t.Fatalf("loading the snapshot: %v", err)
	}

	if len(snapshot.Models) != 1 {
		t.Fatalf("snapshot holds %d models, expected the retired one to be present",
			len(snapshot.Models))
	}
	if snapshot.Models[0].State != model.StateRetired {
		t.Errorf("state is %q, expected %q; a restore that cannot see a terminal state "+
			"would allow the model to be registered again",
			snapshot.Models[0].State, model.StateRetired)
	}
}

// The idempotency table must round-trip too, because a restart that forgets spent keys would
// replay a transition that already happened.
func TestSpentIdempotencyKeysSurviveTheRoundTrip(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	const modelID = "mdl_01hq3k7m9x2f5rb8n0v6c4tqwz"
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)
	const fingerprint = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

	store, err := model.NewSQLStore(db)
	if err != nil {
		t.Fatalf("building the SQL store: %v", err)
	}
	if err := store.InsertModel(ctx, validEntry(t, modelID, at)); err != nil {
		t.Fatalf("inserting the model: %v", err)
	}

	entry := model.TransitionEntry{
		Scope:       "registration",
		Key:         "probe-key-0001",
		Fingerprint: fingerprint,
		ModelID:     validEntry(t, modelID, at).Record.ModelID,
		From:        model.StateRegistered,
		To:          model.StateRegistered,
		AuditID:     "aud_probe_idempotency",
		At:          at,
	}
	if err := store.ApplyTransition(ctx, entry); err != nil {
		t.Fatalf("recording the transition: %v", err)
	}

	reader, err := model.NewSQLSnapshotReader(db)
	if err != nil {
		t.Fatalf("building the snapshot reader: %v", err)
	}
	snapshot, err := reader.LoadSnapshot(ctx)
	if err != nil {
		t.Fatalf("loading the snapshot: %v", err)
	}

	if len(snapshot.Idempotency) != 1 {
		t.Fatalf("snapshot holds %d idempotency entries, expected 1", len(snapshot.Idempotency))
	}
	got := snapshot.Idempotency[0]
	if got.Scope != entry.Scope || got.Key != entry.Key {
		t.Errorf("idempotency coordinates are (%q, %q), expected (%q, %q)",
			got.Scope, got.Key, entry.Scope, entry.Key)
	}
	if got.Fingerprint != fingerprint {
		t.Errorf("fingerprint is %q, expected %q; a restart that lost it could not "+
			"tell a retry from a conflicting reuse", got.Fingerprint, fingerprint)
	}
	if got.AuditID != entry.AuditID {
		t.Errorf("audit id is %q, expected %q", got.AuditID, entry.AuditID)
	}
}
