-- Model governance persistence: the registry, its lifecycle state, the workload identities
-- that may serve it, the revocations that stop them, and the idempotency ledger that makes a
-- retried transition the same transition.
--
-- Authority. This database is the server-held record of which models exist, where each is in
-- its lifecycle, and which workload identities may serve them (docs/07, docs/25 section 5).
-- It is not the decision engine: the Go package in services/control-plane/model decides, and
-- services/control-plane/model/journal.go is the only write path. The split matters because a
-- lifecycle transition decided from caller-supplied state is not a governed transition, and the
-- only way to guarantee the subject state came from the server is to hold it here.
--
-- Every guard below is deliberately redundant with the Go package, for the same reason
-- 0002_audit.sql and 0003_authz.sql are: a constraint that exists only in application code is
-- a convention, and this domain is specifically about not relying on conventions. The
-- verification script proves the database refuses writes that the Go package would also refuse,
-- because a second writer bypassing the Go package must not be able to produce a state no
-- evaluator would have produced.
--
-- What is NOT enforced here: nothing in this file decides whether a transition is permitted,
-- whether an actor may perform it, or whether an approval is independent. Those are the Go
-- package's, and the exclusions below deliberately do not attempt them. Neither can produce an
-- allow on its own, and neither is a bypass of the other. docs/07 and ADR-0xx are unchanged by
-- this file.
--
-- The one property this migration is most careful about: a revocation must not be deletable.
-- EV-040 recorded that revocation which lives only in the process that issued it is not
-- revocation, and that a restart loses the registry, the audit chain, and the idempotency
-- ledger together. The revocations table here is append-only and a revoked identity name can
-- never be re-issued, so a workload that was shut down stays shut down across a restart even
-- if every other table were lost. That is deliberately the narrowest of the guarantees in this
-- file, and it is the one that matters most.

BEGIN;

-- --- Model registry ------------------------------------------------------------

CREATE TABLE model_registry (
    model_id            text        NOT NULL,
    version             text        NOT NULL,
    owner               text        NOT NULL,
    author              text        NOT NULL,
    training_dataset_fingerprint text NOT NULL,
    code_revision       text        NOT NULL,
    feature_specification text      NOT NULL,
    evaluation_results  text        NOT NULL,
    limitations         text        NOT NULL,
    approval_record     text        NOT NULL DEFAULT '',
    deployment_scope    text        NOT NULL,
    monitoring_policy   text        NOT NULL,
    rollback_artifact   text        NOT NULL,
    state               text        NOT NULL,
    registered_at_utc   timestamptz NOT NULL,
    -- The audit identity of the record that produced the current state. This is the
    -- causation link: without it the registry holds a state whose origin is not recorded in
    -- audit_records, which is the same defect as a state change with no audit trail.
    last_audit_id       text        NOT NULL DEFAULT '',
    -- The identity that performed the most recent transition.
    updated_by          text        NOT NULL DEFAULT '',
    updated_at_utc      timestamptz NOT NULL,

    CONSTRAINT model_registry_pkey PRIMARY KEY (model_id),

    -- An in-place edit of a registered model is not a version, it is a new model. The primary
    -- key on model_id alone is what makes that true, and it is the reason a re-registration
    -- cannot overwrite a record: two records with the same id and different versions cannot
    -- both exist, so a second write is a conflict rather than a replacement.
    CONSTRAINT model_registry_version_present CHECK (length(btrim(version)) > 0),
    CONSTRAINT model_registry_owner_present CHECK (length(btrim(owner)) > 0),
    CONSTRAINT model_registry_author_present CHECK (length(btrim(author)) > 0),
    -- The model identifier carries the canonical prefix, enforced here so a row cannot name a
    -- model the Go package would refuse to parse.
    CONSTRAINT model_registry_id_prefixed CHECK (model_id LIKE 'mdl\_%'),
    CONSTRAINT model_registry_id_length CHECK (length(model_id) <= 34),
    -- The eleven required fields are non-empty. A model whose limitations are unrecorded is a
    -- model whose failure modes are unknown, and registering it would put that unknown model
    -- into the lifecycle, so the statement is required rather than merely documented.
    CONSTRAINT model_registry_digest_shape CHECK (
        training_dataset_fingerprint ~ '^[0-9a-f]{64}$' AND
        evaluation_results          ~ '^[0-9a-f]{64}$' AND
        rollback_artifact           ~ '^[0-9a-f]{64}$' AND
        (approval_record = '' OR approval_record ~ '^[0-9a-f]{64}$')),
    CONSTRAINT model_registry_required_present CHECK (
        length(btrim(training_dataset_fingerprint)) > 0 AND
        length(btrim(code_revision))         > 0 AND
        length(btrim(feature_specification))  > 0 AND
        length(btrim(evaluation_results))     > 0 AND
        length(btrim(limitations))            > 0 AND
        length(btrim(deployment_scope))       > 0 AND
        length(btrim(monitoring_policy))      > 0 AND
        length(btrim(rollback_artifact))      > 0),

    -- The closed state set from docs/07 plus QUARANTINED, repeated here so an out-of-set
    -- value is refused by the database and not only by the Go package's validation.
    CONSTRAINT model_registry_state_closed CHECK (state IN
        ('REGISTERED', 'EVALUATED', 'VALIDATED', 'APPROVED', 'PAPER',
         'SHADOW', 'PROMOTED', 'MONITORED', 'RETIRED', 'QUARANTINED')),

    -- Owner and author must be distinguishable. docs/07 forbids self-approval, and the first
    -- mechanical form of that is refusing to register a model whose owner and author are the
    -- same identity: there would then be no pair of people to approve and refuse, whatever
    -- the Go package later decides.
    CONSTRAINT model_registry_owner_differs_from_author CHECK (owner <> author)
);

-- A model may not move sideways. The forward path is the docs/07 lifecycle order and the
-- only permitted non-forward moves are the two terminal states. Enforcing the adjacency here
-- means a writer bypassing the Go package cannot promote a QUARANTINED model by writing
-- PROMOTED, which is the failure docs/25 section 6 is written against.
CREATE FUNCTION model_registry_check_transition() RETURNS trigger AS $$
DECLARE
    allowed boolean := false;
BEGIN
    IF NEW.state = OLD.state THEN
        -- Re-writing the same state is not a transition. Permitted, because a journal that
        -- records the audit record for a retry must still be able to store the row.
        allowed := true;
    ELSIF OLD.state = 'QUARANTINED' THEN
        -- Quarantine is terminal for anything but retirement. A cleared compromise routes
        -- through RETIRED and re-enters the lifecycle as a new version, never in place.
        allowed := (NEW.state = 'RETIRED');
    ELSIF OLD.state = 'RETIRED' THEN
        -- Retired is terminal outright.
        allowed := false;
    ELSE
        allowed := CASE OLD.state
            WHEN 'REGISTERED' THEN NEW.state IN ('EVALUATED', 'QUARANTINED')
            WHEN 'EVALUATED'  THEN NEW.state IN ('VALIDATED', 'QUARANTINED')
            WHEN 'VALIDATED'  THEN NEW.state IN ('APPROVED', 'QUARANTINED')
            WHEN 'APPROVED'   THEN NEW.state IN ('PAPER', 'QUARANTINED')
            WHEN 'PAPER'      THEN NEW.state IN ('SHADOW', 'QUARANTINED')
            WHEN 'SHADOW'     THEN NEW.state IN ('PROMOTED', 'QUARANTINED')
            WHEN 'PROMOTED'   THEN NEW.state IN ('MONITORED', 'QUARANTINED')
            WHEN 'MONITORED'  THEN NEW.state IN ('RETIRED', 'QUARANTINED')
            ELSE false
        END;
    END IF;

    IF NOT allowed THEN
        RAISE EXCEPTION 'refused model %: % -> % is not a declared lifecycle transition',
            NEW.model_id, OLD.state, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    -- A state change must cite the audit record that caused it, or the registry holds a state
    -- whose origin is not in the audit chain. Registration is exempt because it is the first
    -- event and there is nothing before it; the Go journal sets last_audit_id on it too.
    IF NEW.state <> OLD.state AND length(btrim(NEW.last_audit_id)) = 0 THEN
        RAISE EXCEPTION 'refused model %: a state change to % cites no audit record',
            NEW.model_id, NEW.state
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER model_registry_transition_guard
    BEFORE UPDATE ON model_registry
    FOR EACH ROW EXECUTE FUNCTION model_registry_check_transition();

-- The immutable half of a model record must not change. version, owner, author, the dataset
-- fingerprint, the code revision, the feature specification, the evaluation results, the
-- limitations, the deployment scope, the monitoring policy, and the rollback artifact together
-- define what the model is. Allowing any of them to be edited in place would make two rows
-- with the same primary key describe different models, and the digest of the record would no
-- longer identify the thing it was computed for.
CREATE FUNCTION model_registry_refuse_identity_mutation() RETURNS trigger AS $$
DECLARE
    msg text;
BEGIN
    IF NEW.model_id                 IS DISTINCT FROM OLD.model_id
       OR NEW.version               IS DISTINCT FROM OLD.version
       OR NEW.owner                 IS DISTINCT FROM OLD.owner
       OR NEW.author                IS DISTINCT FROM OLD.author
       OR NEW.training_dataset_fingerprint IS DISTINCT FROM OLD.training_dataset_fingerprint
       OR NEW.code_revision        IS DISTINCT FROM OLD.code_revision
       OR NEW.feature_specification IS DISTINCT FROM OLD.feature_specification
       OR NEW.evaluation_results   IS DISTINCT FROM OLD.evaluation_results
       OR NEW.limitations          IS DISTINCT FROM OLD.limitations
       OR NEW.deployment_scope     IS DISTINCT FROM OLD.deployment_scope
       OR NEW.monitoring_policy    IS DISTINCT FROM OLD.monitoring_policy
       OR NEW.rollback_artifact    IS DISTINCT FROM OLD.rollback_artifact THEN
        msg := format('refused model %s: the model record is immutable in place; a change '
            || 'to what the model is requires a new version, which is a new model_id',
            NEW.model_id);
        RAISE EXCEPTION '%', msg USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER model_registry_identity_immutable
    BEFORE UPDATE ON model_registry
    FOR EACH ROW EXECUTE FUNCTION model_registry_refuse_identity_mutation();

-- --- Workload identities -------------------------------------------------------

CREATE TABLE workload_identities (
    identity            text        NOT NULL,
    model_id            text        NOT NULL,
    model_version       text        NOT NULL,
    scope               text        NOT NULL,
    issued_at_utc       timestamptz NOT NULL,
    expires_at_utc      timestamptz NOT NULL,

    CONSTRAINT workload_identities_pkey PRIMARY KEY (identity),
    CONSTRAINT workload_identities_id_present CHECK (length(btrim(identity)) > 0),
    CONSTRAINT workload_identities_model_prefixed CHECK (model_id LIKE 'mdl\_%'),
    CONSTRAINT workload_identities_version_present CHECK (length(btrim(model_version)) > 0),
    -- The closed scope set. docs/25 section 5 names producing artefacts and serving inference
    -- and names no third, and a scope outside the set is a scope no evaluator has considered.
    CONSTRAINT workload_identities_scope_closed CHECK (scope IN
        ('PRODUCE_ARTIFACTS', 'SERVE_INFERENCE')),
    -- Short-lived is enforced as a bound rather than described: a caller cannot mint a
    -- long-lived identity by writing a far-future expiry, because the maximum lifetime is a
    -- constraint. The Go package's WorkloadTTL is one hour and a drift test asserts the two
    -- agree, because a lifetime that differs between layers is an identity that is valid in
    -- one and expired in the other.
    CONSTRAINT workload_identities_expiry_after_issue CHECK (expires_at_utc > issued_at_utc),
    CONSTRAINT workload_identities_lifetime_bounded
        CHECK (expires_at_utc <= issued_at_utc + interval '24 hours')
);

-- The exact-version binding needs an index in this direction, not the model's. Containment
-- looks up "every identity serving this model at this version" and an index on (model_id,
-- model_version) is what makes that a range scan rather than a table scan. Containment runs
-- during a compromise, when latency is least welcome.
CREATE INDEX workload_identities_model_version_idx
    ON workload_identities (model_id, model_version);

-- --- Revocations ---------------------------------------------------------------

-- Append-only, and the reason the rest of the file is worth the trouble. EV-040 recorded that
-- a revocation held only in the process that issued it is not revocation; this table is the
-- part of that gap this migration closes. It also records the model version the revocation
-- covered, so an investigation can ask what was taken down without reconstructing it from
-- worker logs, and so a containment that was too narrow or too broad is visible afterwards.
CREATE TABLE workload_revocations (
    identity            text        NOT NULL,
    model_id            text        NOT NULL,
    model_version       text        NOT NULL,
    revoked_at_utc      timestamptz NOT NULL,
    reason              text        NOT NULL,
    evidence_ref        text        NOT NULL,
    revoked_by          text        NOT NULL DEFAULT '',

    CONSTRAINT workload_revocations_pkey PRIMARY KEY (identity),
    -- An unattributed revocation is not auditable, and revocation is the action that gets
    -- disputed. Both the reason and the forensic evidence reference are required, not merely
    -- recommended.
    CONSTRAINT workload_revocations_reason_present CHECK (length(btrim(reason)) > 0),
    CONSTRAINT workload_revocations_evidence_present CHECK (length(btrim(evidence_ref)) > 0),
    CONSTRAINT workload_revocations_model_prefixed CHECK (model_id LIKE 'mdl\_%'),
    CONSTRAINT workload_revocations_version_present CHECK (length(btrim(model_version)) > 0)
);

CREATE INDEX workload_revocations_model_version_idx
    ON workload_revocations (model_id, model_version);

-- A revocation is permanent. This is the one table in the schema with no update or delete path
-- at all, and the rule is that a compromised workload re-enters through a NEW identity rather
-- than resurrecting the one that was shut down. Without this, correcting a mistaken revocation
-- would be a DELETE, and a DELETE is indistinguishable from an attacker erasing the evidence.
CREATE FUNCTION workload_revocations_refuse_mutation() RETURNS trigger AS $$
DECLARE
    msg text;
BEGIN
    msg := format('refused: workload_revocations is append-only; revocation %s is permanent '
        || 'and a compromised workload re-enters through a new identity', OLD.identity);
    RAISE EXCEPTION '%', msg USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workload_revocations_append_only
    BEFORE UPDATE OR DELETE ON workload_revocations
    FOR EACH ROW EXECUTE FUNCTION workload_revocations_refuse_mutation();

-- A revoked identity name is never re-issued. Without this, a workload could be shut down and
-- then mint a fresh identity under the same name, which would defeat containment while every
-- record of the shutdown remained intact and true. The Go package refuses this in Mint; the
-- constraint here means the refusal survives a restart, which is the case the Go package
-- cannot cover.
CREATE FUNCTION workload_identities_refuse_revoked_reissue() RETURNS trigger AS $$
DECLARE
    msg text;
BEGIN
    IF EXISTS (SELECT 1 FROM workload_revocations WHERE identity = NEW.identity) THEN
        msg := format('refused: identity %s was revoked; a compromised workload re-enters '
            || 'through a new identity, not by resurrecting the old name', NEW.identity);
        RAISE EXCEPTION '%', msg USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workload_identities_no_revoked_reissue
    BEFORE INSERT ON workload_identities
    FOR EACH ROW EXECUTE FUNCTION workload_identities_refuse_revoked_reissue();

-- --- Idempotency ledger --------------------------------------------------------

-- One row per applied transition, keyed by the transition's declared scope plus the caller's
-- key. A retry of the same request resolves to the recorded outcome; the same scope and key
-- carrying a different request is a conflict, and the fingerprint below is what makes that
-- detectable rather than silently resolved in favour of whichever copy arrived first.
CREATE TABLE model_transition_idempotency (
    idempotency_scope   text        NOT NULL,
    idempotency_key     text        NOT NULL,
    request_fingerprint text        NOT NULL,
    model_id            text        NOT NULL,
    from_state          text        NOT NULL,
    to_state            text        NOT NULL,
    audit_id            text        NOT NULL,
    applied_at_utc      timestamptz NOT NULL,

    CONSTRAINT model_transition_idempotency_pkey PRIMARY KEY (idempotency_scope, idempotency_key),
    CONSTRAINT model_transition_idempotency_key_present CHECK (length(btrim(idempotency_key)) >= 8),
    CONSTRAINT model_transition_idempotency_scope_present CHECK (length(btrim(idempotency_scope)) > 0),
    CONSTRAINT model_transition_idempotency_fingerprint_shape
        CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT model_transition_idempotency_audit_present CHECK (length(btrim(audit_id)) > 0),
    -- The recorded states must be real, so a ledger row cannot describe a transition to a
    -- state the lifecycle does not have.
    CONSTRAINT model_transition_idempotency_states_closed CHECK (
        from_state IN ('REGISTERED', 'EVALUATED', 'VALIDATED', 'APPROVED', 'PAPER',
                       'SHADOW', 'PROMOTED', 'MONITORED', 'RETIRED', 'QUARANTINED') AND
        to_state   IN ('REGISTERED', 'EVALUATED', 'VALIDATED', 'APPROVED', 'PAPER',
                       'SHADOW', 'PROMOTED', 'MONITORED', 'RETIRED', 'QUARANTINED'))
);

-- An applied transition is permanent for the same reason a revocation is: the row is the
-- record that the transition happened exactly once. Editing it to point at a different
-- fingerprint would make a retried request indistinguishable from a second one.
CREATE FUNCTION model_transition_idempotency_refuse_mutation() RETURNS trigger AS $$
DECLARE
    msg text;
BEGIN
    msg := format('refused: an applied transition is recorded once and not amended; scope %s '
        || 'key %s already names fingerprint %s', OLD.idempotency_scope, OLD.idempotency_key,
        OLD.request_fingerprint);
    RAISE EXCEPTION '%', msg USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

-- DELETE is included for the same reason it is on workload_revocations: an idempotency ledger
-- that can be pruned is not a ledger of what happened. A transition whose key row is deleted
-- becomes re-appliable, so a retried request would perform the transition a second time.
CREATE TRIGGER model_transition_idempotency_append_only
    BEFORE UPDATE OR DELETE ON model_transition_idempotency
    FOR EACH ROW EXECUTE FUNCTION model_transition_idempotency_refuse_mutation();

-- A revocation must carry its evidence into the same place the audit record does. This is the
-- linkage that lets an investigation start from a revocation and reach the audit chain, rather
-- than searching two stores for a string that ought to match.
ALTER TABLE workload_revocations
    ADD CONSTRAINT workload_revocations_audit_link_present
    CHECK (length(btrim(evidence_ref)) > 0);

COMMIT;

-- migrate:down
-- === Down ======================================================================
--
-- A deliberate schema rollback that discards the registry, every workload identity, and the
-- entire revocation history. That last part is the reason this is documented as a cost rather
-- than a convenience: a rollback after this migration has been applied in production leaves
-- no record that any workload was ever revoked, and every identity name becomes issuable again.
-- docs/09 lists migration rehearsal as a release gate precisely so that the cost of a rollback
-- is known before it is chosen, and rehearse_migrations.py exercises this body.
BEGIN;

DROP TABLE IF EXISTS model_transition_idempotency CASCADE;
DROP TABLE IF EXISTS workload_revocations CASCADE;
DROP TABLE IF EXISTS workload_identities CASCADE;
DROP TABLE IF EXISTS model_registry CASCADE;

DROP FUNCTION IF EXISTS model_transition_idempotency_refuse_mutation() CASCADE;
DROP FUNCTION IF EXISTS workload_identities_refuse_revoked_reissue() CASCADE;
DROP FUNCTION IF EXISTS workload_revocations_refuse_mutation() CASCADE;
DROP FUNCTION IF EXISTS model_registry_refuse_identity_mutation() CASCADE;
DROP FUNCTION IF EXISTS model_registry_check_transition() CASCADE;

COMMIT;
