-- name: AppendEntry :one
--
-- The entry header for one posting set.
--
-- Idempotent rather than erroring on a repeat, because a retried command must not create a
-- second financial fact.
--
-- The conflict target is the PAIR (source_command_id, idempotency_key), because that is what
-- the unique index covers: entry_idempotency_uniq is on the pair, not on the key alone, since
-- the same key issued under a different command is a different posting and collapsing them
-- would lose a financial fact. Writing ON CONFLICT (idempotency_key) looks equivalent and is
-- not -- it has no matching unique index, so the statement fails at runtime with "there is no
-- unique or exclusion constraint matching the ON CONFLICT specification". Neither sqlc nor
-- sqlc vet catches that, which is why scripts/rehearse_migrations.py executes every query
-- against the real schema.
INSERT INTO ledger.entry (
    entry_id,
    source_command_id,
    correlation_id,
    corrects_entry_id,
    reason,
    posted_at,
    idempotency_key,
    content_hash
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (source_command_id, idempotency_key) DO UPDATE
    SET idempotency_key = ledger.entry.idempotency_key
RETURNING *;

-- name: GetEntry :one
SELECT * FROM ledger.entry WHERE entry_id = $1;

-- name: GetEntryByIdempotencyKey :one
--
-- Takes both halves of the pair for the same reason AppendEntry does. Looking up by the key
-- alone would return an arbitrary posting among every command that reused the key, which is
-- exactly the ambiguity the unique index exists to prevent.
SELECT * FROM ledger.entry
WHERE source_command_id = $1 AND idempotency_key = $2;

-- name: InsertLine :exec
--
-- The caller inserts the header and then its legs. There is no single statement that writes
-- both, because the balance trigger is deferred to the end of the transaction: a set that
-- does not balance is refused at COMMIT rather than half-written. That deferral is the point,
-- so the legs are written by a separate statement rather than a CTE.
INSERT INTO ledger.line (entry_id, line_no, account, subject, asset, direction, amount)
VALUES ($1, $2, $3, $4, $5, $6, $7);

-- name: ListLinesForEntry :many
SELECT * FROM ledger.line WHERE entry_id = $1 ORDER BY line_no;

-- name: CheckEntryBalances :one
--
-- The per-asset balance check, computed rather than read.
--
-- This is the query the reconciliation path uses to decide whether a posting set is a valid
-- correction or a defect. The constraint makes the database refuse an unbalanced entry; this
-- makes the application able to explain one without reproducing the trigger's logic.
SELECT
    l.entry_id,
    l.asset,
    sum(CASE WHEN l.direction = 'DEBIT' THEN l.amount ELSE -l.amount END) AS net_amount,
    count(*)::bigint AS leg_count
FROM ledger.line l
WHERE l.entry_id = $1
GROUP BY l.entry_id, l.asset
ORDER BY l.asset;

-- name: ListEntriesByCorrelation :many
SELECT * FROM ledger.entry
WHERE correlation_id = $1
ORDER BY sequence_no;

-- name: ListCorrectionsForEntry :many
SELECT * FROM ledger.entry
WHERE corrects_entry_id = $1
ORDER BY sequence_no;
