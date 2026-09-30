// Package ledger records financial facts.
//
// Authority. The ledger is the system of record for financial facts (docs/01 section 3, rule
// 5: "Ledger is authoritative for financial facts"). Nothing else computes a balance, and
// nothing else may write one. A position or a cash balance held anywhere else is a
// projection of this package, and a projection that disagrees with the ledger is a bug in
// the projection.
//
// The three properties this package exists to make mechanical:
//
//  1. Append-only. The Store interface has no update and no delete, because a destructive
//     update is not a smaller version of an append, it is a different thing. It is
//     unrecoverable, it is unattributable, and it cannot be reviewed. A correction is a new
//     entry that references the entry it corrects (docs/05 section 'Ledger').
//
//  2. Balanced. Every entry balances per asset. An unbalanced entry is refused at the point
//     of posting rather than discovered during a reconciliation weeks later, when the money
//     has already moved and the only remedy is a compensating entry for a defect nobody
//     remembers making.
//
//  3. Rebuildable. A projection is a fold over the entries and holds no authority. It can be
//     deleted at any moment and recomputed to an identical result, which is the property
//     that makes it safe to treat as a cache (docs/25 section 3, invariant 4).
//
// This package is pure domain logic. It reads no clock and no ambient state: the posting
// time, the actor, and the correlation are inputs, so a ledger built from a recorded
// sequence of posts replays identically.
package ledger
