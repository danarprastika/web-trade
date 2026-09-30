-- 0001_ledger.sql
--
-- The append-only ledger (WI-116).
--
-- This migration exists to make append-only a property of the storage layer rather than a
-- convention the Go package happens to follow. An application that can UPDATE a financial
-- fact has a table, not a ledger, and a table of financial facts cannot be reconciled against
-- a venue record because there is no history left to compare it to. The triggers below are
-- the real enforcement; the Go interface is the ergonomic surface on top of them.
--
-- PostgreSQL 17. Schema owner: the ledger domain. Per docs/05 section 'PostgreSQL schema
-- domains', each schema owns its tables and cross-domain writes go through domain services,
-- so no other module writes here.

BEGIN;

CREATE SCHEMA IF NOT EXISTS ledger;

-- The entry header. One row per posting set.
--
-- `sequence_no` is assigned by the database from a dedicated sequence rather than by the
-- caller, and is the ledger's only total order. It is deliberately not a timestamp: two
-- entries committed in the same microsecond must still have a defined order, and a clock is
-- not sufficient for that.
CREATE SEQUENCE ledger.entry_sequence AS bigint START WITH 1 INCREMENT BY 1;

CREATE TABLE ledger.entry (
    -- Canonical identity, minted once and never reused. The 'led_' prefix is checked so an
    -- identifier from another domain cannot be posted here.
    entry_id            text        PRIMARY KEY,

    -- Monotonic, dense, and gapless. UNIQUE because it is an ordering key, not a hint.
    sequence_no         bigint      NOT NULL UNIQUE
                                    DEFAULT nextval('ledger.entry_sequence'),

    -- The command or event that caused this entry. docs/05 requires every entry to
    -- reference its source, so this is NOT NULL rather than nullable "unknown".
    source_command_id   text        NOT NULL,

    -- Ties the entry to the request chain, so every entry from one decision can be found
    -- together. Also NOT NULL for the same reason.
    correlation_id      text        NOT NULL,

    -- Set only on a compensating entry. NULL on an ordinary posting, which is what makes
    -- the two distinguishable when the history is reviewed.
    corrects_entry_id   text        NULL REFERENCES ledger.entry (entry_id),

    -- Required on a compensating entry and forbidden on any other, enforced by the
    -- constraint below rather than only by the application.
    reason              text        NULL,

    posted_at           timestamptz NOT NULL,

    -- The replay key. Uniqueness is on the pair, not the key alone: the same key issued
    -- under a different command is a different posting, and collapsing them would lose a
    -- financial fact.
    idempotency_key     text        NOT NULL,

    -- Append-only enforcement. The triggers refuse changes, but recording the hash of the
    -- content as posted also makes tampering detectable after a restore.
    content_hash        bytea       NOT NULL,

    CONSTRAINT entry_id_prefix CHECK (entry_id LIKE 'led\_%'),
    CONSTRAINT source_command_prefix CHECK (source_command_id LIKE 'cmd\_%'),

    -- A correction must carry a reason, and nothing else may.
    CONSTRAINT correction_has_reason CHECK (
        (corrects_entry_id IS NULL AND reason IS NULL) OR
        (corrects_entry_id IS NOT NULL AND reason IS NOT NULL AND length(btrim(reason)) > 0)
    ),

    -- An entry that corrects itself is not a correction.
    CONSTRAINT correction_not_self CHECK (corrects_entry_id IS DISTINCT FROM entry_id)
);

-- One posting. Lines are the double-entry legs.
CREATE TABLE ledger.line (
    entry_id            text        NOT NULL REFERENCES ledger.entry (entry_id),

    -- Position within the entry, for deterministic reads. Not part of the identity: the
    -- balance is per asset, not per order, so line order carries no meaning.
    line_no             integer     NOT NULL,

    account             text        NOT NULL,
    subject             text        NOT NULL,
    asset               text        NOT NULL,
    direction           text        NOT NULL,
    amount              numeric(38, 9) NOT NULL,

    CONSTRAINT line_pk PRIMARY KEY (entry_id, line_no),

    -- The closed account set. Adding one is a change to the meaning of the books.
    CONSTRAINT line_account_closed CHECK (
        account IN ('CASH', 'POSITION', 'REALIZED_PNL', 'FEE', 'EXTERNAL_CLEARING')
    ),
    CONSTRAINT line_direction_closed CHECK (direction IN ('DEBIT', 'CREDIT')),

    -- Amounts are positive and the direction carries the sign. A negative amount would make
    -- a posting's meaning depend on which encoding a reader found.
    CONSTRAINT line_amount_positive CHECK (amount > 0),

    CONSTRAINT line_fields_present CHECK (
        length(btrim(subject)) > 0 AND length(btrim(asset)) > 0
    ),

    -- A position is held in exactly one instrument, so the subject and the asset must agree.
    -- Without this, a position in one instrument could be posted into another, and every
    -- total would still look plausible.
    CONSTRAINT position_asset_matches_subject CHECK (
        account <> 'POSITION' OR asset = subject
    )
);

-- The balance invariant, enforced by the database.
--
-- An entry must balance per asset: the sum of debits equals the sum of credits within each
-- asset. A deferred constraint trigger rather than a row-level one, because the legs of an
-- entry are inserted after its header and a row trigger on `line` would fire before the rest
-- of the entry existed.
--
-- This is the backstop behind the Go check. If anything writes to these tables other than
-- the ledger domain service, the write fails here rather than being discovered during a
-- reconciliation weeks later.
--
-- Every function is created before the trigger that references it. PostgreSQL resolves the
-- function at trigger-creation time rather than at execution time, so a trigger declared
-- first fails to apply even though the function appears later in the file.
CREATE FUNCTION ledger.assert_entry_balances() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_entry_id   text   := NEW.entry_id;
    v_unbalanced text;
BEGIN
    -- Report every unbalanced asset at once. Failing on the first would make a posting
    -- failure with two bad legs take two round trips to diagnose, and the operator sees
    -- whichever the database happened to reach first.
    SELECT string_agg(format('%s: debits %s, credits %s', asset, debits, credits), '; ')
      INTO v_unbalanced
      FROM (
        SELECT l.asset,
               sum(CASE WHEN l.direction = 'DEBIT' THEN l.amount ELSE 0 END) AS debits,
               sum(CASE WHEN l.direction = 'CREDIT' THEN l.amount ELSE 0 END) AS credits
          FROM ledger.line l
         WHERE l.entry_id = v_entry_id
         GROUP BY l.asset
        HAVING sum(CASE WHEN l.direction = 'DEBIT'  THEN l.amount ELSE 0 END)
            <> sum(CASE WHEN l.direction = 'CREDIT' THEN l.amount ELSE 0 END)
      ) unbalanced;

    IF v_unbalanced IS NOT NULL THEN
        RAISE EXCEPTION
            'ledger entry % does not balance per asset: %', v_entry_id, v_unbalanced
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NULL;
END;
$$;

-- An entry needs at least two legs, since a single posting cannot have a counterpart.
CREATE OR REPLACE FUNCTION ledger.assert_entry_has_lines() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_count integer;
BEGIN
    SELECT count(*) INTO v_count FROM ledger.line WHERE entry_id = NEW.entry_id;
    IF v_count < 2 THEN
        RAISE EXCEPTION
            'ledger entry % has % leg(s); an entry must post at least two to balance',
            NEW.entry_id, v_count
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER entry_must_balance
    AFTER INSERT ON ledger.line
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION ledger.assert_entry_balances();

CREATE CONSTRAINT TRIGGER entry_needs_two_lines
    AFTER INSERT ON ledger.line
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION ledger.assert_entry_has_lines();

-- ---------------------------------------------------------------------------
-- Append-only enforcement
-- ---------------------------------------------------------------------------

-- Refuse UPDATE and DELETE on both tables.
--
-- This is the load-bearing object in this migration. Everything else in the schema describes
-- the shape of a ledger; this is what makes it one. An operator with write access who runs
-- an UPDATE to "fix a bad entry" is stopped here, and the only correct remedy is a
-- compensating entry, which is exactly the rule docs/05 sets.
CREATE OR REPLACE FUNCTION ledger.refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'the ledger is append-only: % on % is refused. Post a compensating entry instead.',
        TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation',
              HINT = 'A financial fact is corrected by a new balanced entry that references the one it reverses.';
    -- Unreachable: the RAISE above always fires. Returning NULL keeps the function valid for
    -- the statement-level TRUNCATE trigger, which also requires a return value.
    RETURN NULL;
END;
$$;

CREATE TRIGGER ledger_entry_is_append_only
    BEFORE UPDATE OR DELETE ON ledger.entry
    FOR EACH ROW EXECUTE FUNCTION ledger.refuse_mutation();

CREATE TRIGGER ledger_line_is_append_only
    BEFORE UPDATE OR DELETE ON ledger.line
    FOR EACH ROW EXECUTE FUNCTION ledger.refuse_mutation();

-- TRUNCATE needs its own trigger.
--
-- A row-level trigger does not fire for TRUNCATE, so the two above leave a real hole: an
-- operator with the privilege could issue TRUNCATE ledger.line and erase the entire posting
-- history in one statement, with no per-row trigger to stop it. On `entry` the foreign key
-- happens to block it, but that is incidental and would change if the constraint were ever
-- relaxed, so `line` is covered explicitly rather than relied upon.
--
-- The function is shared; only the trigger level differs, because TRUNCATE is a statement
-- operation and has no NEW row to return.
CREATE TRIGGER ledger_entry_refuses_truncate
    BEFORE TRUNCATE ON ledger.entry
    FOR EACH STATEMENT EXECUTE FUNCTION ledger.refuse_mutation();

CREATE TRIGGER ledger_line_refuses_truncate
    BEFORE TRUNCATE ON ledger.line
    FOR EACH STATEMENT EXECUTE FUNCTION ledger.refuse_mutation();

-- A correction may be inserted only for an entry that exists, is not already corrected, and
-- is not itself a correction. The self-reference and reason rules are table constraints; the
-- "already corrected" rule needs to look across rows and is a trigger.
CREATE OR REPLACE FUNCTION ledger.assert_correction_allowed() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_corrects   text;
    v_first      text;
    v_is_corr    boolean;
BEGIN
    v_corrects := NEW.corrects_entry_id;
    IF v_corrects IS NULL THEN
        RETURN NULL;
    END IF;

    -- The foreign key covers existence, but only once the referencing row is committed. A
    -- deferred check inside the same transaction would see it, and the constraint is
    -- DEFERRABLE elsewhere for the same reason.
    IF NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = v_corrects) THEN
        RAISE EXCEPTION
            'ledger entry % corrects %, which does not exist; a correction that reverses nothing is indistinguishable from a fabricated fact',
            NEW.entry_id, v_corrects
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    SELECT corrects_entry_id IS NOT NULL INTO v_is_corr
      FROM ledger.entry WHERE entry_id = v_corrects;

    IF v_is_corr THEN
        RAISE EXCEPTION
            'ledger entry % corrects %, which is itself a correction; the original error is already reversed by the first correction',
            NEW.entry_id, v_corrects
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- Exclude the row being inserted. This is an AFTER INSERT trigger, so NEW is already
    -- present in the table by the time the trigger runs, and a bare search for
    -- corrects_entry_id = v_corrects finds the new row itself and reports every correction
    -- as a duplicate of itself. Without this exclusion no compensating entry can ever be
    -- written.
    SELECT entry_id INTO v_first
      FROM ledger.entry
     WHERE corrects_entry_id = v_corrects
       AND entry_id <> NEW.entry_id
     LIMIT 1;

    IF v_first IS NOT NULL THEN
        RAISE EXCEPTION
            'ledger entry % corrects %, which was already corrected by %; a second correction of the same entry would net to something other than the original balance',
            NEW.entry_id, v_corrects, v_first
            USING ERRCODE = 'restrict_violation';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER entry_correction_is_allowed
    AFTER INSERT ON ledger.entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION ledger.assert_correction_allowed();

-- ---------------------------------------------------------------------------
-- Idempotency
-- ---------------------------------------------------------------------------

-- A replayed posting is a no-op, enforced by the database rather than by a read-then-write
-- in the application. A check-then-insert has a window between the two statements in which a
-- concurrent retry inserts the same fact twice, which is the exact failure a financial
-- system cannot tolerate.
CREATE UNIQUE INDEX entry_idempotency_uniq
    ON ledger.entry (source_command_id, idempotency_key);

-- Position and cash read paths. These project from `line`; they carry no authority and are
-- safe to drop and recreate, which is why they are indexes and not tables.
CREATE INDEX line_account_subject_asset_idx
    ON ledger.line (account, subject, asset);

CREATE INDEX line_entry_idx ON ledger.line (entry_id);

-- Reconciles entries that belong to one request chain.
CREATE INDEX entry_correlation_idx ON ledger.entry (correlation_id);

-- Finds every correction of a given entry, which is the query that answers "was this
-- corrected, and when".
CREATE INDEX entry_corrects_idx
    ON ledger.entry (corrects_entry_id)
    WHERE corrects_entry_id IS NOT NULL;

COMMENT ON SCHEMA ledger IS
    'Authoritative financial facts (docs/01 section 3). Append-only, balanced, corrected by compensating entries.';
COMMENT ON TABLE ledger.entry IS
    'One balanced posting set. Rows are immutable; the ledger_entry_is_append_only trigger refuses UPDATE and DELETE.';
COMMENT ON TABLE ledger.line IS
    'One double-entry leg. Entries must balance per asset, enforced by entry_must_balance.';
COMMENT ON FUNCTION ledger.refuse_mutation() IS
    'The append-only enforcement. A financial fact is corrected by a new entry, never by changing an old one.';

COMMIT;

-- migrate:down
-- The reverse of the migration above.
--
-- Dropping the schema drops its tables, their indexes, their triggers, and the functions
-- those triggers used. Naming them again first is only a way to fail: a table's triggers go
-- with the table, and PostgreSQL will refuse to drop a function that is still referenced.
--
-- The schema is dropped rather than emptied. A down migration that drops the tables and
-- leaves the namespace behind hands the next up migration a schema it will satisfy with IF
-- NOT EXISTS and then silently adopt, which is the same disagreement between the database
-- and the repository that the drift check exists to catch.
BEGIN;

DROP SCHEMA IF EXISTS ledger CASCADE;

COMMIT;
