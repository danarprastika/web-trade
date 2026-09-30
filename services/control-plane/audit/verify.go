package audit

import (
	"sort"
	"strconv"
)

// itoa64 renders a sequence for a finding's detail text. Findings are read by people, so
// the number is spelled out rather than left as a format verb.
func itoa64(v int64) string { return strconv.FormatInt(v, 10) }

// Verifier checks a set of records and checkpoints and decides whether the evidence is
// intact.
//
// It is deliberately given data rather than a Chain. The point of docs/22 and ADR-022 is
// that evidence must be verifiable without trusting the system that produced it, so the
// verifier reads what was actually stored or exported, in the order it was presented,
// and reaches its own conclusion. Handing it a Chain would let it re-derive the answer
// from the same in-memory state that produced the records, which would verify nothing.
type Verifier struct {
	ring *KeyRing
}

// NewVerifier returns a verifier trusting the keys in ring.
func NewVerifier(ring *KeyRing) *Verifier { return &Verifier{ring: ring} }

// Verify checks records presented in the given order, against the given checkpoints.
//
// Every finding is reported rather than returning at the first one. A verifier that
// stopped early would let a second, independent tampering attempt hide behind the first,
// and the operator would fix the visible one and reopen the system still compromised.
//
// The presented order is checked as presented and is never sorted. Sorting first would
// make reordering invisible by construction, since the chain linkage does not depend on
// list order; detecting it requires refusing to normalise the input.
func (v *Verifier) Verify(records []Record, checkpoints []Checkpoint) Verification {
	result := Verification{OK: true, RecordsChecked: len(records), CheckpointsChecked: len(checkpoints)}

	report := func(f Finding) {
		result.OK = false
		result.Findings = append(result.Findings, f)
	}

	// Partition the records by partition, preserving the order they were presented in.
	var order []string
	byPartition := make(map[string][]Record)
	for _, r := range records {
		if _, seen := byPartition[r.Partition]; !seen {
			order = append(order, r.Partition)
		}
		byPartition[r.Partition] = append(byPartition[r.Partition], r)
	}

	checkpointsByPartition := make(map[string][]Checkpoint)
	for _, cp := range checkpoints {
		checkpointsByPartition[cp.Partition] = append(checkpointsByPartition[cp.Partition], cp)
	}

	for _, partition := range order {
		v.verifyPartition(partition, byPartition[partition], checkpointsByPartition[partition], report)
	}

	// A checkpoint for a partition with no records at all is itself suspicious: either
	// every record for that partition was removed, or the checkpoint does not belong.
	for _, cp := range checkpoints {
		if _, hasRecords := byPartition[cp.Partition]; !hasRecords {
			report(Finding{
				Kind:      FindingDeletion,
				Partition: cp.Partition,
				Sequence:  cp.FirstSequence,
				Detail:    "a signed checkpoint covers this partition but no records were presented for it",
			})
		}
	}

	return result
}

// reportFunc receives a finding. It is a named type so the partition walk can pass the
// accumulator without importing a closure-shaped API into the signature above.
type reportFunc func(Finding)

func (v *Verifier) verifyPartition(partition string, records []Record, checkpoints []Checkpoint, report reportFunc) {
	seen := make(map[int64]bool, len(records))
	// The hash the current record must link to: the previous record's, or a
	// checkpoint's LastHash where a batch has been closed.
	var expectedPrevious Hash
	var expectedSequence int64 = 1
	// checkpointIndex walks checkpoints as the record walk crosses their bounds.
	sort.SliceStable(checkpoints, func(i, j int) bool {
		return checkpoints[i].FirstSequence < checkpoints[j].FirstSequence
	})
	nextCheckpoint := 0

	for _, r := range records {
		// Replay: a sequence already consumed in this partition.
		if seen[r.Sequence] {
			report(Finding{
				Kind:      FindingReplay,
				Partition: partition,
				Sequence:  r.Sequence,
				Detail:    "sequence already appears in this partition; a record was replayed or duplicated",
			})
			// Keep walking: the record still has to be checked for other problems.
		}
		seen[r.Sequence] = true

		// Deletion: a gap in the sequence means a record was removed.
		if r.Sequence > expectedSequence {
			report(Finding{
				Kind:      FindingDeletion,
				Partition: partition,
				Sequence:  r.Sequence,
				Detail:    "sequence jumps from " + itoa64(expectedSequence) + " to " + itoa64(r.Sequence) + "; a record was removed",
			})
		} else if r.Sequence < expectedSequence {
			// Reorder: the record is behind the walk, so the presented order does not
			// match the sequence order.
			report(Finding{
				Kind:      FindingReorder,
				Partition: partition,
				Sequence:  r.Sequence,
				Detail:    "record appears out of order; expected sequence " + itoa64(expectedSequence),
			})
		}

		// Tamper: the record's own hash must match its content.
		if r.RecordHash != r.ComputeHash() {
			report(Finding{
				Kind:      FindingTamper,
				Partition: partition,
				Sequence:  r.Sequence,
				Detail:    "recomputed hash does not match the recorded hash; the record was altered",
			})
		}

		// Reorder: the record must link to whatever actually precedes it.
		if r.PreviousHash != expectedPrevious {
			report(Finding{
				Kind:      FindingReorder,
				Partition: partition,
				Sequence:  r.Sequence,
				Detail:    "previous_hash does not match the record that actually precedes it",
			})
		}

		expectedPrevious = r.RecordHash
		expectedSequence = r.Sequence + 1

		// When a checkpoint's range ends here, the next record must resume from the
		// signed LastHash. This is the restore check: a restored database whose chain
		// does not continue from the last signed checkpoint lost or reordered evidence.
		for nextCheckpoint < len(checkpoints) && checkpoints[nextCheckpoint].LastSequence == r.Sequence {
			cp := checkpoints[nextCheckpoint]
			v.verifyCheckpointAgainstRecords(cp, records, report)
			expectedPrevious = cp.LastHash
			nextCheckpoint++
		}
	}

	// Any checkpoint never reached means its covered records were not all presented.
	for ; nextCheckpoint < len(checkpoints); nextCheckpoint++ {
		cp := checkpoints[nextCheckpoint]
		report(Finding{
			Kind:      FindingCheckpoint,
			Partition: partition,
			Sequence:  cp.FirstSequence,
			Detail:    "a signed checkpoint covers a range that was not fully presented",
		})
		v.verifyCheckpointSignature(cp, report)
	}
}

// verifyCheckpointAgainstRecords checks a checkpoint against the records it claims to
// cover, and verifies its signature.
func (v *Verifier) verifyCheckpointAgainstRecords(cp Checkpoint, records []Record, report reportFunc) {
	v.verifyCheckpointSignature(cp, report)

	var covered int
	var first, last *Record
	for i := range records {
		if records[i].Sequence >= cp.FirstSequence && records[i].Sequence <= cp.LastSequence {
			covered++
			if first == nil {
				first = &records[i]
			}
			last = &records[i]
		}
	}

	if covered != cp.Count {
		report(Finding{
			Kind:      FindingCheckpoint,
			Partition: cp.Partition,
			Sequence:  cp.FirstSequence,
			Detail:    "checkpoint covers " + itoa64(int64(cp.Count)) + " records but " + itoa64(int64(covered)) + " were presented",
		})
	}
	if first != nil && first.RecordHash != cp.FirstHash {
		report(Finding{
			Kind:      FindingCheckpoint,
			Partition: cp.Partition,
			Sequence:  cp.FirstSequence,
			Detail:    "checkpoint first_hash does not match the record at its first sequence",
		})
	}
	if last != nil && last.RecordHash != cp.LastHash {
		report(Finding{
			Kind:      FindingCheckpoint,
			Partition: cp.Partition,
			Sequence:  cp.LastSequence,
			Detail:    "checkpoint last_hash does not match the record at its last sequence",
		})
	}
}

func (v *Verifier) verifyCheckpointSignature(cp Checkpoint, report reportFunc) {
	if err := cp.Verify(v.ring); err != nil {
		kind := FindingSignature
		if cp.SigningKeyID == "" {
			kind = FindingCheckpoint
		}
		report(Finding{
			Kind:      kind,
			Partition: cp.Partition,
			Sequence:  cp.FirstSequence,
			Detail:    err.Error(),
		})
	}
}
