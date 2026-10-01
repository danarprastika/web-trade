package audit

import (
	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Restore rebuilds a chain from records read back out of durable storage.
//
// This is the half of restore that was missing. docs/22 and ADR-022 are explicit that
// evidence must be verifiable without trusting the system that produced it, and WI-117's
// fifth acceptance criterion asks for restore *detection* - which the Verifier provides,
// against checkpoints, for data someone else hands it. Detection is not restoration. Without
// this method a process that restarts has no way to continue a chain: the in-memory chain
// starts empty, allocates sequence 1 for the next record, and collides with a record that
// has existed in storage for months. Every consumer of the chain that needs to survive a
// restart - the model journal above all - is therefore unable to rehydrate, and had recorded
// that as a limitation rather than as a missing method.
//
// Restore is deliberately not a constructor and deliberately not a partial operation:
//
//   - It refuses on a chain that already holds records. Restoring into a live chain would
//     leave the two histories interleaved, and the resulting chain would still hash correctly
//     while describing two different events at the same sequence. That is a corruption the
//     Verifier cannot detect, because each record is individually well-formed.
//   - It is all-or-nothing. A restore that applied records until it hit a bad one would leave
//     a chain that looks usable and is not, and the next append would build on records whose
//     linkage was never established.
//   - It verifies as it goes. Each record's hash is recomputed and each link is checked
//     against the record that precedes it, so a tampered, truncated or reordered archive is
//     refused at the point of loading rather than discovered later by a reader who has no way
//     to tell a silent truncation from a partition that simply ended.
//
// Records are presented in the order they were stored and are never sorted. Sorting would
// make reordering invisible by construction, which is the same reasoning that keeps the
// Verifier from normalising its input.
func (c *Chain) Restore(records []Record) error {
	if len(c.partitions) > 0 || len(c.byAuditID) > 0 || len(c.records) > 0 {
		return reject(contracts.CodeConflict,
			"this chain already holds %d partition(s) and %d record(s); restore is only "+
				"meaningful on a chain that has not started, because restoring into a live "+
				"chain would interleave two histories at the same sequence numbers",
			len(c.partitions), len(c.byAuditID))
	}

	// Stage everything, exactly as Append does, so a refusal part-way through leaves the
	// real chain untouched rather than half-restored.
	staged := make(map[string]partitionState, len(records))
	byAuditID := make(map[string]Record, len(records))
	ordered := make(map[string][]Record, len(records))

	for i, r := range records {
		if err := r.Validate(); err != nil {
			return reject(contracts.CodeValidation,
				"record %d of the restore (audit_id %q) is not a valid record: %v", i, r.AuditID, err)
		}
		// The stored hash must be the hash of the stored content. This is the check that
		// makes a tampered archive un-restorable rather than merely detectable.
		if recomputed := r.ComputeHash(); recomputed != r.RecordHash {
			return reject(contracts.CodeValidation,
				"record %d of the restore (audit_id %q) does not hash to its stored value; "+
					"the stored content has been altered since it was written", i, r.AuditID)
		}
		if existing, seen := byAuditID[r.AuditID]; seen {
			return reject(contracts.CodeConflict,
				"audit_id %s appears twice in the restore, at sequences %d and %d; an "+
					"identity cannot carry two records", r.AuditID, existing.Sequence, r.Sequence)
		}

		ps, ok := staged[r.Partition]
		if !ok {
			ps = partitionState{}
			ps.lastHash = GenesisHash
		}
		if r.Sequence != ps.lastSequence+1 {
			return reject(contracts.CodeValidation,
				"partition %s is missing sequence %d: the restore presents %d where %d is "+
					"required. A gap means evidence was deleted, and a restored chain with a "+
					"hole in it would let the next append fill it with a record that links to "+
					"nothing",
				r.Partition, ps.lastSequence+1, r.Sequence, ps.lastSequence+1)
		}
		if r.PreviousHash != ps.lastHash {
			return reject(contracts.CodeValidation,
				"record %d of the restore (audit_id %q) links to the wrong predecessor in "+
					"partition %s; the stored chain does not follow from the record before it",
				i, r.AuditID, r.Partition)
		}

		ps.lastSequence = r.Sequence
		ps.lastHash = r.RecordHash
		staged[r.Partition] = ps
		byAuditID[r.AuditID] = r
		ordered[r.Partition] = append(ordered[r.Partition], r)
	}

	// Commit. Nothing above mutated the chain, so this is the first point at which it
	// changes at all.
	for partition, ps := range staged {
		committed := ps
		c.partitions[partition] = &committed
	}
	for auditID, r := range byAuditID {
		c.byAuditID[auditID] = r
	}
	for partition, rs := range ordered {
		c.records[partition] = rs
	}
	return nil
}
