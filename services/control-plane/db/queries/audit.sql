-- name: AppendAuditRecord :one
--
-- The append-only evidence write.
--
-- There is no ON CONFLICT clause here, deliberately. A duplicate audit_id is a genuine
-- conflict between two different facts, and silently returning the existing row would make
-- the second write disappear while the caller believed it was recorded. The ledger is
-- idempotent because a repeat is a retry; an audit record is idempotent because a repeat is
-- a contradiction, and those are different situations that happen to look alike.
INSERT INTO audit_records (
    audit_id,
    partition,
    sequence,
    actor_id,
    actor_type,
    action,
    target_type,
    target_id,
    environment,
    market_scope,
    occurred_at_utc,
    recorded_at_utc,
    reason,
    correlation_id,
    causation_id,
    policy_version,
    result,
    before_digest,
    after_digest,
    previous_hash,
    record_hash,
    signing_key_id,
    schema_version
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
    $15, $16, $17, $18, $19, $20, $21, $22, $23
)
RETURNING *;

-- name: GetAuditRecord :one
SELECT * FROM audit_records WHERE audit_id = $1;

-- name: GetNextAuditSequence :one
--
-- The next sequence number for a partition.
--
-- Computed as max + 1 rather than read from a counter table so that the number is always
-- derived from the chain that actually exists. A counter table can disagree with the records
-- after a restore, and a gap detected only at verification time is a gap that has already
-- been written to.
SELECT coalesce(max(r.sequence), 0)::bigint + 1 AS next_sequence
FROM audit_records r
WHERE r.partition = $1;

-- name: GetLastAuditRecordInPartition :one
SELECT * FROM audit_records
WHERE partition = $1
ORDER BY sequence DESC
LIMIT 1;

-- name: ListAuditRecordsByCorrelation :many
SELECT * FROM audit_records
WHERE correlation_id = $1 AND correlation_id <> ''
ORDER BY recorded_at_utc, partition, sequence;

-- name: ListAuditRecordsForActor :many
--
-- Bounded on purpose. An unbounded actor history is a table scan over the evidence that has
-- to survive for seven years, and the callers that need it are investigations rather than
-- request handlers.
SELECT * FROM audit_records
WHERE actor_id = $1
ORDER BY recorded_at_utc DESC
LIMIT $2;

-- name: ListAuditRecordsInPartitionRange :many
SELECT * FROM audit_records
WHERE partition = $1
  AND sequence >= $2
  AND sequence <= $3
ORDER BY sequence;

-- name: AppendAuditCheckpoint :one
INSERT INTO audit_checkpoints (
    partition,
    first_sequence,
    last_sequence,
    first_hash,
    last_hash,
    record_count,
    created_at_utc,
    signing_key_id,
    signature,
    schema_version
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING *;

-- name: GetLatestAuditCheckpoint :one
SELECT * FROM audit_checkpoints
WHERE partition = $1
ORDER BY last_sequence DESC
LIMIT 1;

-- name: ListAuditDeletionEvents :many
--
-- The retained record of a deletion. Deleting evidence is permitted under a two-person
-- approval after expiry, and the fact that it happened is itself kept, so this table is
-- append-only in the same way the evidence it describes is.
SELECT * FROM audit_deletion_events
ORDER BY deleted_at_utc DESC
LIMIT $1;

-- name: InsertAuditDeletionEvent :one
INSERT INTO audit_deletion_events (
    audit_id,
    partition,
    first_sequence,
    last_sequence,
    requested_by,
    approved_by,
    deleted_at_utc
) VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING *;
