package model

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"sort"
	"strings"
	"sync"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
)

// Journal is the model registry's only write path.
//
// It exists because the gate's first acceptance criterion is that identity, registry,
// decision ledger, tool permissions, and governance workflows "operate with complete audit
// trails", and none of the pieces that verify that criterion could satisfy it on their own.
// Apply is a pure decision function: it validates a proposed transition and returns what
// would happen, and it deliberately holds no state. That is the right design for a decision
// layer, and it is also why a caller could call Apply, be told a promotion is permitted, and
// then promote without writing anything to the audit chain. Outcome.AuditRecord existed and
// carried a descriptive string, not a record.
//
// So the guarantee moves from "callers write an audit record" to "there is no way to change
// a lifecycle state except through here, and here does not write the state until the audit
// chain has accepted the record describing it." A missing audit trail stops being something
// a caller might forget and becomes a state change that cannot happen.
//
// The chain and the clock are required constructor arguments rather than optional
// collaborators. A Journal buildable without a chain would be a registry whose audit trail
// is optional, which is the exact condition the gate excludes, and it would be a condition
// this constructor introduced rather than one inherited from the specification.
//
// Journal is safe for concurrent use. Apply is pure so sharing it is fine, but the registry
// state and the idempotency ledger beneath it are not, and the read-modify-write across
// chain.Append and the state commit is not atomic without this lock. WorkloadRegistry has
// the same gap and the same lock for the same reason.
type Journal struct {
	mu sync.Mutex

	chain       *audit.Chain
	clock       func() time.Time
	environment string

	// records holds each model's registered record. It is the source of the Owner, which is
	// the audit partition: records chained under one owner's scope cannot be used to reason
	// about another owner's, and a promotion cannot be reordered across that boundary.
	records map[contracts.Identifier]Record
	// states holds the current lifecycle state of each registered model.
	states map[contracts.Identifier]State
	// applied is the idempotency ledger, keyed by an idempotency scope plus the caller's
	// key. A retry of the same request returns the recorded outcome; the same scope and key
	// carrying a different request is a conflict rather than a retry.
	applied map[string]appliedTransition
	// auditIDs maps a model to the last audit record written for it, so a transition
	// records its causation instead of floating free in the chain.
	auditIDs map[contracts.Identifier]string

	// store is the durable destination for both writes. It is optional, and nil means
	// in-memory only, because a journal with no store is a legitimate thing to build for a
	// read-only or migration-time caller - but every writer gets one, so "no durable record"
	// is a property of the wiring rather than of whether somebody remembered a call.
	store Store
}

// appliedTransition is what an idempotency key resolved to the first time it was used.
type appliedTransition struct {
	// fingerprint digests the request that produced this outcome. A retry whose fingerprint
	// differs is a conflict: two different intents share one key, and resolving that by
	// preferring either copy would mean silently deciding which one actually happened.
	fingerprint Digest
	outcome     Outcome
}

// NewJournal builds a Journal over an audit chain, a clock, and a deployment environment.
//
// The environment is a property of the registry rather than of each call, because it is a
// fact about where the control plane is running and asking a caller to restate it per
// transition is an invitation to record a state change in the wrong environment. The audit
// package refuses a blank environment, so the value has to come from somewhere real.
func NewJournal(chain *audit.Chain, clock func() time.Time, environment string) (*Journal, error) {
	return NewJournalWithStore(chain, clock, environment, nil)
}

// NewJournalWithStore builds a Journal whose writes are recorded durably in store.
//
// A nil store is permitted and means in-memory only. That is not the same as refusing a
// nil store, and the difference is deliberate: a journal with no durable record is a
// legitimate configuration for a caller that only reads, and a constructor that refused
// would push that caller toward building a journal and then not using it. What is not
// permitted is a caller that believes it has a durable journal and does not, which is why
// Store reports which journal it is attached to rather than leaving it to be inferred.
func NewJournalWithStore(
	chain *audit.Chain,
	clock func() time.Time,
	environment string,
	store Store,
) (*Journal, error) {
	if chain == nil {
		return nil, reject(contracts.CodeInternal, ErrIncompleteRecord,
			"a model journal requires an audit chain; a registry whose audit trail is "+
				"optional cannot satisfy the gate it exists to satisfy")
	}
	if clock == nil {
		return nil, reject(contracts.CodeInternal, ErrIncompleteRecord,
			"a model journal requires a clock; occurred_at and recorded_at are load-bearing "+
				"audit fields and cannot be defaulted to the wall clock by omission")
	}
	if strings.TrimSpace(environment) == "" {
		return nil, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"a model journal requires a deployment environment; the audit chain refuses a "+
				"record that cannot be placed, and a placement nobody supplied is not one")
	}
	return &Journal{
		chain:       chain,
		clock:       clock,
		environment: environment,
		records:     make(map[contracts.Identifier]Record),
		states:      make(map[contracts.Identifier]State),
		applied:     make(map[string]appliedTransition),
		auditIDs:    make(map[contracts.Identifier]string),
		store:       store,
	}, nil
}

// Durable reports whether this journal writes through a store.
//
// It exists because the alternative is a nil check at every call site, and a caller asking
// "does this journal persist" should get an answer rather than have to read the field.
func (j *Journal) Durable() bool { return j.store != nil }

// Register records a model and places it in REGISTERED, audited.
//
// Registration is itself a governance event carrying an audit record, because a model that
// exists in the registry but never appeared in the audit chain could later be promoted out
// of a history that does not contain its own existence.
func (j *Journal) Register(rec Record, actorType contracts.ActorType, actorID string) (Outcome, error) {
	return j.RegisterContext(context.Background(), rec, actorType, actorID)
}

// RegisterContext records a model and places it in REGISTERED, audited, honouring ctx.
//
// Register exists as the background-context form so that the 19 existing callers and every
// reader of the audit guarantee keep working unchanged. A durable write is a network call,
// so a caller that has a context and lets this one be invented cannot cancel it.
func (j *Journal) RegisterContext(
	ctx context.Context,
	rec Record,
	actorType contracts.ActorType,
	actorID string,
) (Outcome, error) {
	if err := rec.Validate(); err != nil {
		return Outcome{}, err
	}
	j.mu.Lock()
	defer j.mu.Unlock()

	if _, exists := j.records[rec.ModelID]; exists {
		return Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,
			"model %s is already registered; re-registration would give one model two "+
				"lifecycles, and an in-place edit of a registered model is a new version "+
				"rather than a replacement", rec.ModelID)
	}
	t, ok := TransitionFor("", StateRegistered)
	if !ok {
		return Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
			"the lifecycle declares no transition into REGISTERED")
	}

	// A registration has no prior state, so its before-digest is empty. That is a fact
	// about the first event in a model's life rather than a missing value, and an empty
	// before-digest says exactly that.
	//
	// The durable write is InsertModel rather than ApplyTransition, because registration
	// creates the row rather than moving it, and the migration's identity-mutation guard
	// would refuse any second attempt to write one.
	// The audit identifier is passed into the closure rather than recomputed inside it.
	// Deriving it in two places would be one refactor away from the two copies disagreeing,
	// and a store row citing a different audit record than the registry row is precisely the
	// broken linkage the last_audit_id column exists to prevent.
	outcome, err := j.commit(rec, Outcome{
		ModelID:          rec.ModelID,
		Transition:       t,
		EventType:        t.EventType,
		IdempotencyScope: t.IdempotencyScope,
	}, "", actorType, identityOr(actorID), t.EventType, ctx,
		func(ctx context.Context, auditID string) error {
			now := j.clock()
			return j.store.InsertModel(ctx, RegistryEntry{
				Record:       rec,
				State:        StateRegistered,
				AuditID:      auditID,
				UpdatedBy:    identityOr(actorID),
				At:           now,
				RegisteredAt: now,
			})
		})
	if err != nil {
		return Outcome{}, err
	}
	j.records[rec.ModelID] = rec
	return outcome, nil
}

// Transact applies a lifecycle transition and records it.
//
// The ordering is the substance of this function:
//
//  1. Apply validates the request. It is pure, so a refusal here changed nothing.
//  2. The idempotency key is resolved, before the state check, so a retry of an
//     already-applied request returns its recorded outcome even though the world has moved
//     past its source state. Checking state first would make every retry of a completed
//     transition fail as stale, which is the standard way a retried promotion double-fires.
//  3. The current state is checked against the request's claimed source state, because the
//     transition table says which edges exist, not where this particular model is. A
//     journal that skipped this would happily promote a quarantined model by describing it
//     as REGISTERED.
//  4. The audit record is appended, and only on acceptance is the state written and the
//     idempotency key recorded.
//
// Steps 4's two halves are not split. If the chain refuses, the state is not written and the
// caller is told the transition did not happen. That is what makes "complete audit trails" a
// fact about the system rather than an instruction to its users.
func (j *Journal) Transact(req Request) (Outcome, error) {
	return j.TransactContext(context.Background(), req)
}

// TransactContext applies a lifecycle transition and records it, honouring ctx.
//
// See RegisterContext for why the background-context form exists alongside this one.
func (j *Journal) TransactContext(ctx context.Context, req Request) (Outcome, error) {
	outcome, err := Apply(req)
	if err != nil {
		return Outcome{}, err
	}
	from := outcome.Transition.From

	j.mu.Lock()
	defer j.mu.Unlock()

	scopeKey := idempotencyKey(outcome.IdempotencyScope, req.IdempotencyKey)
	fingerprint := requestFingerprint(req)
	if prior, seen := j.applied[scopeKey]; seen {
		if prior.fingerprint != fingerprint {
			return Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,
				"idempotency key %q was already used in scope %s for a different request; "+
					"two different intents share one key and neither may be silently preferred",
				req.IdempotencyKey, outcome.IdempotencyScope)
		}
		return prior.outcome, nil
	}

	rec, known := j.records[req.ModelID]
	if !known {
		return Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,
			"model %s is not registered; a lifecycle transition for an unregistered model "+
				"has no owner to chain under and no state to move", req.ModelID)
	}
	current, known := j.states[req.ModelID]
	if !known {
		return Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
			"model %s is registered but has no lifecycle state, which is an invariant "+
				"violation rather than a caller error", req.ModelID)
	}
	if current != from {
		return Outcome{}, reject(contracts.CodeConflict, ErrIncompleteRecord,
			"model %s is in %s, but the request claims it is in %s; the transition table "+
				"says which edges exist, not where this model is", req.ModelID, current, from)
	}

	committed, err := j.commit(rec, outcome, from, req.ActorType, identityOr(req.ActorID),
		outcome.EventType, ctx,
		func(ctx context.Context, auditID string) error {
			return j.store.ApplyTransition(ctx, TransitionEntry{
				Scope:       outcome.IdempotencyScope,
				Key:         req.IdempotencyKey,
				Fingerprint: fingerprint,
				ModelID:     req.ModelID,
				From:        from,
				To:          outcome.Transition.To,
				AuditID:     auditID,
				At:          j.clock(),
			})
		})
	if err != nil {
		return Outcome{}, err
	}
	j.applied[scopeKey] = appliedTransition{fingerprint: fingerprint, outcome: committed}
	return committed, nil
}

// commit appends the audit record and, only on its acceptance, writes the state change.
//
// Every mutation of Journal's state funnels through this one function, which is what makes
// "no state change without an audit record" checkable by reading a single function rather
// than by auditing every write site in the package.
//
// The ordering now spans three stores rather than one, and the order is the substance:
//
//  1. the audit record is appended to the chain;
//  2. the durable write goes to the store, advancing state and recording the transition
//     atomically;
//  3. the in-memory maps are updated.
//
// Step 2 failing leaves the in-memory state untouched, which is the property that matters:
// a caller told "not applied" must find the model exactly where it was. The audit record
// from step 1 is already in the chain, so the chain gains a record for a transition that
// did not take effect - and that is recorded honestly below rather than papered over,
// because a chain containing a SUCCEEDED record for a transition that failed is exactly the
// kind of thing an investigator would later have to unpick.
func (j *Journal) commit(
	rec Record,
	outcome Outcome,
	from State,
	actorType contracts.ActorType,
	actorID, action string,
	ctx context.Context,
	persist func(context.Context, string) error,
) (Outcome, error) {
	partition := rec.Owner
	now := j.clock()
	to := outcome.Transition.To
	auditID := auditIDFor(partition, rec.ModelID, action, to)

	// A retry of a transition whose durable write was refused reaches the same audit identity,
	// because that identity is derived from stable inputs rather than from the clock. The
	// timestamps are the one field that is not, and the chain hashes them - so a regenerated
	// record would differ from the one already stored and be refused as a conflicting reuse,
	// leaving the transition permanently unreachable after a single transient storage failure.
	occurredAt, recordedAt := j.stampsFor(auditID, now)

	record := audit.Record{
		AuditID:       auditID,
		Partition:     partition,
		Sequence:      j.chain.LastSequence(partition) + 1,
		ActorID:       actorID,
		ActorType:     actorType,
		Action:        action,
		TargetType:    "model",
		TargetID:      rec.ModelID.String(),
		Environment:   j.environment,
		OccurredAt:    occurredAt,
		RecordedAt:    recordedAt,
		Reason:        action,
		CorrelationID: rec.ModelID.String() + ":" + action,
		CausationID:   j.auditIDs[rec.ModelID],
		PolicyVersion: rec.Version,
		Result:        audit.ResultSucceeded,
		BeforeDigest:  stateDigest(rec.ModelID, from),
		AfterDigest:   stateDigest(rec.ModelID, to),
	}
	if prev, ok := j.chain.LastHash(partition); ok {
		record.PreviousHash = prev
	}
	// An approval transition carries the approver's approval digest into the after-digest,
	// so the audit record cites the approval rather than merely implying that one existed.
	if outcome.ApprovalRecord != "" {
		record.AfterDigest += ":" + string(outcome.ApprovalRecord)
	}

	// The refusal path. Nothing above this line has written anything: Apply is pure, the
	// idempotency ledger is written by the caller only after this returns, and the state
	// map is written only after this returns. So returning here leaves the registry
	// exactly as it was, which is the invariant this type exists to provide.
	if _, err := j.chain.Append([]audit.Record{record}); err != nil {
		return Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
			"the audit chain refused the record for this %s, so it was not applied: %v",
			action, err)
	}

	// The durable write. A failure here returns before any in-memory state is touched, so
	// the caller's retry finds the model where it was and the transition is genuinely
	// unapplied rather than applied-and-hidden.
	if j.store != nil && persist != nil {
		if err := persist(ctx, auditID); err != nil {
			// The chain already holds a SUCCEEDED record for this transition, and an
			// append-only chain cannot retract one. Leaving it uncorrected would export a
			// false success to durable storage, so the refusal is recorded beside it.
			if refusalErr := j.recordRefusal(record, err); refusalErr != nil {
				return Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
					"the durable store refused this %s and the refusal could not be recorded "+
						"in the audit chain, so the chain holds a SUCCEEDED record for a "+
						"transition that did not happen: store refusal %v, chain refusal %v",
					action, err, refusalErr)
			}
			return Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
				"the audit chain accepted the record for this %s but the durable store "+
					"refused it, so it was not applied and the model's state is unchanged: %v",
				action, err)
		}
	}

	// A refusal record is terminal - an append-only chain cannot retract it - so the retry that
	// finally lands leaves the contradiction standing: the last evidence for the transition
	// says it was not applied while the registry says it was. Nothing detects that, because
	// the row cites the accepted record and verifyAgainstChain is right to accept it. So the
	// success is recorded too, citing the refusal as its cause.
	if err := j.recordApplication(record); err != nil {
		return Outcome{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
			"the durable store accepted this %s and it IS applied, but the audit chain refused "+
				"to record that the earlier refusal was resolved, so the last evidence for "+
				"this transition still says it was not applied: %v", action, err)
	}

	j.states[rec.ModelID] = to
	j.auditIDs[rec.ModelID] = auditID
	outcome.AuditRecord = auditID
	return outcome, nil
}

// stampsFor returns the timestamps a record carrying auditID must use.
//
// The audit identity is derived from stable inputs, so a retry of a transition whose durable
// write was refused reaches the same identity again. The timestamps are the exception, and the
// chain hashes them. Reusing what was already recorded is therefore not a way of concealing a
// difference - one identity can never legitimately carry two different contents, and the chain
// still refuses that case - but the only way to hand the chain back the record it already
// holds rather than a conflict that would make the transition unreachable forever.
func (j *Journal) stampsFor(auditID string, now time.Time) (contracts.Timestamp, contracts.Timestamp) {
	if prior, seen := j.chain.RecordByAuditID(auditID); seen {
		return prior.OccurredAt, prior.RecordedAt
	}
	stamp := audit.TimestampFrom(now)
	return stamp, stamp
}

// recordRefusal appends the record that corrects a success the chain accepted but the durable
// store did not honour.
//
// It cites the original as its cause and inverts the digests, so the chain shows the state the
// model was actually left in rather than the state the refused transition would have reached.
// Without it the audit sink would durably export a SUCCEEDED record for a transition that never
// happened, and nothing in an append-only chain could say otherwise afterwards.
//
// The refusal carries a fixed reason rather than the store's error text. That error goes to the
// caller and to the logs, where it belongs; evidence that outlives the process should state
// what happened to the governance event without carrying database internals into it.
func (j *Journal) recordRefusal(original audit.Record, _ error) error {
	auditID := original.AuditID + ".refused"
	occurredAt, recordedAt := j.stampsFor(auditID, j.clock())

	refusal := audit.Record{
		AuditID:       auditID,
		Partition:     original.Partition,
		Sequence:      j.chain.LastSequence(original.Partition) + 1,
		ActorID:       original.ActorID,
		ActorType:     original.ActorType,
		Action:        original.Action,
		TargetType:    original.TargetType,
		TargetID:      original.TargetID,
		Environment:   original.Environment,
		OccurredAt:    occurredAt,
		RecordedAt:    recordedAt,
		Reason:        "the durable store refused the transition, so it was not applied",
		CorrelationID: original.CorrelationID,
		CausationID:   original.AuditID,
		PolicyVersion: original.PolicyVersion,
		Result:        audit.ResultRefused,
		BeforeDigest:  original.AfterDigest,
		AfterDigest:   original.BeforeDigest,
	}
	if prev, ok := j.chain.LastHash(original.Partition); ok {
		refusal.PreviousHash = prev
	}
	_, err := j.chain.Append([]audit.Record{refusal})
	return err
}

// recordApplication closes a refusal once the retry it was waiting for actually lands.
//
// It appends nothing on the ordinary path, which is the point: a transition the store accepted
// first time is one record, and adding a second would make the common case noisier than the
// rare one it exists to repair.
//
// When a refusal does exist, the digests invert again, so the chain shows the state the model
// reached rather than the one it was left in, and the record is caused by the refusal. Without
// that causation an investigator walking forward from the refusal never reaches the resolution,
// because nothing links them.
func (j *Journal) recordApplication(original audit.Record) error {
	refusal, refused := j.chain.RecordByAuditID(original.AuditID + ".refused")
	if !refused {
		return nil
	}
	auditID := refusal.AuditID + ".applied"
	occurredAt, recordedAt := j.stampsFor(auditID, j.clock())

	application := audit.Record{
		AuditID:       auditID,
		Partition:     refusal.Partition,
		Sequence:      j.chain.LastSequence(refusal.Partition) + 1,
		ActorID:       refusal.ActorID,
		ActorType:     refusal.ActorType,
		Action:        refusal.Action,
		TargetType:    refusal.TargetType,
		TargetID:      refusal.TargetID,
		Environment:   refusal.Environment,
		OccurredAt:    occurredAt,
		RecordedAt:    recordedAt,
		Reason:        "the durable store accepted the transition on retry, so it is applied",
		CorrelationID: refusal.CorrelationID,
		CausationID:   refusal.AuditID,
		PolicyVersion: refusal.PolicyVersion,
		Result:        audit.ResultSucceeded,
		BeforeDigest:  refusal.AfterDigest,
		AfterDigest:   refusal.BeforeDigest,
	}
	if prev, ok := j.chain.LastHash(refusal.Partition); ok {
		application.PreviousHash = prev
	}
	_, err := j.chain.Append([]audit.Record{application})
	return err
}

// State reports a model's current lifecycle state, and whether it is registered at all.
func (j *Journal) State(modelID contracts.Identifier) (State, bool) {
	j.mu.Lock()
	defer j.mu.Unlock()
	s, ok := j.states[modelID]
	return s, ok
}

// Record reports a model's registered record.
func (j *Journal) Record(modelID contracts.Identifier) (Record, bool) {
	j.mu.Lock()
	defer j.mu.Unlock()
	r, ok := j.records[modelID]
	return r, ok
}

// RegisteredModels lists the registered model identifiers in a stable order, so a caller
// listing the registry twice sees the same sequence and can diff the two listings.
func (j *Journal) RegisteredModels() []string {
	j.mu.Lock()
	defer j.mu.Unlock()
	out := make([]string, 0, len(j.records))
	for id := range j.records {
		out = append(out, id.String())
	}
	sort.Strings(out)
	return out
}

// AuditRecords returns the audit records written for one model, in chain order. It is the
// model's complete governance history as the registry itself recorded it.
func (j *Journal) AuditRecords(modelID contracts.Identifier) []audit.Record {
	var out []audit.Record
	for _, r := range j.chain.AllRecords() {
		if r.TargetID == modelID.String() {
			out = append(out, r)
		}
	}
	return out
}

// Chain exposes the audit chain, which is the same chain the journal wrote to, so a caller
// verifying the chain is verifying the registry's own history.
func (j *Journal) Chain() *audit.Chain { return j.chain }

// auditIDFor derives a stable audit identity for a governance event.
//
// It is derived rather than generated, and deliberately excludes the timestamp, so that a
// retry of the same request produces the same identity. That is what lets the chain's
// duplicate-delivery path recognise a retry as the same record rather than as a second,
// contradictory record describing one transition. Including the timestamp would have made
// every retry a new event, which is precisely the double-write the idempotency scope exists
// to prevent.
func auditIDFor(partition string, id contracts.Identifier, action string, to State) string {
	return string(digestOf("audit", partition, id.String(), action, string(to)))
}

// stateDigest is the digest of a lifecycle state for the before/after audit fields.
//
// docs/22 section 2 requires sensitive state to be referenced by digest rather than copied
// into the audit payload. A lifecycle state is a single non-sensitive token, so it is
// digested here for consistency with the rest of the platform's audit digests rather than
// because it needed hiding.
func stateDigest(id contracts.Identifier, s State) string {
	if s == "" {
		return ""
	}
	return string(digestOf("state", id.String(), string(s)))
}

// digestOf computes a bare lowercase hex SHA-256: the representation model.Digest accepts
// and the one the Python research worker emits. The control plane is authoritative for that
// wire format, and the two are pinned by separate tests that do not read each other.
func digestOf(parts ...string) Digest {
	h := sha256.New()
	for i, p := range parts {
		if i > 0 {
			h.Write([]byte{0x1f})
		}
		h.Write([]byte(p))
	}
	return Digest(hex.EncodeToString(h.Sum(nil)))
}

// idempotencyKey namespaces a caller's key by the transition's declared scope, so one key
// reused across two different transition types is two different keys rather than a conflict.
func idempotencyKey(scope, key string) string {
	return scope + "\x1f" + key
}

// requestFingerprint digests everything about a request that determines its outcome, so a
// reused idempotency key carrying a different intent is detected as a conflict.
func requestFingerprint(req Request) Digest {
	return digestOf(
		"request",
		req.ModelID.String(),
		string(req.From),
		string(req.Command),
		string(req.ActorType),
		req.ActorID,
		req.Reference,
		req.IdempotencyKey,
	)
}

// identityOr names the system when a caller supplies no actor id.
//
// A privileged transition with no actor is already refused by Apply, but a non-privileged
// one may legitimately be system-originated, and the audit package refuses a blank actor_id
// because an unattributable record is not evidence. Defaulting to "system" records the
// absence of a person honestly instead of leaving the field empty or inventing one.
func identityOr(actorID string) string {
	if strings.TrimSpace(actorID) == "" {
		return "system"
	}
	return actorID
}
