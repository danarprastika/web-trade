-- Audit integrity: append-only hash-chained records with signed checkpoints.
--
-- Authority. This database stores audit evidence (docs/22, ADR-022). It is a store, not
-- the trust root: the chain and the signed checkpoints are what make the evidence
-- verifiable without trusting this database. A database that enforced only "append-only"
-- would prove that nobody used SQL, not that the evidence says what it claims.
--
-- Every guard here is deliberately redundant with the Go package. The Go package refuses
-- an invalid record; this migration refuses it again at the storage layer, because a
-- second writer that does not go through the Go package would otherwise be able to write
-- anything at all.

BEGIN;

CREATE TABLE audit_records (
    audit_id           text        NOT NULL,
    partition          text        NOT NULL,
    sequence           bigint      NOT NULL,
    actor_id           text        NOT NULL,
    actor_type         text        NOT NULL,
    action             text        NOT NULL,
    target_type        text        NOT NULL DEFAULT '',
    target_id          text        NOT NULL DEFAULT '',
    environment        text        NOT NULL,
    market_scope       text        NOT NULL DEFAULT '',
    occurred_at_utc    timestamptz NOT NULL,
    recorded_at_utc    timestamptz NOT NULL,
    reason             text        NOT NULL DEFAULT '',
    correlation_id     text        NOT NULL DEFAULT '',
    causation_id       text        NOT NULL DEFAULT '',
    policy_version     text        NOT NULL DEFAULT '',
    result             text        NOT NULL,
    before_digest      text        NOT NULL DEFAULT '',
    after_digest       text        NOT NULL DEFAULT '',
    previous_hash      bytea       NOT NULL,
    record_hash        bytea       NOT NULL,
    signing_key_id     text        NOT NULL DEFAULT '',
    schema_version     integer     NOT NULL,

    CONSTRAINT audit_records_pkey PRIMARY KEY (audit_id),

    -- A sequence is unique within its partition, which is what makes a replayed record
    -- impossible to store even by a writer that does not consult the Go package.
    CONSTRAINT audit_records_partition_sequence_key UNIQUE (partition, sequence),

    CONSTRAINT audit_records_sequence_positive CHECK (sequence >= 1),
    CONSTRAINT audit_records_hash_length CHECK (length(record_hash) = 32),
    CONSTRAINT audit_records_previous_hash_length CHECK (length(previous_hash) = 32),
    CONSTRAINT audit_records_actor_id_present CHECK (length(btrim(actor_id)) > 0),
    CONSTRAINT audit_records_partition_present CHECK (length(btrim(partition)) > 0),
    CONSTRAINT audit_records_action_present CHECK (length(btrim(action)) > 0),
    CONSTRAINT audit_records_environment_present CHECK (length(btrim(environment)) > 0),

    -- The closed sets, repeated here so an out-of-set value is refused by the database
    -- and not only by the Go package's validation.
    CONSTRAINT audit_records_actor_type_closed CHECK (actor_type IN
        ('HUMAN', 'SERVICE', 'AGENT', 'STRATEGY', 'SYSTEM', 'BREAK_GLASS')),
    CONSTRAINT audit_records_result_closed CHECK (result IN
        ('SUCCEEDED', 'REFUSED', 'FAILED', 'PARTIAL', 'UNKNOWN')),

    -- The canonical schema version is part of the hashed payload, so a record written
    -- under a different version must not be silently accepted alongside current ones.
    CONSTRAINT audit_records_schema_version CHECK (schema_version = 1),

    -- A record cannot be recorded before it occurred. Clock skew between hosts is real,
    -- so a small tolerance is allowed rather than demanding perfect ordering.
    CONSTRAINT audit_records_recorded_not_before_occurred
        CHECK (recorded_at_utc >= occurred_at_utc - interval '5 minutes')
);

CREATE INDEX audit_records_correlation_idx ON audit_records (correlation_id);
CREATE INDEX audit_records_partition_sequence_idx ON audit_records (partition, sequence DESC);
CREATE INDEX audit_records_recorded_at_idx ON audit_records (recorded_at_utc DESC);

-- Signatures are held as bytes because the signing algorithm is chosen by the KMS, not by
-- this schema. A text column would have pinned the storage format to one algorithm.
CREATE TABLE audit_checkpoints (
    partition       text        NOT NULL,
    first_sequence  bigint      NOT NULL,
    last_sequence   bigint      NOT NULL,
    first_hash      bytea       NOT NULL,
    last_hash       bytea       NOT NULL,
    record_count    integer     NOT NULL,
    created_at_utc  timestamptz NOT NULL,
    signing_key_id  text        NOT NULL,
    signature       bytea,
    schema_version  integer     NOT NULL,

    CONSTRAINT audit_checkpoints_pkey PRIMARY KEY (partition, first_sequence),
    CONSTRAINT audit_checkpoints_range_valid CHECK (last_sequence >= first_sequence AND first_sequence >= 1),
    CONSTRAINT audit_checkpoints_count_positive CHECK (record_count > 0),
    CONSTRAINT audit_checkpoints_first_hash_length CHECK (length(first_hash) = 32),
    CONSTRAINT audit_checkpoints_last_hash_length CHECK (length(last_hash) = 32),
    CONSTRAINT audit_checkpoints_key_present CHECK (length(btrim(signing_key_id)) > 0),
    CONSTRAINT audit_checkpoints_schema_version CHECK (schema_version = 1),

    -- Two checkpoints covering the same sequence range would make "the" signed boundary
    -- ambiguous, and ambiguity here is indistinguishable from tampering.
    CONSTRAINT audit_checkpoints_range_unique UNIQUE (partition, last_sequence)
);

-- The retained record of a deletion. docs/22 section 4 requires the deletion event itself
-- to be retained, so this table is also append-only and is never shortened.
CREATE TABLE audit_deletion_events (
    audit_id       text        NOT NULL,
    partition      text        NOT NULL,
    first_sequence bigint      NOT NULL,
    last_sequence  bigint      NOT NULL,
    requested_by   text        NOT NULL,
    approved_by    text        NOT NULL,
    deleted_at_utc timestamptz NOT NULL,

    CONSTRAINT audit_deletion_events_pkey PRIMARY KEY (audit_id),
    CONSTRAINT audit_deletion_events_distinct_people CHECK (requested_by <> approved_by),
    CONSTRAINT audit_deletion_events_both_present
        CHECK (length(btrim(requested_by)) > 0 AND length(btrim(approved_by)) > 0)
);

-- --- Append-only enforcement ---------------------------------------------------
--
-- Row-level triggers do not fire for TRUNCATE, so without a statement-level trigger the
-- entire chain could be erased in a single statement. That omission was found while
-- verifying WI-116's ledger migration and is closed here from the start.

CREATE FUNCTION audit_refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit evidence is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
    -- Returning is unreachable, but PL/pgSQL requires it: without it the function falls
    -- off the end and PostgreSQL raises an error that masks the intended message.
    RETURN NULL;
END;
$$;

CREATE TRIGGER audit_records_no_mutation
    BEFORE UPDATE OR DELETE ON audit_records
    FOR EACH ROW EXECUTE FUNCTION audit_refuse_mutation();

CREATE TRIGGER audit_checkpoints_no_mutation
    BEFORE UPDATE OR DELETE ON audit_checkpoints
    FOR EACH ROW EXECUTE FUNCTION audit_refuse_mutation();

CREATE TRIGGER audit_deletion_events_no_mutation
    BEFORE UPDATE OR DELETE ON audit_deletion_events
    FOR EACH ROW EXECUTE FUNCTION audit_refuse_mutation();

CREATE TRIGGER audit_records_no_truncate
    BEFORE TRUNCATE ON audit_records
    FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_mutation();

CREATE TRIGGER audit_checkpoints_no_truncate
    BEFORE TRUNCATE ON audit_checkpoints
    FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_mutation();

CREATE TRIGGER audit_deletion_events_no_truncate
    BEFORE TRUNCATE ON audit_deletion_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_mutation();

-- A record must link to the record that actually precedes it in its partition.
--
-- This is a constraint trigger because it must see the committed row, and it is
-- DEFERRABLE INITIALLY DEFERRED so that a batch may be inserted in any order within its
-- transaction and still be checked once, at commit, when the whole chain is present.
CREATE FUNCTION audit_check_chain_link() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    prior_hash bytea;
BEGIN
    SELECT record_hash INTO prior_hash
      FROM audit_records
     WHERE partition = NEW.partition
       AND sequence = NEW.sequence - 1;

    IF FOUND THEN
        IF prior_hash <> NEW.previous_hash THEN
            RAISE EXCEPTION
                'audit chain break: record % at % sequence % names previous_hash % but the preceding record hashes to %',
                NEW.audit_id, NEW.partition, NEW.sequence,
                encode(NEW.previous_hash, 'hex'), encode(prior_hash, 'hex')
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    ELSIF NEW.sequence > 1 THEN
        -- No predecessor exists yet. This is only legitimate at the head of a chain that
        -- has not been restored into; the checkpoint table is what proves that.
        RAISE EXCEPTION
            'audit deletion: record % at % sequence % has no predecessor',
            NEW.audit_id, NEW.partition, NEW.sequence
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER audit_records_chain_link
    AFTER INSERT ON audit_records
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION audit_check_chain_link();

-- A checkpoint must agree with the records it claims to cover. Verified at commit so a
-- checkpoint and its batch can be written in either order within one transaction.
CREATE FUNCTION audit_check_checkpoint_coverage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    covered    integer;
    actual_first bytea;
    actual_last  bytea;
BEGIN
    SELECT count(*) INTO covered
      FROM audit_records
     WHERE partition = NEW.partition
       AND sequence BETWEEN NEW.first_sequence AND NEW.last_sequence;

    IF covered <> NEW.record_count THEN
        RAISE EXCEPTION
            'checkpoint covers % records but % are present in % sequences %..%',
            NEW.record_count, covered, NEW.partition, NEW.first_sequence, NEW.last_sequence
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- The boundary hashes are looked up at their exact sequences rather than derived with
    -- min()/max(). A bytea aggregate orders by byte value, not by sequence, so it would
    -- silently return the wrong record's hash and refuse a perfectly valid checkpoint.
    SELECT record_hash INTO actual_first
      FROM audit_records
     WHERE partition = NEW.partition AND sequence = NEW.first_sequence;

    SELECT record_hash INTO actual_last
      FROM audit_records
     WHERE partition = NEW.partition AND sequence = NEW.last_sequence;

    IF actual_first IS DISTINCT FROM NEW.first_hash THEN
        RAISE EXCEPTION
            'checkpoint first_hash does not match the record at sequence % in %',
            NEW.first_sequence, NEW.partition
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF actual_last IS DISTINCT FROM NEW.last_hash THEN
        RAISE EXCEPTION
            'checkpoint last_hash does not match the record at sequence % in %',
            NEW.last_sequence, NEW.partition
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER audit_checkpoints_coverage
    AFTER INSERT ON audit_checkpoints
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION audit_check_checkpoint_coverage();

COMMIT;

-- migrate:down
-- The reverse of the migration above.
--
-- These tables are append-only by trigger, so a normal DELETE is refused by the very guards
-- this migration installs. The drops work anyway: DROP TABLE does not fire the row triggers
-- it is about to remove. That asymmetry is correct, and it is also why a down migration is
-- not evidence that append-only is negotiable -- the reversal is a schema operation performed
-- deliberately by a migration runner, not a write any application role can perform.
BEGIN;

DROP TABLE IF EXISTS audit_records CASCADE;
DROP TABLE IF EXISTS audit_checkpoints CASCADE;
DROP TABLE IF EXISTS audit_deletion_events CASCADE;

-- Dropped after the tables, because each function is referenced by triggers on them and
-- PostgreSQL refuses to drop a function that still has dependents.
DROP FUNCTION IF EXISTS audit_check_checkpoint_coverage() CASCADE;
DROP FUNCTION IF EXISTS audit_check_chain_link() CASCADE;
DROP FUNCTION IF EXISTS audit_refuse_mutation() CASCADE;

COMMIT;
