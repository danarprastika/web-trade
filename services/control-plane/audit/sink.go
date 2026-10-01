package audit

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

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
// every generated query can be handed a write the 0002 guards do not cover. Note that only
// AppendAuditRecord is reachable here - there is no update, no delete, and no upsert,
// because a sink that could modify or remove evidence would not be a sink.
type SQLSinkQuerier interface {
	AppendAuditRecord(ctx context.Context, arg dbgen.AppendAuditRecordParams) (dbgen.AuditRecord, error)
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
}

// NewSQLSink returns a SQLSink that writes each batch in its own transaction.
func NewSQLSink(db *sql.DB) (*SQLSink, error) {
	if db == nil {
		return nil, errors.New("a sql-backed audit sink requires a database handle; " +
			"constructing one here would hide the pool from the caller's shutdown sequence")
	}
	return &SQLSink{
		q:     dbgen.New(db),
		close: db.Close,
		begin: sinkBeginTx[SQLSinkQuerier](db, func(tx *sql.Tx) SQLSinkQuerier { return dbgen.New(tx) }),
	}, nil
}

// NewSQLSinkInTx returns a SQLSink whose writes join a transaction the caller already owns.
//
// The caller commits, not this sink. It is named separately from NewSQLSink because the
// difference is who owns the commit, and a mistake there means a sink that reports success
// for records a later rollback erased.
func NewSQLSinkInTx(q SQLSinkQuerier) (*SQLSink, error) {
	if q == nil {
		return nil, errors.New("a sql-backed audit sink requires a querier")
	}
	return &SQLSink{
		q:     q,
		close: func() error { return nil },
		begin: func(_ context.Context, fn func(SQLSinkQuerier) error) error { return fn(q) },
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

// Export writes the batch in one transaction, in the order given.
//
// Order is the caller's business, not this sink's: the records arrive from a chain that
// already numbered them, and re-sorting here would mean the durable order and the chain
// order could disagree, which is the one comparison the integrity verifier exists to make.
func (s *SQLSink) Export(ctx context.Context, records []Record) error {
	if len(records) == 0 {
		return nil
	}
	return s.begin(ctx, func(q SQLSinkQuerier) error {
		for _, r := range records {
			if _, err := q.AppendAuditRecord(ctx, paramsFor(r)); err != nil {
				return fmt.Errorf("exporting audit record %s (partition %s sequence %d): %w",
					r.AuditID, r.Partition, r.Sequence, err)
			}
		}
		return nil
	})
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
