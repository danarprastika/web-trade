package audit

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// Sink is the durable, independent copy of accepted audit records.
//
// This is the interface Guard.Exported has been waiting for. Until it existed, the guard's
// backlog had exactly one decrement path and no producer, so the guard could enter a state it
// could not leave; see Exporter for the shape of the fix and guard.go's Clear for the
// related change that stops the operator's escape hatch from appearing to work when it does
// not.
//
// Sink is deliberately separate from Chain. Chain decides what a record is and where it
// belongs; the sink decides where the bytes go. Keeping them apart is what allows the same
// chain to be exported to more than one destination, which docs/22 section 4 requires
// independent immutable retention - one database is not independent of the process that
// writes to it.
type Sink interface {
	// Export writes a batch of records durably. It returns nil only once the records are
	// committed.
	//
	// A batch is all-or-nothing. Returning nil for a partially written batch would let
	// the caller release backlog for records that were never stored, which is the one
	// failure this interface exists to make impossible.
	Export(ctx context.Context, records []Record) error
}

// SQLSinkQuerier is the subset of the generated accessors this sink uses.
//
// It is narrow for the same reason the model package's ports are: a sink that can reach
// every generated query can be handed a write the 0002 guards do not cover. Both reachable
// writes are appends into the two audit tables, and nothing else is: there is no update, no
// delete, and no upsert, because a sink that could modify or remove evidence would not be a
// sink.
//
// AppendAuditCheckpoint is here because the anchor is the sink's product too. The reader
// side of this package treats a partition's latest checkpoint as the only durable statement
// of how far that partition went - it is what makes a deleted tail detectable rather than
// merely internal consistency - and a consumer with no producer is a check that can never
// fire. Every test of that check inserted its own checkpoint, so the absence of a producer
// was invisible until a live database was involved.
type SQLSinkQuerier interface {
	AppendAuditRecord(ctx context.Context, arg dbgen.AppendAuditRecordParams) (dbgen.AuditRecord, error)
	AppendAuditCheckpoint(ctx context.Context, arg dbgen.AppendAuditCheckpointParams) (dbgen.AuditCheckpoint, error)
}

// Anchor is what seals a durable export: the signer that vouches for the batch and the clock
// that dates the vouching.
//
// It is a type rather than two constructor parameters because a sink needs both together.
// NewCheckpoint refuses a nil signer, and created_at is part of the signed payload, so
// neither can be defaulted by omission. Bundling them means one requirement with one name
// instead of two arguments that can each be forgotten, and the refusal can say what is
// missing instead of which argument was nil.
type Anchor struct {
	signer Signer
	clock  func() time.Time
}

// NewAnchor returns the signer-and-clock pair a sink closes each export with.
func NewAnchor(signer Signer, clock func() time.Time) (*Anchor, error) {
	if signer == nil {
		// Refused rather than defaulted. A sink with no signer could only store records, and
		// an archive nothing has vouched for is indistinguishable from an archive whose tail
		// was deleted - which is the failure the checkpoint exists to detect.
		return nil, errors.New("a sql-backed audit sink requires a checkpoint signer; without " +
			"one the export would commit records that nothing says how far they reach, and a " +
			"truncated archive would restore as verified")
	}
	if clock == nil {
		return nil, errors.New("a sql-backed audit sink requires a clock; a checkpoint's " +
			"created_at is part of its signed payload and cannot be defaulted by omission")
	}
	return &Anchor{signer: signer, clock: clock}, nil
}

// Signer returns the signer this anchor closes checkpoints with.
//
// It is here for a caller that also builds a verification ring: the ring needs the signer's
// public key, and the anchor is the one value the sink was given.
func (a *Anchor) Signer() Signer { return a.signer }

// seal signs a checkpoint over one partition's contiguous range.
func (a *Anchor) seal(records []Record) (Checkpoint, error) {
	return NewCheckpoint(records, a.signer, TimestampFrom(a.clock()))
}

// SQLSink is a Sink backed by the generated accessors over PostgreSQL.
//
// It takes a *sql.DB rather than building a pool, for the reason the model store does: a
// pool constructed here would be invisible to the caller's shutdown sequence. It imports
// database/sql and the generated accessors and nothing else, so it introduces no driver
// dependency - which matters here for the same reason it matters in the model store, since
// no pgx v5 release currently satisfies the repository's pinning gate.
type SQLSink struct {
	// q is the narrow querier used when no transaction is opened.
	q SQLSinkQuerier
	// begin runs fn with a transaction-scoped querier, committing when fn returns nil.
	begin func(ctx context.Context, fn func(SQLSinkQuerier) error) error
	// close releases the caller's pool. It is nil when the sink did not create one.
	close func() error
	// anchor signs the checkpoint each committed export closes with. It is never nil: a sink
	// that could not vouch for its own batch would be constructed only to reintroduce the
	// unanchored archive this now refuses.
	anchor *Anchor
}

// NewSQLSink returns a SQLSink that writes each batch, and the checkpoint covering it, in one
// transaction of its own.
func NewSQLSink(db *sql.DB, anchor *Anchor) (*SQLSink, error) {
	if db == nil {
		return nil, errors.New("a sql-backed audit sink requires a database handle; " +
			"constructing one here would hide the pool from the caller's shutdown sequence")
	}
	if anchor == nil {
		return nil, errors.New("a sql-backed audit sink requires an anchor; a sink that " +
			"cannot sign a checkpoint over what it stores would commit unanchored evidence, " +
			"and a truncated archive would then restore as verified")
	}
	return &SQLSink{
		q:      dbgen.New(db),
		close:  db.Close,
		anchor: anchor,
		begin:  sinkBeginTx[SQLSinkQuerier](db, func(tx *sql.Tx) SQLSinkQuerier { return dbgen.New(tx) }),
	}, nil
}

// NewSQLSinkInTx returns a SQLSink whose writes join a transaction the caller already owns.
//
// The caller commits, not this sink. It is named separately from NewSQLSink because the
// difference is who owns the commit, and a mistake there means a sink that reports success
// for records a later rollback erased.
func NewSQLSinkInTx(q SQLSinkQuerier, anchor *Anchor) (*SQLSink, error) {
	if q == nil {
		return nil, errors.New("a sql-backed audit sink requires a querier")
	}
	if anchor == nil {
		return nil, errors.New("a sql-backed audit sink requires an anchor; a sink that " +
			"cannot sign a checkpoint over what it stores would commit unanchored evidence, " +
			"and a truncated archive would then restore as verified")
	}
	return &SQLSink{
		q:      q,
		close:  func() error { return nil },
		anchor: anchor,
		begin:  func(_ context.Context, fn func(SQLSinkQuerier) error) error { return fn(q) },
	}, nil
}

// sinkBeginTx returns a function that runs fn inside a transaction it owns.
//
// It is a separate copy of the model store's beginTx rather than a shared helper because
// the two packages cannot import each other without the sink's independence being
// compromised: a sink that lives in the same package as the thing it stores is not an
// independent copy of anything. The rollback error is discarded for the same reason as
// there - after a successful Commit it returns sql.ErrTxDone, and reporting that would turn
// a committed write into a reported failure.
func sinkBeginTx[Q any](
	db *sql.DB,
	newQuerier func(*sql.Tx) Q,
) func(context.Context, func(Q) error) error {
	return func(ctx context.Context, fn func(Q) error) error {
		tx, err := db.BeginTx(ctx, nil)
		if err != nil {
			return fmt.Errorf("beginning the audit export transaction: %w", err)
		}
		defer func() { _ = tx.Rollback() }()

		if err := fn(newQuerier(tx)); err != nil {
			return err
		}
		if err := tx.Commit(); err != nil {
			return fmt.Errorf("committing the audit export transaction: %w", err)
		}
		return nil
	}
}

// Export writes the batch in one transaction, in the order given, and closes it with one signed
// checkpoint per partition the batch touched.
//
// Order is the caller's business, not this sink's: the records arrive from a chain that
// already numbered them, and re-sorting here would mean the durable order and the chain
// order could disagree, which is the one comparison the integrity verifier exists to make.
//
// The checkpoint is written in the same transaction as the records, and this is the property
// the whole change exists for. A checkpoint committed separately is the same class of bug as
// no checkpoint at all: a crash between the two commits either leaves an anchor vouching for
// records that were never written - so the restore refuses an archive that is perfectly
// intact - or leaves records with no anchor, which is precisely the hole being closed. One
// transaction removes the window, and a failure anywhere in it discards both halves.
//
// Anything that prevents the anchor is reported as a failure of the whole export. Returning
// nil for records whose checkpoint could not be stored would release the guard's backlog for
// evidence nothing has promised anything about, which is the unanchored state this refuses.
func (s *SQLSink) Export(ctx context.Context, records []Record) error {
	if len(records) == 0 {
		return nil
	}

	// Signed before the transaction opens, so a batch that cannot be anchored - a partition
	// with a hole in it, or a signer that will not sign - is refused without writing a single
	// record. The parameters are then inserted inside the transaction with the records, which
	// is where the atomicity actually has to hold.
	anchors, err := s.checkpoints(records)
	if err != nil {
		return err
	}

	return s.begin(ctx, func(q SQLSinkQuerier) error {
		for _, r := range records {
			if _, err := q.AppendAuditRecord(ctx, paramsFor(r)); err != nil {
				return fmt.Errorf("exporting audit record %s (partition %s sequence %d): %w",
					r.AuditID, r.Partition, r.Sequence, err)
			}
		}
		for _, anchor := range anchors {
			if _, err := q.AppendAuditCheckpoint(ctx, anchor); err != nil {
				return fmt.Errorf("recording the audit checkpoint for partition %s "+
					"(sequences %d..%d): %w",
					anchor.Partition, anchor.FirstSequence, anchor.LastSequence, err)
			}
		}
		return nil
	})
}

// checkpoints builds one signed checkpoint per partition present in records.
//
// Grouping is by partition because a partition is what a checkpoint covers: NewCheckpoint
// refuses a batch spanning two partitions, and "this partition reached sequence N with this
// hash" is the statement the restore needs to hear. One checkpoint per partition per export,
// never one per record - an anchor's job is to close a range, and a row per record would be
// one row per record saying the same thing with only the last one carrying the weight.
//
// The checkpoint covers the range this export appended, not the partition's whole history.
// GetLatestAuditCheckpoint orders by last_sequence DESC, so the newest row is the one that
// describes how far the partition actually went; emitting a fresh one per export keeps that
// row advancing with the records instead of restating an older boundary. Successive exports of
// one partition therefore produce adjacent, non-overlapping ranges, which is what the
// table's uniqueness on (partition, last_sequence) and its deferred coverage check expect.
//
// Partitions are visited in sorted order so that a batch which cannot be anchored fails
// naming the same partition on every run rather than whichever the map happened to yield.
func (s *SQLSink) checkpoints(records []Record) ([]dbgen.AppendAuditCheckpointParams, error) {
	byPartition := make(map[string][]Record, len(records))
	for _, r := range records {
		byPartition[r.Partition] = append(byPartition[r.Partition], r)
	}
	partitions := make([]string, 0, len(byPartition))
	for partition := range byPartition {
		partitions = append(partitions, partition)
	}
	sort.Strings(partitions)

	out := make([]dbgen.AppendAuditCheckpointParams, 0, len(partitions))
	for _, partition := range partitions {
		cp, err := s.anchor.seal(byPartition[partition])
		if err != nil {
			return nil, fmt.Errorf("sealing the audit checkpoint for partition %s: %w", partition, err)
		}
		out = append(out, checkpointParams(cp))
	}
	return out, nil
}

// checkpointParams maps a signed checkpoint onto the generated insert's parameters.
//
// Written out field by field for the reason paramsFor is: the mapping is the contract between
// what was signed and what is stored, and a column that is quietly omitted is a column the
// restore cannot compare against.
func checkpointParams(cp Checkpoint) dbgen.AppendAuditCheckpointParams {
	return dbgen.AppendAuditCheckpointParams{
		Partition:     cp.Partition,
		FirstSequence: cp.FirstSequence,
		LastSequence:  cp.LastSequence,
		// Copied, not aliased, for the reason the record hashes are: these arrays belong to
		// the checkpoint and a slice sharing their backing store could be rewritten under the
		// driver.
		FirstHash:     append([]byte(nil), cp.FirstHash[:]...),
		LastHash:      append([]byte(nil), cp.LastHash[:]...),
		RecordCount:   int32(cp.Count),
		CreatedAtUtc:  cp.CreatedAt.Time(),
		SigningKeyID:  cp.SigningKeyID,
		Signature:     append([]byte(nil), cp.Signature...),
		SchemaVersion: int32(CheckpointSchemaVersion),
	}
}

// paramsFor maps a record onto the generated insert's parameters.
//
// The mapping is written out field by field rather than reflected, because a reflection
// would be free to skip a field the schema requires and default it instead, and the whole
// point of writing the redundant guards into the migration is that a missing field is
// caught. Written by hand, adding a field to Record without adding it here is a compile
// error at the missing value only if the type changes - so the mapping is instead checked
// by TestEveryRecordFieldReachesTheDatabase, which compares the two sets by name.
func paramsFor(r Record) dbgen.AppendAuditRecordParams {
	return dbgen.AppendAuditRecordParams{
		AuditID:       r.AuditID,
		Partition:     r.Partition,
		Sequence:      r.Sequence,
		ActorID:       r.ActorID,
		ActorType:     string(r.ActorType),
		Action:        r.Action,
		TargetType:    r.TargetType,
		TargetID:      r.TargetID,
		Environment:   r.Environment,
		MarketScope:   r.MarketScope,
		OccurredAtUtc: r.OccurredAt.Time(),
		RecordedAtUtc: r.RecordedAt.Time(),
		Reason:        r.Reason,
		CorrelationID: r.CorrelationID,
		CausationID:   r.CausationID,
		PolicyVersion: r.PolicyVersion,
		Result:        string(r.Result),
		BeforeDigest:  r.BeforeDigest,
		AfterDigest:   r.AfterDigest,
		// Hash is a fixed-size array, so this conversion copies rather than aliases. That
		// matters: a slice sharing the array's backing store would let a later write to
		// the record mutate bytes the driver may not have written yet.
		PreviousHash:  append([]byte(nil), r.PreviousHash[:]...),
		RecordHash:    append([]byte(nil), r.RecordHash[:]...),
		SigningKeyID:  r.SigningKeyID,
		SchemaVersion: int32(SchemaVersion),
	}
}

// Close releases the underlying pool, when the sink was given one.
func (s *SQLSink) Close() error {
	if s.close == nil {
		return nil
	}
	return s.close()
}

// Exporter is the component that gives Guard.Exported a producer.
//
// The guard counts records it has accepted but not exported, and refuses new work when the
// backlog reaches its limit. Until this type existed, nothing ever reduced that count, so
// the guard had a door and no way to open it. An Exporter is that way: it writes to a Sink
// and releases the backlog only for records the sink has committed.
type Exporter struct {
	guard *Guard
	sink  Sink
}

// NewExporter returns an Exporter that drains g's backlog into sink.
func NewExporter(g *Guard, sink Sink) (*Exporter, error) {
	if g == nil {
		return nil, errors.New("an exporter requires a guard; without one there is no " +
			"backlog to drain and nothing for the sink to release")
	}
	if sink == nil {
		return nil, errors.New("an exporter requires a sink; without one nothing can " +
			"reach durable storage and the backlog it drains would grow without bound")
	}
	return &Exporter{guard: g, sink: sink}, nil
}

// Guard returns the guard whose backlog this exporter drains.
func (e *Exporter) Guard() *Guard { return e.guard }

// Export writes records durably and releases their backlog.
//
// The order is load-bearing and is the property this type exists to guarantee: the sink is
// written first, and the backlog is released only after it has committed. Releasing first
// would be the natural way to write this and it is a data-loss bug - a sink that then
// refuses leaves the records counted as exported, the guard's limit no longer reflecting
// reality, and the system resuming as though the evidence were safe when it is in a
// process buffer that a crash erases.
func (e *Exporter) Export(ctx context.Context, records []Record) error {
	if len(records) == 0 {
		return nil
	}
	if err := e.sink.Export(ctx, records); err != nil {
		// The backlog is deliberately untouched. The records are still owed a place in
		// durable storage, and the guard's whole purpose is to count what is still owed.
		return fmt.Errorf("exporting %d audit record(s) to durable storage: %w", len(records), err)
	}
	if err := e.guard.Exported(len(records)); err != nil {
		// The records are committed, so the backlog really has shrunk. A refusal here
		// means the caller exported more records than it ever accepted, which is a
		// programming error rather than a storage failure - and it is reported rather
		// than swallowed, because leaving pending too high would re-trip a halt that the
		// real state no longer justifies.
		return fmt.Errorf("releasing backlog after exporting %d audit record(s): %w",
			len(records), err)
	}
	return nil
}

// Accept records that n more audit records are pending export, and returns the guard's
// verdict.
//
// It exists so that a caller reserving backlog and a caller releasing it are calling the
// same guard through one type. The failure mode it removes is a caller that reserves
// against one guard and exports against another, which produces a permanently non-zero
// backlog on one of them and an unbounded one on the other, with no error anywhere.
func (e *Exporter) Accept(n int) error { return e.guard.Accept(n) }

// Assert the exporter actually wires the two halves together, so a change to either
// signature is a build failure rather than a runtime surprise.
var _ interface {
	Export(context.Context, []Record) error
	Accept(int) error
} = (*Exporter)(nil)

// compile-time assertion that the narrow interface above is satisfied by the generated
// querier. Without this, renaming a generated accessor surfaces in a deployment.
var _ SQLSinkQuerier = (dbgen.Querier)(nil)
