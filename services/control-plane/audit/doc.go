// Package audit records evidence of what was decided and who decided it.
//
// Authority. The audit chain is the platform's account of its own behaviour. It is
// append-only, hash-chained, and closed by signed checkpoints, so a missing, altered,
// reordered or replayed record is detectable without trusting the database that
// stored it (docs/22, ADR-022).
//
// The three properties this package exists to make mechanical:
//
//  1. Tamper-evident. Each record carries the hash of the record before it, within its
//     partition, so changing any record invalidates that record and every record after
//     it. Deleting a record from the middle leaves a sequence gap. Reordering breaks
//     the previous-hash link. Replaying an old record reuses a sequence that has
//     already been consumed. None of these require the attacker to cooperate.
//
//  2. Independently verifiable. A batch is closed by a checkpoint naming the partition,
//     the sequence range, the first and last hash, the count, and the signing key. A
//     verifier given records and checkpoints decides integrity on its own, so the
//     database is evidence rather than authority.
//
//  3. Never silently lossy. When the audit sink is unavailable, records accumulate in a
//     bounded buffer and sensitive operations are blocked before the buffer can overflow.
//     There is no path that discards an audit record, because an audit record that can
//     be lost is not evidence of anything.
//
// This package is pure domain logic. It reads no clock, no key material store, and no
// ambient state: time, actor, and the signing implementation are inputs, so an audit
// chain built from a recorded sequence of decisions verifies identically on replay.
package audit
