-- Verification for 0001_ledger.sql.
--
-- The Go tests prove the domain rules. These prove that the *database* enforces them, which
-- is the point of the migration: a ledger whose append-only property is only a Go convention
-- is one SQL statement away from being a table.
--
-- How to read the output. The write attempts below are expected to fail, and psql reports
-- those failures on stderr while the results come back on stdout, so the two interleave in
-- whatever order the terminal happens to flush them. Markers interleaved with the errors
-- therefore prove nothing on their own.
--
-- Instead, every guard is verified by inspecting the database afterwards. The final block
-- computes a PASS or FAIL per invariant from what actually persisted, which cannot be
-- confused by output ordering: a guard that did not fire leaves a row behind, and the
-- assertion catches it.
--
-- Run it against a freshly migrated database:
--   psql -c 'DROP SCHEMA IF EXISTS ledger CASCADE'
--   psql -v ON_ERROR_STOP=1 < db/migrations/0001_ledger.sql
--   psql                      < db/tests/0001_ledger_verify.sql

\set ON_ERROR_STOP off
\pset tuples_only on
\pset format unaligned

\echo ''
\echo '### ATTEMPTING WRITES THAT MUST BE REFUSED ###'

-- A. An unbalanced entry: debits 100, credits 90.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash)
VALUES ('led_01jq7x5a000000000000000010', 'cmd_01jq7x5a000000000000000011',
        'cmd_01jq7x5a000000000000000011', now(), 'bad-1', decode('ab','hex'));
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000010', 1, 'CASH', 'PORT-A', 'USD', 'DEBIT', 100),
       ('led_01jq7x5a000000000000000010', 2, 'EXTERNAL_CLEARING', 'VENUE-X', 'USD', 'CREDIT', 90);
COMMIT;

-- B. A one-leg entry: cannot balance because it has no counterpart.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash)
VALUES ('led_01jq7x5a000000000000000020', 'cmd_01jq7x5a000000000000000021',
        'cmd_01jq7x5a000000000000000021', now(), 'bad-2', decode('ab','hex'));
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000020', 1, 'CASH', 'PORT-A', 'USD', 'DEBIT', 100);
COMMIT;

-- C. A negative amount: the direction carries the sign, so the amount must be positive.
BEGIN;
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000001', 5, 'FEE', 'VENUE-X', 'USD', 'DEBIT', -5);
COMMIT;

-- D. An account outside the closed set.
BEGIN;
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000001', 5, 'SLUSH_FUND', 'VENUE-X', 'USD', 'DEBIT', 5);
COMMIT;

-- E. A position whose subject and asset disagree.
BEGIN;
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000001', 5, 'POSITION', 'ETH-USD', 'BTC-USD', 'DEBIT', 5);
COMMIT;

-- F. An in-place correction: a reason on something that is not a correction.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash, reason)
VALUES ('led_01jq7x5a000000000000000050', 'cmd_01jq7x5a000000000000000051',
        'cmd_01jq7x5a000000000000000051', now(), 'x-1', decode('ef','hex'),
        'looks like a correction');
COMMIT;

-- G. A correction with no reason.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash, corrects_entry_id)
VALUES ('led_01jq7x5a000000000000000040', 'cmd_01jq7x5a000000000000000041',
        'cmd_01jq7x5a000000000000000041', now(), 'corr-1', decode('ef','hex'),
        'led_01jq7x5a000000000000000001');
COMMIT;

-- H. An entry identity from another domain.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash)
VALUES ('ord_01jq7x5a000000000000000001', 'cmd_01jq7x5a000000000000000002',
        'cmd_01jq7x5a000000000000000002', now(), 'wrong-domain', decode('ab','hex'));
COMMIT;

\echo ''
\echo '### WRITES THAT MUST SUCCEED ###'

-- I. A balanced buy, which is the shape the Go translation produces.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash)
VALUES ('led_01jq7x5a000000000000000001', 'cmd_01jq7x5a000000000000000002',
        'cmd_01jq7x5a000000000000000002', now(), 'buy-1', decode('ab','hex'));
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000001', 1, 'POSITION', 'BTC-USD', 'BTC-USD', 'DEBIT', 2),
       ('led_01jq7x5a000000000000000001', 2, 'EXTERNAL_CLEARING', 'VENUE-X', 'BTC-USD', 'CREDIT', 2),
       ('led_01jq7x5a000000000000000001', 3, 'CASH', 'PORT-A', 'USD', 'CREDIT', 60000),
       ('led_01jq7x5a000000000000000001', 4, 'EXTERNAL_CLEARING', 'VENUE-X', 'USD', 'DEBIT', 60000);
COMMIT;

-- J. The same idempotency key under a *different* command: a different posting, not a replay.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash)
VALUES ('led_01jq7x5a000000000000000031', 'cmd_01jq7x5a000000000000000032',
        'cmd_01jq7x5a000000000000000032', now(), 'buy-1', decode('cd','hex'));
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000031', 1, 'CASH', 'PORT-A', 'USD', 'DEBIT', 7),
       ('led_01jq7x5a000000000000000031', 2, 'EXTERNAL_CLEARING', 'VENUE-X', 'USD', 'CREDIT', 7);
COMMIT;

-- K. A valid compensating entry: the same lines with every direction flipped.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash, corrects_entry_id, reason)
VALUES ('led_01jq7x5a000000000000000070', 'cmd_01jq7x5a000000000000000071',
        'cmd_01jq7x5a000000000000000071', now(), 'corr-3', decode('ef','hex'),
        'led_01jq7x5a000000000000000001', 'the venue never reported this execution');
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ('led_01jq7x5a000000000000000070', 1, 'POSITION', 'BTC-USD', 'BTC-USD', 'CREDIT', 2),
       ('led_01jq7x5a000000000000000070', 2, 'EXTERNAL_CLEARING', 'VENUE-X', 'BTC-USD', 'DEBIT', 2),
       ('led_01jq7x5a000000000000000070', 3, 'CASH', 'PORT-A', 'USD', 'DEBIT', 60000),
       ('led_01jq7x5a000000000000000070', 4, 'EXTERNAL_CLEARING', 'VENUE-X', 'USD', 'CREDIT', 60000);
COMMIT;

\echo ''
\echo '### MUTATIONS THAT MUST BE REFUSED ###'
UPDATE ledger.entry SET reason = 'quietly changed' WHERE entry_id = 'led_01jq7x5a000000000000000001';
DELETE FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000001';
UPDATE ledger.line SET amount = 999 WHERE entry_id = 'led_01jq7x5a000000000000000001' AND line_no = 1;
DELETE FROM ledger.line WHERE entry_id = 'led_01jq7x5a000000000000000001';
-- TRUNCATE on the child table is the case a row-level trigger cannot catch.
TRUNCATE ledger.line;
TRUNCATE ledger.entry CASCADE;

\echo ''
\echo '### WRITES THAT MUST BE REFUSED, PHASE 2 ###'

-- L. A second correction of the same entry.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash, corrects_entry_id, reason)
VALUES ('led_01jq7x5a000000000000000080', 'cmd_01jq7x5a000000000000000081',
        'cmd_01jq7x5a000000000000000081', now(), 'corr-4', decode('ef','hex'),
        'led_01jq7x5a000000000000000001', 'correcting it twice');
COMMIT;

-- M. A correction of a correction.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash, corrects_entry_id, reason)
VALUES ('led_01jq7x5a000000000000000090', 'cmd_01jq7x5a000000000000000091',
        'cmd_01jq7x5a000000000000000091', now(), 'corr-5', decode('ef','hex'),
        'led_01jq7x5a000000000000000070', 'correcting the correction');
COMMIT;

-- N. A correction of an entry that does not exist.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash, corrects_entry_id, reason)
VALUES ('led_01jq7x5a000000000000000060', 'cmd_01jq7x5a000000000000000061',
        'cmd_01jq7x5a000000000000000061', now(), 'corr-2', decode('ef','hex'),
        'led_01jq7x5a000000000000000099', 'correcting nothing');
COMMIT;

-- O. A replay of the original posting under the same command and key.
BEGIN;
INSERT INTO ledger.entry (entry_id, source_command_id, correlation_id, posted_at,
                          idempotency_key, content_hash)
VALUES ('led_01jq7x5a000000000000000030', 'cmd_01jq7x5a000000000000000002',
        'cmd_01jq7x5a000000000000000002', now(), 'buy-1', decode('ab','hex'));
COMMIT;

\echo ''
\echo '### ASSERTIONS (these are the actual result) ###'

WITH assertions(name, passed, detail) AS (
    -- Every refused write left nothing behind.
    SELECT 'unbalanced entry was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000010'),
           'entry 010 must not exist'
    UNION ALL
    SELECT 'one-leg entry was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000020'),
           'entry 020 must not exist'
    UNION ALL
    SELECT 'negative amount was refused',
           NOT EXISTS (SELECT 1 FROM ledger.line WHERE amount < 0),
           'no negative amount may persist'
    UNION ALL
    SELECT 'unclosed account was refused',
           NOT EXISTS (SELECT 1 FROM ledger.line WHERE account = 'SLUSH_FUND'),
           'no undeclared account may persist'
    UNION ALL
    SELECT 'position asset/subject mismatch was refused',
           NOT EXISTS (SELECT 1 FROM ledger.line WHERE account = 'POSITION' AND asset <> subject),
           'a position is held in one instrument'
    UNION ALL
    SELECT 'reason on a non-correction was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'led_01jq7x5a000000000000000050'),
           'entry 050 must not exist'
    UNION ALL
    SELECT 'correction with no reason was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'led_01jq7x5a000000000000000040'),
           'entry 040 must not exist'
    UNION ALL
    SELECT 'foreign entry identity was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'ord_01jq7x5a000000000000000001'),
           'an order identity may not be a ledger entry'
    UNION ALL
    SELECT 'second correction was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'led_01jq7x5a000000000000000080'),
           'entry 080 must not exist'
    UNION ALL
    SELECT 'correction of a correction was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'led_01jq7x5a000000000000000090'),
           'entry 090 must not exist'
    UNION ALL
    SELECT 'correction of a missing entry was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'led_01jq7x5a000000000000000060'),
           'entry 060 must not exist'
    UNION ALL
    SELECT 'replayed posting was refused',
           NOT EXISTS (SELECT 1 FROM ledger.entry
                       WHERE entry_id = 'led_01jq7x5a000000000000000030'),
           'entry 030 must not exist'
    UNION ALL
    -- The three writes that had to succeed did, and no others.
    SELECT 'exactly the three valid entries persisted',
           (SELECT count(*) FROM ledger.entry) = 3,
           'found ' || (SELECT count(*) FROM ledger.entry) || ', want 3'
    UNION ALL
    SELECT 'exactly ten lines persisted',
           (SELECT count(*) FROM ledger.line) = 10,
           'found ' || (SELECT count(*) FROM ledger.line) || ', want 10'
    UNION ALL
    SELECT 'the same key under a different command is a different posting',
           EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000031'),
           'idempotency is keyed on the command as well as the key'
    UNION ALL
    -- The corrected position folds back to flat, which is what the whole correction path is for.
    SELECT 'the corrected position is flat',
           COALESCE((SELECT sum(CASE WHEN direction = 'DEBIT' THEN amount ELSE -amount END)
                       FROM ledger.line
                      WHERE account = 'POSITION' AND subject = 'BTC-USD'), 0) = 0,
           'position should net to zero after the correction'
    UNION ALL
    -- And the surviving entry is unchanged: an UPDATE was attempted above.
    SELECT 'the original entry was not modified in place',
           EXISTS (SELECT 1 FROM ledger.entry e
                    WHERE e.entry_id = 'led_01jq7x5a000000000000000001'
                      AND e.reason IS NULL)
           AND EXISTS (SELECT 1 FROM ledger.line l
                        WHERE l.entry_id = 'led_01jq7x5a000000000000000001'
                          AND l.line_no = 1 AND l.amount = 2),
           'UPDATE and DELETE must both have been refused'
    UNION ALL
    -- Every persisted entry balances per asset, checked across the whole history.
    SELECT 'every persisted entry balances per asset',
           NOT EXISTS (
               SELECT 1 FROM ledger.line l
                GROUP BY l.entry_id, l.asset
               HAVING sum(CASE WHEN l.direction = 'DEBIT' THEN l.amount ELSE 0 END)
                   <> sum(CASE WHEN l.direction = 'CREDIT' THEN l.amount ELSE 0 END)),
           'debits must equal credits within each asset'
)
SELECT CASE WHEN passed THEN 'PASS' ELSE 'FAIL' END || '  ' || name || '  (' || detail || ')'
  FROM assertions
 ORDER BY passed DESC, name;

\echo ''
WITH totals AS (
    SELECT count(*) FILTER (WHERE NOT passed) AS failed,
           count(*)                            AS total
      FROM (
        SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000010') AS passed
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000020')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.line WHERE amount < 0)
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.line WHERE account = 'SLUSH_FUND')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.line WHERE account = 'POSITION' AND asset <> subject)
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000050')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000040')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'ord_01jq7x5a000000000000000001')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000080')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000090')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000060')
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000030')
        UNION ALL SELECT (SELECT count(*) FROM ledger.entry) = 3
        UNION ALL SELECT (SELECT count(*) FROM ledger.line) = 10
        UNION ALL SELECT EXISTS (SELECT 1 FROM ledger.entry WHERE entry_id = 'led_01jq7x5a000000000000000031')
        UNION ALL SELECT COALESCE((SELECT sum(CASE WHEN direction = 'DEBIT' THEN amount ELSE -amount END)
                                     FROM ledger.line WHERE account = 'POSITION' AND subject = 'BTC-USD'), 0) = 0
        UNION ALL SELECT EXISTS (SELECT 1 FROM ledger.entry e
                                  WHERE e.entry_id = 'led_01jq7x5a000000000000000001' AND e.reason IS NULL)
                 AND EXISTS (SELECT 1 FROM ledger.line l
                              WHERE l.entry_id = 'led_01jq7x5a000000000000000001'
                                AND l.line_no = 1 AND l.amount = 2)
        UNION ALL SELECT NOT EXISTS (SELECT 1 FROM ledger.line l
                                      GROUP BY l.entry_id, l.asset
                                     HAVING sum(CASE WHEN l.direction = 'DEBIT' THEN l.amount ELSE 0 END)
                                         <> sum(CASE WHEN l.direction = 'CREDIT' THEN l.amount ELSE 0 END))
      ) a
)
SELECT CASE WHEN failed = 0 THEN 'ALL ' || total || ' ASSERTIONS PASSED'
            ELSE failed || ' OF ' || total || ' ASSERTIONS FAILED' END
  FROM totals;
