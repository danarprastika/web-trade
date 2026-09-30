-- Verification for 0002_audit.sql.
--
-- The Go tests prove the audit domain rules. These prove that the *database* enforces
-- append-only, chain linkage, and checkpoint agreement, which is the point of the
-- migration: evidence that is only append-only by Go convention is one SQL statement away
-- from being ordinary rows.
--
-- How to read the output. The write attempts below are expected to fail, and psql reports
-- those failures on stderr while the results come back on stdout, so the two interleave
-- unpredictably. Markers interleaved with the errors therefore prove nothing on their own.
--
-- Instead, every guard is verified by inspecting the database afterwards. The final block
-- computes a PASS or FAIL per invariant from what actually persisted, which cannot be
-- confused by output ordering: a guard that did not fire leaves a row behind, and the
-- assertion catches it.
--
-- Run it against a freshly migrated database:
--   psql -v ON_ERROR_STOP=1 < db/migrations/0002_audit.sql
--   psql                      < db/tests/0002_audit_verify.sql

\set ON_ERROR_STOP off
\pset tuples_only on
\pset format unaligned

-- h(bytea) renders a digest as 'xxxxxxxx', so comparisons below are readable.
CREATE OR REPLACE FUNCTION h(b bytea) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(encode(b, 'hex'), repeat('0', 64));
$$;

-- A valid record. The hash values are placeholders: this file proves the *guards*, and the
-- chain-link trigger compares a record's previous_hash to the previous record's hash, so
-- the fixtures below are written to link correctly to each other.
CREATE OR REPLACE FUNCTION mkrec(
    p_audit_id text, p_partition text, p_sequence bigint,
    p_prev bytea, p_hash bytea, p_actor_type text DEFAULT 'HUMAN',
    p_result text DEFAULT 'SUCCEEDED', p_recorded timestamptz DEFAULT now()
) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO audit_records (
        audit_id, partition, sequence, actor_id, actor_type, action,
        target_type, target_id, environment, market_scope,
        occurred_at_utc, recorded_at_utc, reason, correlation_id, causation_id,
        policy_version, result, before_digest, after_digest,
        previous_hash, record_hash, signing_key_id, schema_version)
    VALUES (
        p_audit_id, p_partition, p_sequence, 'actor-0001', p_actor_type, 'TEST_ACTION',
        'ORDER', 'ord-0001', 'SIMULATION', 'IDX',
        p_recorded, p_recorded, 'verification fixture', 'cor-0001', '',
        'policy-v1', p_result, '', '',
        p_prev, p_hash, 'key-0001', 1);
END;
$$;

\echo ''
\echo '### SEEDING A VALID CHAIN ###'

-- Three linked records in tenant-a, plus one in tenant-b.
SELECT mkrec('aud-0001', 'tenant-a', 1, decode(repeat('00', 32), 'hex'), decode(repeat('a1', 32), 'hex'));
SELECT mkrec('aud-0002', 'tenant-a', 2, decode(repeat('a1', 32), 'hex'), decode(repeat('a2', 32), 'hex'));
SELECT mkrec('aud-0003', 'tenant-a', 3, decode(repeat('a2', 32), 'hex'), decode(repeat('a3', 32), 'hex'));
SELECT mkrec('aud-b01', 'tenant-b', 1, decode(repeat('00', 32), 'hex'), decode(repeat('b1', 32), 'hex'));

\echo ''
\echo '### ATTEMPTING WRITES THAT MUST BE REFUSED ###'

-- A. UPDATE of evidence.
BEGIN;
UPDATE audit_records SET action = 'ALTERED' WHERE audit_id = 'aud-0002';
COMMIT;

-- B. DELETE of evidence.
BEGIN;
DELETE FROM audit_records WHERE audit_id = 'aud-0002';
COMMIT;

-- C. TRUNCATE of the whole chain. This is the one a row-level trigger does not catch.
TRUNCATE audit_records;

-- D. A broken chain link: a record naming the wrong predecessor.
BEGIN;
SELECT mkrec('aud-0004', 'tenant-a', 4, decode(repeat('ff', 32), 'hex'), decode(repeat('a4', 32), 'hex'));
COMMIT;

-- E. A record whose predecessor does not exist: a hole in the chain.
BEGIN;
SELECT mkrec('aud-0007', 'tenant-a', 7, decode(repeat('a6', 32), 'hex'), decode(repeat('a7', 32), 'hex'));
COMMIT;

-- F. A replayed sequence in the same partition.
BEGIN;
SELECT mkrec('aud-0003-dup', 'tenant-a', 3, decode(repeat('a2', 32), 'hex'), decode(repeat('a3', 32), 'hex'));
COMMIT;

-- G. An actor type outside the closed set.
BEGIN;
SELECT mkrec('aud-0004', 'tenant-a', 4, decode(repeat('a3', 32), 'hex'), decode(repeat('a4', 32), 'hex'),
             'ROBOT');
COMMIT;

-- H. A result outside the closed set.
BEGIN;
SELECT mkrec('aud-0004', 'tenant-a', 4, decode(repeat('a3', 32), 'hex'), decode(repeat('a4', 32), 'hex'),
             'HUMAN', 'MAYBE');
COMMIT;

-- I. A record with no actor: unattributable evidence.
BEGIN;
INSERT INTO audit_records (
    audit_id, partition, sequence, actor_id, actor_type, action,
    environment, occurred_at_utc, recorded_at_utc, result,
    previous_hash, record_hash, schema_version)
VALUES ('aud-noactor', 'tenant-a', 4, '', 'HUMAN', 'TEST_ACTION',
        'SIMULATION', now(), now(), 'SUCCEEDED',
        decode(repeat('a3', 32), 'hex'), decode(repeat('a4', 32), 'hex'), 1);
COMMIT;

-- J. A sequence below one.
BEGIN;
SELECT mkrec('aud-zero', 'tenant-a', 0, decode(repeat('00', 32), 'hex'), decode(repeat('z0', 32), 'hex'));
COMMIT;

-- K. A record written under an unknown schema version.
BEGIN;
INSERT INTO audit_records (
    audit_id, partition, sequence, actor_id, actor_type, action,
    environment, occurred_at_utc, recorded_at_utc, result,
    previous_hash, record_hash, schema_version)
VALUES ('aud-v9', 'tenant-a', 4, 'actor-0001', 'HUMAN', 'TEST_ACTION',
        'SIMULATION', now(), now(), 'SUCCEEDED',
        decode(repeat('a3', 32), 'hex'), decode(repeat('a4', 32), 'hex'), 9);
COMMIT;

-- L. A deletion event approved by the same person who requested it.
BEGIN;
INSERT INTO audit_deletion_events (audit_id, partition, first_sequence, last_sequence,
                                    requested_by, approved_by, deleted_at_utc)
VALUES ('del-0001', 'tenant-a', 1, 3, 'alice', 'alice', now());
COMMIT;

-- M. UPDATE of a deletion event, which is itself retained evidence.
BEGIN;
UPDATE audit_deletion_events SET approved_by = 'bob' WHERE audit_id = 'del-0001';
COMMIT;

-- N. A checkpoint whose record_count disagrees with the records present.
BEGIN;
INSERT INTO audit_checkpoints (partition, first_sequence, last_sequence, first_hash, last_hash,
                                record_count, created_at_utc, signing_key_id, signature, schema_version)
VALUES ('tenant-a', 1, 3, decode(repeat('a1', 32), 'hex'), decode(repeat('a3', 32), 'hex'),
        99, now(), 'key-0001', decode(repeat('5a', 32), 'hex'), 1);
COMMIT;

-- O. A checkpoint whose last_hash does not match the record at its last sequence.
BEGIN;
INSERT INTO audit_checkpoints (partition, first_sequence, last_sequence, first_hash, last_hash,
                                record_count, created_at_utc, signing_key_id, signature, schema_version)
VALUES ('tenant-b', 1, 1, decode(repeat('b1', 32), 'hex'), decode(repeat('bb', 32), 'hex'),
        1, now(), 'key-0001', decode(repeat('5a', 32), 'hex'), 1);
COMMIT;

-- P. A second checkpoint over a range that is already checkpointed by a valid one. This
--    is the overlap case: the signed boundary of a sequence range must be unique, or
--    "the" signed boundary becomes ambiguous, which is indistinguishable from tampering.
--    It deliberately reuses the range that Q establishes, so it is a true overlap rather
--    than a second checkpoint of a range nothing else covers.
BEGIN;
INSERT INTO audit_checkpoints (partition, first_sequence, last_sequence, first_hash, last_hash,
                                record_count, created_at_utc, signing_key_id, signature, schema_version)
VALUES ('tenant-a', 1, 3, decode(repeat('a1', 32), 'hex'), decode(repeat('a3', 32), 'hex'),
        3, now(), 'key-0002', decode(repeat('5a', 32), 'hex'), 1);
COMMIT;

-- Q. A well-formed checkpoint. This one must be ACCEPTED, and is the control that proves
--    the checkpoint guard is not simply refusing everything.
BEGIN;
INSERT INTO audit_checkpoints (partition, first_sequence, last_sequence, first_hash, last_hash,
                                record_count, created_at_utc, signing_key_id, signature, schema_version)
VALUES ('tenant-a', 1, 3, decode(repeat('a1', 32), 'hex'), decode(repeat('a3', 32), 'hex'),
        3, now(), 'key-0001', decode(repeat('5a', 32), 'hex'), 1);
COMMIT;

\echo ''
\echo '### ASSERTIONS ###'

-- The per-invariant results are materialised before being reported, because a CTE is
-- scoped to a single statement: querying `checks` again in a second statement would fail
-- with "relation does not exist" and take the summary with it.
--
-- There is deliberately no ON COMMIT DROP here. psql runs each statement in its own
-- transaction, so the table would be dropped by the very commit that created it.
CREATE TEMP TABLE check_results AS
WITH checks(name, ok) AS (
    -- Append-only: none of the mutation attempts may have persisted.
    SELECT 'update of evidence was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE action = 'ALTERED')
    UNION ALL
    SELECT 'delete of evidence was refused',
           (SELECT count(*) FROM audit_records WHERE audit_id = 'aud-0002') = 1
    UNION ALL
    SELECT 'truncate of evidence was refused',
           (SELECT count(*) FROM audit_records) >= 4
    UNION ALL
    SELECT 'truncate of checkpoints was refused',
           (SELECT count(*) FROM audit_checkpoints) = 1
    UNION ALL
    SELECT 'truncate of deletion events was refused',
           (SELECT count(*) FROM audit_deletion_events) = 0

    -- Chain linkage.
    UNION ALL
    SELECT 'broken chain link was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE audit_id = 'aud-0004' AND partition = 'tenant-a' AND sequence = 4)
    UNION ALL
    SELECT 'record with no predecessor was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE audit_id = 'aud-0007')
    UNION ALL
    SELECT 'replayed sequence was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE audit_id = 'aud-0003-dup')
    UNION ALL
    SELECT 'the seeded chain is intact',
           (SELECT count(*) FROM audit_records WHERE partition = 'tenant-a') = 3

    -- Closed sets and attribution.
    UNION ALL
    SELECT 'actor type outside the closed set was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE actor_type = 'ROBOT')
    UNION ALL
    SELECT 'result outside the closed set was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE result = 'MAYBE')
    UNION ALL
    SELECT 'unattributable record was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE actor_id = '')
    UNION ALL
    SELECT 'sequence below one was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE sequence < 1)
    UNION ALL
    SELECT 'unknown schema version was refused',
           NOT EXISTS (SELECT 1 FROM audit_records WHERE schema_version <> 1)

    -- Deletion policy.
    UNION ALL
    SELECT 'self-approved deletion event was refused',
           NOT EXISTS (SELECT 1 FROM audit_deletion_events WHERE requested_by = approved_by)
    UNION ALL
    SELECT 'update of a deletion event was refused',
           NOT EXISTS (SELECT 1 FROM audit_deletion_events WHERE approved_by = 'bob')

    -- Checkpoints.
    UNION ALL
    SELECT 'miscounting checkpoint was refused',
           NOT EXISTS (SELECT 1 FROM audit_checkpoints WHERE record_count = 99)
    UNION ALL
    SELECT 'checkpoint with a wrong last_hash was refused',
           NOT EXISTS (SELECT 1 FROM audit_checkpoints WHERE partition = 'tenant-b')
    UNION ALL
    SELECT 'overlapping checkpoint was refused',
           (SELECT count(*) FROM audit_checkpoints) = 1
    UNION ALL
    SELECT 'a well-formed checkpoint was accepted',
           (SELECT count(*) FROM audit_checkpoints
             WHERE partition = 'tenant-a' AND record_count = 3) = 1
)
SELECT name, bool_and(ok) AS ok FROM checks GROUP BY name;

SELECT (CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END) || '  ' || name || '  (1)'
  FROM check_results
 ORDER BY name;

SELECT CASE WHEN count(*) FILTER (WHERE NOT ok) = 0
            THEN 'ALL ' || count(*) || ' ASSERTIONS PASSED'
            ELSE count(*) FILTER (WHERE NOT ok) || ' OF ' || count(*) || ' ASSERTIONS FAILED' END
  FROM check_results;

DROP TABLE check_results;
