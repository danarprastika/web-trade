-- Queries against the model registry, the workload identities that may serve it, the
-- revocations that stop them, and the idempotency ledger.
--
-- Authority, and why these queries are shaped the way they are.
--
-- The Go package in services/control-plane/model decides; these queries only persist what it
-- decided. Nothing here is allowed to become a second decision path, and the shapes below are
-- chosen to make that structurally difficult rather than merely documented:
--
--   * There is no UPDATE that can move a model between arbitrary states. The only state query
--     writes the target state alongside the audit record that caused it, so a caller cannot
--     produce a state whose origin is not in the audit chain.
--   * There is no DELETE anywhere in this file. The three tables that must not lose a row
--     (revocations, the idempotency ledger, and the registry itself) are protected by triggers
--     in the migration; a query that asked to delete one would fail at runtime, and its absence
--     here means nobody writes code expecting it to work.
--   * The revocation queries answer containment questions by reading recorded revocations
--     rather than by reading live identities, so a blast radius is a function of what happened
--     and not of when the question was asked.
--
-- Every query is written to be safe under retry, because a lifecycle transition is decided
-- once and may be delivered twice. That is what the idempotency ledger is for, and it is why
-- the lookup and the insert are separate calls the journal sequences rather than one statement.

-- name: InsertModel :one
--
-- Register a model. The eleven required fields are all present because the migration's
-- constraints refuse a row missing any of them; the Go package decides *which* models
-- register, and this query only records the decision.
--
-- A duplicate model_id is a conflict rather than an update, and there is no ON CONFLICT
-- clause: overwriting a registered model in place is the exact defect the immutability
-- constraint exists to prevent, and an ON CONFLICT DO UPDATE here would quietly reintroduce
-- it for whichever caller happened to use this query.
INSERT INTO model_registry (
    model_id,
    version,
    owner,
    author,
    training_dataset_fingerprint,
    code_revision,
    feature_specification,
    evaluation_results,
    limitations,
    approval_record,
    deployment_scope,
    monitoring_policy,
    rollback_artifact,
    state,
    registered_at_utc,
    last_audit_id,
    updated_by,
    updated_at_utc
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
)
RETURNING *;

-- name: GetModel :one
SELECT * FROM model_registry WHERE model_id = $1;

-- name: ListModelsInState :many
--
-- The models currently in one lifecycle state, for the monitor and the reconciliation sweep.
-- Ordered by model_id rather than by registration time so that two callers asking the same
-- question at the same moment get the same order, which is what makes a sweep restartable.
SELECT * FROM model_registry WHERE state = $1 ORDER BY model_id;

-- name: ListActiveModels :many
--
-- Every model still able to serve inference. Terminal states are excluded here rather than by
-- the caller, because the interesting failure is a caller that forgot: retired and quarantined
-- models must never appear in a serving set, and the exclusion belongs next to the schema.
SELECT * FROM model_registry
WHERE state NOT IN ('RETIRED', 'QUARANTINED')
ORDER BY model_id;

-- name: ListAllModels :many
--
-- Every registered model, in every lifecycle state, for startup rehydration.
--
-- ListActiveModels is not a substitute. It is deliberately blind to the terminal states, which
-- is correct for a serving set and exactly wrong for a restore: a journal rebuilt only from
-- active models has no memory that a model was ever retired, so the model looks unregistered
-- and can be registered again from scratch. Terminal states are the rows that most have to
-- survive a restart.
--
-- Unbounded, unlike the audit reads, because this is bounded by the number of models rather
-- than by a retention period, and because a restore that silently loaded a prefix of the
-- registry would be worse than one that took the whole table.
SELECT * FROM model_registry ORDER BY model_id;

-- name: SetModelState :one
--
-- Record a lifecycle transition.
--
-- Two columns move together and deliberately. last_audit_id is not a default that a caller may
-- omit: the migration refuses a state change that cites no audit record, so a transition whose
-- cause was not recorded cannot be stored even if the caller wanted to store it. Making the
-- audit identifier a required parameter is what keeps that guarantee from depending on every
-- caller remembering it.
--
-- The transition's legality is enforced by the trigger, not by this query. The Go package
-- decides; the database refuses anything the package would have refused, so a second writer
-- cannot produce a state no evaluator would have produced.
UPDATE model_registry
SET state = $2,
    last_audit_id = $3,
    updated_by = $4,
    updated_at_utc = $5
WHERE model_id = $1
RETURNING *;

-- name: ListModelAuditRefs :many
--
-- The audit records that caused this model's current state and its immediately preceding one.
-- Ordered by update time descending so a reader sees the latest cause first, which is the one
-- a responder investigating a promotion needs.
SELECT last_audit_id, state, updated_by, updated_at_utc
FROM model_registry
WHERE model_id = $1
  AND last_audit_id <> ''
ORDER BY updated_at_utc DESC;

-- name: InsertWorkloadIdentity :one
--
-- Issue a short-lived identity bound to one exact model and version.
--
-- The expiry is a parameter rather than a database default, and the migration bounds it. A
-- caller cannot mint a long-lived identity by passing a far-future expiry, which is the
-- property that makes revocation meaningful: an identity cannot outlive the incident response
-- that has to revoke it.
--
-- An identity name that was ever revoked is refused by the trigger, so this insert cannot
-- resurrect a compromised workload under a name an operator has already seen shut down.
INSERT INTO workload_identities (
    identity,
    model_id,
    model_version,
    scope,
    issued_at_utc,
    expires_at_utc
) VALUES ($1, $2, $3, $4, $5, $6)
RETURNING *;

-- name: GetWorkloadIdentity :one
SELECT * FROM workload_identities WHERE identity = $1;

-- name: ListIdentitiesForModelVersion :many
--
-- Every identity currently serving one exact model version.
--
-- This is the query containment widens to. It takes the model *and* the version because
-- revoking only the detected workload is not containment: a compromised research worker shares
-- its code and its dataset with whatever else was serving that version, and those identities
-- have to be found from the store rather than from a list the responder kept in their head.
--
-- Revoked identities are included, deliberately. Containment must report what it took down
-- even after a restart, and a set that shrinks as revocations are processed would make the
-- blast radius a function of when it was asked rather than of what happened.
SELECT * FROM workload_identities
WHERE model_id = $1 AND model_version = $2
ORDER BY identity;

-- name: ListValidIdentitiesForModelVersion :many
--
-- The same set, restricted to identities not yet revoked and not yet expired.
--
-- Separate from ListIdentitiesForModelVersion on purpose. Containment wants the full set
-- (assertion 31 and the widening path); a serving check wants only the identities that may
-- still act. Collapsing them would mean either reporting fewer revocations than happened or
-- admitting revoked identities as usable, and both are worse than a second query.
SELECT i.* FROM workload_identities i
WHERE i.model_id = $1
  AND i.model_version = $2
  AND i.expires_at_utc > now()
  AND NOT EXISTS (
      SELECT 1 FROM workload_revocations r WHERE r.identity = i.identity
  )
ORDER BY i.identity;

-- name: ListRevocationsForModelVersion :many
--
-- The revocations recorded against one exact model version.
--
-- The reported blast radius is built from these rows rather than from the live identity set,
-- which is what makes containment report the same population on a retry as it did the first
-- time. Reading live identities instead would make the answer depend on which revocations had
-- already been written, so a retry after a partial failure would report a *smaller* blast
-- radius than the first attempt -- the one outcome a compromise response must never produce.
SELECT * FROM workload_revocations
WHERE model_id = $1 AND model_version = $2
ORDER BY revoked_at_utc, identity;

-- name: GetRevocation :one
SELECT * FROM workload_revocations WHERE identity = $1;

-- name: ListRevocationsForIdentityModel :many
--
-- Every revocation for one identity, across versions. An identity that served two versions
-- and was compromised in both has two rows, and an investigation needs both: the reason names
-- the incident, and the version says how much surface was exposed.
SELECT * FROM workload_revocations
WHERE identity = $1
ORDER BY revoked_at_utc;

-- name: ListAllWorkloadIdentities :many
--
-- Every workload identity ever issued, for startup rehydration.
--
-- ListValidIdentitiesForModelVersion is not a substitute: it filters to currently valid ones,
-- which is right for a serving check and exactly wrong for a restore, because an expired or
-- revoked identity that is not loaded here becomes mintable again. The revocation check in the
-- registry is a lookup in a map that only exists if the revocations were loaded too, so a
-- partial load of either table silently removes a security control.
SELECT * FROM workload_identities ORDER BY identity;

-- name: ListAllWorkloadRevocations :many
--
-- Every revocation, for startup rehydration.
--
-- Unbounded for the same reason as the identity list: this table is the authority on which
-- identities must never be re-minted, and loading a prefix of it means the identities not
-- covered by that prefix have no recorded revocation.
SELECT * FROM workload_revocations ORDER BY revoked_at_utc, identity;

-- name: InsertRevocation :one
--
-- Revoke an identity, permanently.
--
-- reason and evidence_ref are required by the migration and are parameters here, not optional
-- metadata. An unattributed revocation cannot be reviewed, and revocation is the action an
-- operator disputes first, so the record has to say why and on what forensic basis.
--
-- There is no update or delete path for this table, by design.
INSERT INTO workload_revocations (
    identity,
    model_id,
    model_version,
    revoked_at_utc,
    reason,
    evidence_ref,
    revoked_by
) VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;

-- name: IsIdentityRevoked :one
--
-- Whether this identity name has ever been revoked, in any model version.
--
-- Scoped by identity alone, not by (identity, model, version), because the guarantee is about
-- the *name*: a workload shut down as compromised must not be able to re-appear under that
-- name attached to a different version. Scoping this by version would make revocation a
-- property of a deployment rather than of an identity, which is the weaker and wrong claim.
SELECT EXISTS (
    SELECT 1 FROM workload_revocations WHERE identity = $1
) AS revoked;

-- name: GetTransitionIdempotency :one
--
-- The transition previously applied under this scope and key, if any.
--
-- The journal calls this before deciding to apply, and its absence is what tells the journal
-- this is a first attempt rather than a retry.
SELECT * FROM model_transition_idempotency
WHERE idempotency_scope = $1 AND idempotency_key = $2;

-- name: RecordTransitionIdempotency :one
--
-- Record that a transition has been applied.
--
-- The primary key on (idempotency_scope, idempotency_key) is the concurrency control. Two
-- concurrent retries of the same transition race here, one wins, and the loser gets a unique
-- violation rather than a second application. This is why the insert exists as its own call
-- after the state write rather than being folded into it: a single statement cannot distinguish
-- "applied by me" from "applied by a concurrent retry of mine", and guessing wrong either
-- applies a transition twice or hides one that was applied.
--
-- The caller supplies request_fingerprint. A retry carrying a *different* fingerprint under
-- the same key is a different request that collided with an idempotency key, which the journal
-- must surface rather than treat as a retry of the first.
INSERT INTO model_transition_idempotency (
    idempotency_scope,
    idempotency_key,
    request_fingerprint,
    model_id,
    from_state,
    to_state,
    audit_id,
    applied_at_utc
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
RETURNING *;

-- name: ListAllIdempotency :many
--
-- Every transition applied to any model, oldest first.
--
-- This reconstructs each model's lifecycle from recorded applications rather than from the
-- current state, so a reader can see the path taken and not only where it ended up. Ordered
-- oldest first because the sequence *is* the information; reversing it would make the list
-- unreadable while still looking plausible.
--
-- Deliberately one query for the whole ledger rather than one per model. The rehydration
-- reader restores every model, so the per-model form made startup cost one round trip per
-- registered model, strictly sequential, and a registry with a few thousand models then spent
-- startup waiting on the network rather than reading. Ordering within a model is unchanged, so
-- a caller that cares about one model's path reads the same order out of this list.
SELECT * FROM model_transition_idempotency
ORDER BY model_id, applied_at_utc, idempotency_scope, idempotency_key;
