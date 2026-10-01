package model

import (
	"context"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
)

// Restore rebuilds a journal's in-memory state from a durable snapshot.
//
// This is the restart path, and it is the last of the three read-side gaps the audit work
// exposed. The registry store was write-only, so a process that restarted had no memory of
// which models existed, what state they had reached, or which idempotency keys were spent.
// All three consequences are real and one of them is severe: without the ledger, a retried
// transition is not recognised as a retry, so a caller retrying after a restart gets a second
// execution of an operation that already committed.
//
// Restore refuses a snapshot the audit chain does not corroborate. That check is the point of
// having two durable stores rather than one: the registry says a model is in state X and names
// the audit record that established it, and the chain holds that record with its own
// after-digest. A snapshot whose state digest does not match the after-digest of the audit
// record it cites is a registry that has drifted from its evidence, and loading it would
// produce a journal that looks whole and attests to something that never happened.
//
// It is all-or-nothing, like every other apply in this package. A partial restore would leave
// some models present and others unknown, and "unknown" is indistinguishable from "never
// registered" to every caller downstream - which is the specific condition under which a
// retired model gets registered again.
func (j *Journal) Restore(snapshot Snapshot) error {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Stage first. Nothing below mutates the journal, so any refusal leaves it exactly as it
	// was rather than half-loaded.
	records := make(map[contracts.Identifier]Record, len(snapshot.Models))
	states := make(map[contracts.Identifier]State, len(snapshot.Models))
	auditIDs := make(map[contracts.Identifier]string, len(snapshot.Models))

	for _, model := range snapshot.Models {
		id := model.Record.ModelID
		if id.IsZero() {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"the snapshot contains a model with no identifier, so it cannot be placed in "+
					"a partition or verified against the chain")
		}
		if existing, seen := states[id]; seen {
			return reject(contracts.CodeConflict, ErrIncompleteRecord,
				"the snapshot contains model %s twice, in states %s and %s; the registry has "+
					"one row per model, so this is a reader that merged two sources",
				id, existing, model.State)
		}
		if err := j.verifyAgainstChain(model); err != nil {
			return err
		}
		records[id] = model.Record
		states[id] = model.State
		auditIDs[id] = model.AuditID
	}

	applied := make(map[string]appliedTransition, len(snapshot.Idempotency))
	for _, entry := range snapshot.Idempotency {
		key := idempotencyKey(entry.Scope, entry.Key)
		if existing, seen := applied[key]; seen {
			return reject(contracts.CodeConflict, ErrIncompleteRecord,
				"the snapshot records idempotency key %s/%s twice, resolving to transitions "+
					"on %s and %s; one key cannot have been spent twice",
				entry.Scope, entry.Key,
				existing.outcome.Transition.From, existing.outcome.Transition.To)
		}
		if _, ok := states[entry.ModelID]; !ok {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"the snapshot records a transition for model %s, which the snapshot does not "+
					"contain; a transition cannot be replayed for a model that is not registered",
				entry.ModelID)
		}
		trans, ok := TransitionFor(entry.From, entry.To)
		if !ok {
			return reject(contracts.CodeInternal, ErrIncompleteRecord,
				"the snapshot records a transition %s -> %s for model %s that is not declared in the lifecycle",
				entry.From, entry.To, entry.ModelID)
		}
		applied[key] = appliedTransition{
			fingerprint: entry.Fingerprint,
			outcome: Outcome{
				ModelID:          entry.ModelID,
				Transition:       trans,
				EventType:        trans.EventType,
				AuditRecord:      entry.AuditID,
				IdempotencyScope: trans.IdempotencyScope,
				FailureBehavior:  trans.FailureBehavior,
			},
		}
	}

	j.records = records
	j.states = states
	j.auditIDs = auditIDs
	j.applied = applied
	return nil
}

// verifyAgainstChain checks that the chain corroborates what the registry claims.
//
// The chain is the authority, not the registry: it is append-only, independently verifiable,
// and the only one of the two whose integrity anyone outside this process can check. So the
// registry's state is accepted only when a record it cites exists in the chain and that
// record's after-digest is the digest of this state.
//
// The after-digest may carry an ":approval" suffix, because commit appends the approver's
// approval digest to it so a record cites its approval rather than implying one. Comparing
// the whole field would therefore refuse every approval transition; comparing only the prefix
// would accept a state whose digest matches while the approval is missing, which is the part
// worth checking.
func (j *Journal) verifyAgainstChain(model ModelSnapshot) error {
	if j.chain == nil {
		return reject(contracts.CodeInternal, ErrIncompleteRecord,
			"a restore needs an audit chain to verify the registry against, and this journal "+
				"has none")
	}
	if strings.TrimSpace(model.AuditID) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"model %s carries no audit record; the registry requires one, so a row without it "+
				"means the model exists in the registry but not in the evidence", model.Record.ModelID)
	}
	record, ok := j.chain.RecordByAuditID(model.AuditID)
	if !ok {
		return reject(contracts.CodeConflict, ErrIncompleteRecord,
			"model %s claims audit record %s, which is not in the chain; the registry has "+
				"drifted from the evidence and cannot be restored",
			model.Record.ModelID, model.AuditID)
	}
	want := stateDigest(model.Record.ModelID, model.State)
	got, _, _ := strings.Cut(record.AfterDigest, ":")
	if got != want {
		return reject(contracts.CodeConflict, ErrIncompleteRecord,
			"model %s is recorded in state %s, whose digest is %s, but the audit record it "+
				"cites records after-digest %s; restoring this would make the registry assert a "+
				"state its own evidence does not support",
			model.Record.ModelID, model.State, want, record.AfterDigest)
	}
	return nil
}

// RehydratedJournal builds a journal whose state is restored from durable storage.
//
// It takes both stores deliberately: the chain restores the evidence and the snapshot restores
// the registry, and neither can substitute for the other. The chain cannot supply a model's
// declaration or its current state, because stateDigest is one-way; the snapshot cannot supply
// the audit records a transition must cite as its causation.
//
// The chain must already be restored - by audit.Rehydrate - before this is called. A journal
// restored against an empty chain would fail every model's corroboration check, which is
// correct but not informative, so the check below names the likely cause.
func RehydratedJournal(
	ctx context.Context,
	chain *audit.Chain,
	clock func() time.Time,
	environment string,
	store Store,
	reader SnapshotReader,
) (*Journal, error) {
	journal, err := NewJournalWithStore(chain, clock, environment, store)
	if err != nil {
		return nil, err
	}
	if reader == nil {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"rehydrating a journal needs a snapshot reader; without one the journal would be "+
				"empty, which is indistinguishable from a registry that has never been written")
	}
	snapshot, err := reader.LoadSnapshot(ctx)
	if err != nil {
		return nil, err
	}
	if err := journal.Restore(snapshot); err != nil {
		return nil, err
	}
	return journal, nil
}
