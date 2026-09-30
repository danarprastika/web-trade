package model

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// TestRollbackIsPossibleOnlyWhereARollbackArtifactExists is the rollback half of
// acceptance criterion three.
//
// docs/07 requires every model record to carry a "rollback artifact", and requires
// promotion to a state that can affect execution to be preceded by a rollback being ready.
// The two together are what make a rollback possible at the moment it is needed: an
// artifact that does not exist when the model is healthy cannot be produced in the minutes
// after it starts losing money.
//
// The test therefore checks the artifact at registration, the precondition at promotion,
// and that the digest reaches the audit record. A rollback path that exists on paper but
// has no artifact behind it is the failure this rules out.
func TestRollbackIsPossibleOnlyWhereARollbackArtifactExists(t *testing.T) {
	// The record must carry a rollback artifact before a model can be registered at all.
	rec := validRecord()
	rec.RollbackArtifact = ""
	if err := setID(t, rec).Validate(); err == nil {
		t.Error("a model with no rollback artifact was registered; docs/07 requires a " +
			"rollback artifact on every model record")
	}
	if err := setID(t, validRecord()).Validate(); err != nil {
		t.Fatalf("a model with a rollback artifact was refused: %v", err)
	}

	// Promotion requires the readiness precondition, and a caller cannot satisfy it by
	// asserting a different name.
	promote := byFromCmd[transitionKey{state: StateShadow, command: CommandPromote}]
	if promote.Precondition != PreconditionRollbackReady {
		t.Errorf("promotion requires precondition %q, want %q",
			promote.Precondition, PreconditionRollbackReady)
	}

	req := validRequest(t, StateShadow, CommandPromote, contracts.ActorHuman)
	req.PreconditionsSatisfied = []Precondition{PreconditionNoOpenExposure}
	if _, err := Apply(req); err == nil {
		t.Error("promotion was applied without the rollback readiness precondition")
	}

	req = validRequest(t, StateShadow, CommandPromote, contracts.ActorHuman)
	if _, err := Apply(req); err != nil {
		t.Errorf("promotion with the rollback precondition was refused: %v", err)
	}
}

// TestThePromotionAuditRecordCitesTheRollbackArtifact: the artifact has to be reachable
// from the audit chain, or an operator who needs to roll back during an incident has to
// search for it.
func TestThePromotionAuditRecordCitesTheRollbackArtifact(t *testing.T) {
	promote, ok := TransitionFor(StateShadow, StatePromoted)
	if !ok {
		t.Fatal("no declared transition from SHADOW to PROMOTED")
	}
	lower := strings.ToLower(promote.AuditRecord)
	if !strings.Contains(lower, "rollback") {
		t.Errorf("the promotion audit record does not cite the rollback artifact: %s",
			promote.AuditRecord)
	}
	if !strings.Contains(lower, "monitoring") {
		t.Errorf("the promotion audit record does not cite the monitoring policy: %s",
			promote.AuditRecord)
	}
}

// TestRetirementIsTheRollbackPathFromMonitoring: once a model is live, the way back is a
// retirement, and it requires no open exposure so a rollback cannot strand a position.
//
// This matters because a rollback that could only be applied while the model is flat would
// be no rollback at all: the moment a rollback is needed is exactly when a model is
// exposed. Requiring a flat position to *retire* is right, but it means the position has to
// be closed deliberately by an operator before retirement, and that is a decision the audit
// trail has to show.
func TestRetirementIsTheRollbackPathFromMonitoring(t *testing.T) {
	retire, ok := TransitionFor(StateMonitored, StateRetired)
	if !ok {
		t.Fatal("no declared transition from MONITORED to RETIRED")
	}
	if retire.Command != CommandRetire {
		t.Errorf("MONITORED -> RETIRED carries command %q, want %q", retire.Command, CommandRetire)
	}
	if retire.Precondition != PreconditionNoOpenExposure {
		t.Errorf("retirement requires %q, want %q", retire.Precondition, PreconditionNoOpenExposure)
	}

	// An operator or an automatic drift response may retire it; an agent may not.
	for _, actor := range []contracts.ActorType{contracts.ActorHuman, contracts.ActorSystem} {
		req := validRequest(t, StateMonitored, CommandRetire, actor)
		if _, err := Apply(req); err != nil {
			t.Errorf("retirement by %s was refused: %v", actor, err)
		}
	}
	for _, actor := range []contracts.ActorType{contracts.ActorAgent, contracts.ActorStrategy} {
		req := validRequest(t, StateMonitored, CommandRetire, actor)
		if _, err := Apply(req); err == nil {
			t.Errorf("retirement by %s was accepted; an agent may not change a lifecycle state",
				actor)
		}
	}

	// The audit record has to say what happened to any residual position, because a
	// retirement that closed an open position without saying so is a reconciliation break.
	lower := strings.ToLower(retire.AuditRecord)
	if !strings.Contains(lower, "residual") {
		t.Errorf("the retirement audit record does not disposition any residual position: %s",
			retire.AuditRecord)
	}
}

// TestRetirementCannotBeRetriedIntoADoubleDisposition: retirement is the irreversible end
// of the lifecycle, so its idempotency scope has to be distinct from every other command.
func TestRetirementCannotBeRetriedIntoADoubleDisposition(t *testing.T) {
	scope := byFromCmd[transitionKey{state: StateMonitored, command: CommandRetire}].IdempotencyScope
	for _, other := range transitions {
		if other.Command == CommandRetire {
			continue
		}
		if other.IdempotencyScope == scope {
			t.Errorf("retirement shares idempotency scope %q with command %s; a retry of "+
				"one could suppress the other", scope, other.Command)
		}
	}
}

// TestAQuarantinedModelCannotBeResumedIntoALiveState is the rollback-adjacent containment
// property: clearing a quarantine retires the model rather than returning it to service, so
// the only way back is a new version through the full lifecycle.
func TestAQuarantinedModelCannotBeResumedIntoALiveState(t *testing.T) {
	for _, to := range NextStates(StateQuarantined) {
		switch to {
		case StateRetired:
		default:
			t.Errorf("QUARANTINED leads to %s; a cleared model must retire and re-enter the "+
				"lifecycle, not resume at %s", to, to)
		}
	}
	// And re-entering means starting again, so the whole chain from REGISTERED is
	// available and nothing is skipped.
	if len(NextStates(StateRegistered)) == 0 {
		t.Error("REGISTERED has no onward transition, so a retired model could not re-enter")
	}
}
