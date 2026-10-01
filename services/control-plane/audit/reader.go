package audit

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// rehydratePageSize bounds one round trip to the database.
//
// A partition's evidence is retained for seven years, so a full read is unbounded by
// construction. This does not make the read cheap, and it cannot - an in-memory Chain holds
// every record it has seen, so rehydrating a partition means holding that partition. The page
// bounds the query's working set rather than the total, which is the part that can be
// controlled without changing what a Chain is.
const rehydratePageSize = 500

// ChainReader is the read side that Sink deliberately is not.
//
// Sink was defined write-only on purpose: a sink that could modify or remove evidence would
// not be a sink. That left the package with no way to load stored evidence back, and the
// consequence was recorded against several work items as "cannot rehydrate after restart".
// This is the missing half. It is a separate interface from Sink on purpose - a reader that
// could write would reintroduce the same problem one interface away - and it is narrower than
// the generated accessors for the same reason.
type ChainReader interface {
	// ReadPartition returns stored records for one partition in ascending sequence order,
	// covering the inclusive range from..to.
	//
	// Order is required rather than incidental. Restore refuses to sort its input, because
	// sorting would make a reordered archive indistinguishable from an intact one, so a
	// reader that returned records out of order would produce an archive that cannot be
	// loaded rather than one that is merely unsorted.
	//
	// This method alone cannot tell a partition that ended from a partition whose tail was
	// deleted, because the two present exactly the same rows. That distinction needs the
	// signed checkpoints, which arrive through ChainAnchorReader below.
	ReadPartition(ctx context.Context, partition string, from, to int64) ([]Record, error)
}

// ChainAnchorReader reads the signed checkpoints that say how far a partition actually went.
//
// It is separate from ChainReader rather than part of it because the anchor is a different
// kind of artifact: records are the evidence, checkpoints are the promise about the evidence
// that was made while it was still all there. Rehydrate uses it when the reader offers it, so
// that a truncated archive fails closed instead of restoring as a shorter - and perfectly
// internally consistent - chain.
type ChainAnchorReader interface {
	// LatestCheckpoint returns the checkpoint covering the highest sequence in a partition,
	// and whether one exists. A partition with no checkpoint is not an error: it is a
	// partition nothing has vouched for yet, which is the ordinary state of a fresh chain.
	LatestCheckpoint(ctx context.Context, partition string) (Checkpoint, bool, error)
}

// SQLChainReaderQuerier is the subset of the generated accessors this reader uses.
//
// It exposes one range read with an explicit upper bound and one point read of a partition's
// latest checkpoint. There is no unfiltered "select all from audit_records" reachable here,
// because an unbounded read over seven years of retained evidence is a table scan and the
// callers that need one are investigations rather than startup paths.
type SQLChainReaderQuerier interface {
	ListAuditRecordsInPartitionRange(ctx context.Context, arg dbgen.ListAuditRecordsInPartitionRangeParams) ([]dbgen.AuditRecord, error)
	GetLatestAuditCheckpoint(ctx context.Context, partition string) (dbgen.AuditCheckpoint, error)
}

// SQLChainReader is a ChainReader over the generated accessors.
//
// It imports database/sql and the generated accessors and nothing else, matching SQLSink, so
// it introduces no driver dependency. That matters for the reason EV-046 records: no pgx v5
// release currently satisfies the repository's pinning gate.
type SQLChainReader struct {
	q SQLChainReaderQuerier
	// close releases the caller's pool. It is nil when the reader did not create one.
	close func() error
}

// NewSQLChainReader returns a reader over db.
//
// It takes a *sql.DB rather than building a pool, for the reason SQLSink does: a pool
// constructed here would be invisible to the caller's shutdown sequence.
func NewSQLChainReader(db *sql.DB) (*SQLChainReader, error) {
	if db == nil {
		return nil, errors.New("a sql-backed audit reader requires a database handle; " +
			"constructing one here would hide the pool from the caller's shutdown sequence")
	}
	return &SQLChainReader{q: dbgen.New(db), close: db.Close}, nil
}

// NewSQLChainReaderInTx returns a reader whose reads join a transaction the caller owns.
func NewSQLChainReaderInTx(q SQLChainReaderQuerier) (*SQLChainReader, error) {
	if q == nil {
		return nil, errors.New("a sql-backed audit reader requires a querier")
	}
	return &SQLChainReader{q: q, close: func() error { return nil }}, nil
}

// Close releases the pool when this reader created one.
func (r *SQLChainReader) Close() error {
	if r.close == nil {
		return nil
	}
	return r.close()
}

// ReadPartition returns one bounded range of one partition.
func (r *SQLChainReader) ReadPartition(ctx context.Context, partition string, from, to int64) ([]Record, error) {
	rows, err := r.q.ListAuditRecordsInPartitionRange(ctx, dbgen.ListAuditRecordsInPartitionRangeParams{
		Partition:  partition,
		Sequence:   from,
		Sequence_2: to,
	})
	if err != nil {
		return nil, fmt.Errorf("reading partition %s sequences %d..%d: %w", partition, from, to, err)
	}
	records := make([]Record, 0, len(rows))
	for _, row := range rows {
		rec, err := recordFrom(row)
		if err != nil {
			return nil, fmt.Errorf("partition %s sequence %d (audit_id %s): %w",
				partition, row.Sequence, row.AuditID, err)
		}
		records = append(records, rec)
	}
	return records, nil
}

// LatestCheckpoint returns the newest signed checkpoint in a partition, if one exists.
//
// This is the anchor the restore needs and it is already durable: audit_checkpoints is
// append-only, its rows are signed, and this is the query the repository already generates
// for it. Nothing here had to be invented to detect a truncated tail, and nothing here needs
// a migration to be able to.
func (r *SQLChainReader) LatestCheckpoint(ctx context.Context, partition string) (Checkpoint, bool, error) {
	row, err := r.q.GetLatestAuditCheckpoint(ctx, partition)
	if errors.Is(err, sql.ErrNoRows) {
		// Nothing has vouched for this partition yet. That is a state, not a failure, and
		// reporting it as one would make a fresh deployment refuse to start.
		return Checkpoint{}, false, nil
	}
	if err != nil {
		return Checkpoint{}, false, fmt.Errorf("reading the latest checkpoint of partition %s: %w", partition, err)
	}
	cp, err := checkpointFrom(row)
	if err != nil {
		return Checkpoint{}, false, fmt.Errorf("partition %s latest checkpoint: %w", partition, err)
	}
	return cp, true, nil
}

// checkpointFrom maps a stored checkpoint row back onto a Checkpoint.
//
// The schema version is compared rather than adopted, for the same reason recordFrom does it:
// checkpointFields hashes the package constant, so a row written under another version cannot
// be re-derived here and would be refused downstream for a reason that looks like tampering.
//
// The partition on the row is carried, not checked, because checking it needs the partition
// that was asked for. Rehydrate does that comparison, since an anchor filed under the wrong
// partition would compare a sequence number against the wrong chain.
func checkpointFrom(row dbgen.AuditCheckpoint) (Checkpoint, error) {
	if row.SchemaVersion != CheckpointSchemaVersion {
		return Checkpoint{}, reject(contracts.CodeValidation,
			"stored checkpoint schema_version is %d but this build writes version %d; the "+
				"checkpoint cannot be re-derived because the version is part of the signed "+
				"payload, not a property of the row", row.SchemaVersion, CheckpointSchemaVersion)
	}
	firstHash, err := hashFrom(row.FirstHash)
	if err != nil {
		return Checkpoint{}, fmt.Errorf("first_hash: %w", err)
	}
	lastHash, err := hashFrom(row.LastHash)
	if err != nil {
		return Checkpoint{}, fmt.Errorf("last_hash: %w", err)
	}
	return Checkpoint{
		Partition:     row.Partition,
		FirstSequence: row.FirstSequence,
		LastSequence:  row.LastSequence,
		FirstHash:     firstHash,
		LastHash:      lastHash,
		Count:         int(row.RecordCount),
		CreatedAt:     TimestampFrom(row.CreatedAtUtc),
		SigningKeyID:  row.SigningKeyID,
		// Copied rather than aliased, for the reason the record hashes are: the row's
		// slice belongs to the driver and an aliased one would mutate under the next scan.
		Signature: append(Signature(nil), row.Signature...),
	}, nil
}

// recordFrom maps a stored row back onto a Record.
//
// This is the exact inverse of paramsFor, and it is written out field by field for the same
// reason: a mapping that silently skipped a field would restore a record whose hash does not
// match its content, which Restore would then refuse as tampering - an accurate diagnosis of
// a defect that is actually a mapping bug. Two conversions carry real risk and are checked
// rather than assumed.
//
// The hashes are copied, not aliased. The row's slices belong to the driver and may be reused
// across rows; a Record holding one of them would appear to mutate when the next scan step
// overwrites the buffer, and a record whose hash changes after it was stored is the exact
// failure this package exists to make impossible.
//
// The schema version is compared rather than adopted. canonicalFields hashes the package
// constant, not a per-record field, so a row written under a different version cannot be
// re-derived here - the content would hash to something the row does not claim. Refusing with
// a specific message is the difference between "this archive is damaged" and "this archive was
// written by a version of this software that no longer exists here".
func recordFrom(row dbgen.AuditRecord) (Record, error) {
	if row.SchemaVersion != SchemaVersion {
		return Record{}, reject(contracts.CodeValidation,
			"stored schema_version is %d but this build hashes version %d; the record cannot "+
				"be re-derived because the version is part of the hashed payload, not a "+
				"property of the row", row.SchemaVersion, SchemaVersion)
	}
	previous, err := hashFrom(row.PreviousHash)
	if err != nil {
		return Record{}, fmt.Errorf("previous_hash: %w", err)
	}
	record, err := hashFrom(row.RecordHash)
	if err != nil {
		return Record{}, fmt.Errorf("record_hash: %w", err)
	}
	return Record{
		AuditID:       row.AuditID,
		Partition:     row.Partition,
		Sequence:      row.Sequence,
		ActorID:       row.ActorID,
		ActorType:     ActorType(row.ActorType),
		Action:        row.Action,
		TargetType:    row.TargetType,
		TargetID:      row.TargetID,
		Environment:   row.Environment,
		MarketScope:   row.MarketScope,
		OccurredAt:    TimestampFrom(row.OccurredAtUtc),
		RecordedAt:    TimestampFrom(row.RecordedAtUtc),
		Reason:        row.Reason,
		CorrelationID: row.CorrelationID,
		CausationID:   row.CausationID,
		PolicyVersion: row.PolicyVersion,
		Result:        Result(row.Result),
		BeforeDigest:  row.BeforeDigest,
		AfterDigest:   row.AfterDigest,
		PreviousHash:  previous,
		RecordHash:    record,
		SigningKeyID:  row.SigningKeyID,
	}, nil
}

// hashFrom converts a stored byte slice into a fixed-size hash.
//
// The length is checked rather than truncated or padded. A bytea of the wrong length cannot
// have come from this writer, and a hash that was silently padded or cut would produce a
// record that verifies against nothing.
func hashFrom(raw []byte) (Hash, error) {
	var h Hash
	if len(raw) != len(h) {
		return Hash{}, reject(contracts.CodeValidation,
			"stored hash is %d bytes, expected %d", len(raw), len(h))
	}
	copy(h[:], raw)
	return h, nil
}

// Rehydrate loads stored evidence into a chain that has not started.
//
// It pages every partition from sequence 1 and hands the whole archive to Restore exactly
// once. Once, because Restore refuses to run against a chain that already holds records, and
// once with everything, because Restore stages per partition independently and so handles a
// mixed archive correctly while a per-partition call would trip the already-started guard on
// the second partition. Calling it per page would also reorder the archive, which is the one
// thing Restore exists to be able to detect.
//
// Truncation is refused, not absorbed. Paging cannot tell a partition that ended from a
// partition whose newest records were deleted, because the two return the same rows, so when
// the reader can also serve signed checkpoints - SQLChainReader can, and that is the reader
// the control plane rehydrates through - each partition is anchored at its latest checkpoint
// and the archive must still reach that sequence with the hash that was signed. A surviving
// prefix is contiguous and correctly linked, so without the anchor it would restore cleanly
// and the process would go on to report a verified chain over evidence that is gone.
//
// The anchor is optional because a reader that has nowhere durable to read checkpoints from
// cannot supply one, and refusing to rehydrate at all in that case would make an in-memory
// reader unusable rather than making a truncated archive safe. What that costs is stated
// rather than hidden: without an anchor the archive is checked for tampering, reordering and
// holes, and a deleted tail is not among the things it can see.
//
// A partition with no stored records is not an error. It means the chain has not been written
// to yet, which is the ordinary state of a fresh deployment.
func Rehydrate(ctx context.Context, c *Chain, r ChainReader, partitions []string) error {
	var archive []Record
	var anchorable ChainAnchorReader
	var anchors map[string]Checkpoint
	if reader, ok := r.(ChainAnchorReader); ok {
		anchorable = reader
		anchors = make(map[string]Checkpoint, len(partitions))
	}

	for _, partition := range partitions {
		records, err := readPartition(ctx, r, partition)
		if err != nil {
			return fmt.Errorf("rehydrating partition %s: %w", partition, err)
		}
		archive = append(archive, records...)

		if anchors == nil {
			continue
		}
		cp, found, err := anchorable.LatestCheckpoint(ctx, partition)
		if err != nil {
			return fmt.Errorf("reading the head anchor of partition %s: %w", partition, err)
		}
		if !found {
			continue
		}
		if cp.Partition != partition {
			return reject(contracts.CodeValidation,
				"the checkpoint returned for partition %s names partition %q; an anchor filed "+
					"under the wrong partition would compare a sequence against the wrong chain",
				partition, cp.Partition)
		}
		anchors[partition] = cp
	}

	if len(archive) == 0 && len(anchors) == 0 {
		return nil
	}
	// The anchored restore rather than the plain one, even when no anchor was found: with an
	// empty anchor map it is the same operation, and there is then no branch here that can
	// skip the head comparison.
	if err := c.restore(archive, anchors); err != nil {
		return fmt.Errorf("restoring %d record(s) across %d partition(s): %w",
			len(archive), len(partitions), err)
	}
	return nil
}

// readPartition pages one partition in ascending sequence order.
//
// The page size is a floor on the query's working set, not a cap on the result: an in-memory
// Chain holds every record it has seen, so a partition is fully resident once rehydrated
// whatever order it arrives in.
//
// A short page is treated as the end of the partition because the query is bounded and
// ordered: if more rows existed, this page would have been full. That reasoning establishes
// completeness of the *read*, not of the archive - the rows that are not in the table are
// not rows a page can find - which is why the truncation check above and not this loop is
// what refuses a deleted tail.
func readPartition(ctx context.Context, r ChainReader, partition string) ([]Record, error) {
	records := make([]Record, 0, rehydratePageSize)
	for from := int64(1); ; from += rehydratePageSize {
		to := from + rehydratePageSize - 1
		page, err := r.ReadPartition(ctx, partition, from, to)
		if err != nil {
			return nil, err
		}
		records = append(records, page...)
		if len(page) < rehydratePageSize {
			return records, nil
		}
	}
}

var _ SQLChainReaderQuerier = (dbgen.Querier)(nil)

// The SQL reader is the one the control plane rehydrates through, so it is the one whose
// anchors Rehydrate will find. Asserting it here means a rename or a lost method is a build
// failure rather than a silent fall back to the unanchored path, which is the one branch
// where a truncated archive would go unnoticed.
var _ ChainAnchorReader = (*SQLChainReader)(nil)
