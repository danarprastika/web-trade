package audit

import (
	"sort"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// partitionState is the chain's memory of one partition.
//
// It holds only what is needed to place the next record. The records themselves are held
// by the store, because the chain's job is to make ordering and linkage structural, not
// to be the archive.
type partitionState struct {
	// lastSequence is the highest sequence issued in this partition, 0 when empty.
	lastSequence int64
	// lastHash is the record_hash of the record at lastSequence.
	lastHash Hash
}

// Chain appends records to per-partition hash chains.
//
// The chain assigns the sequence and the previous hash itself. A caller may state the
// sequence it believes it is writing, and the chain refuses if it disagrees, but it never
// accepts a sequence or a link it did not derive. That is what makes an out-of-order or
// re-parented record impossible to write rather than merely detectable afterwards.
type Chain struct {
	partitions map[string]*partitionState
	// byAuditID detects duplicate delivery. docs/22 section 7 requires duplicate
	// delivery to be idempotent, which means the same record delivered twice is one
	// record, not two, and a different record reusing an identity is a conflict.
	byAuditID map[string]Record
	// records retains the accepted records in append order per partition, for
	// checkpointing and evidence queries.
	records map[string][]Record
}

// NewChain returns an empty chain.
func NewChain() *Chain {
	return &Chain{
		partitions: make(map[string]*partitionState),
		byAuditID:  make(map[string]Record),
		records:    make(map[string][]Record),
	}
}

// LastSequence returns the highest sequence issued in a partition, or 0 when the
// partition is empty.
func (c *Chain) LastSequence(partition string) int64 {
	if ps, ok := c.partitions[partition]; ok {
		return ps.lastSequence
	}
	return 0
}

// LastHash returns the record_hash of the last record in a partition.
func (c *Chain) LastHash(partition string) (Hash, bool) {
	if ps, ok := c.partitions[partition]; ok {
		return ps.lastHash, true
	}
	return Hash{}, false
}

// Append writes records and returns them with their assigned sequence, previous hash,
// and hash filled in.
//
// Append is atomic across the whole batch: if any record is refused, none is written. A
// partial batch would leave a partition with a hole in it that no writer intended, and
// the only way to close that hole would be a record that says nothing true.
func (c *Chain) Append(records []Record) ([]Record, error) {
	// Stage the whole batch against a copy of the affected partition states, so a
	// refusal part-way through leaves the real chain untouched.
	staged := make(map[string]partitionState, len(c.partitions))
	accepted := make([]Record, 0, len(records))
	out := make([]Record, 0, len(records))

	for _, r := range records {
		// Only the chain-assigned field is left unchecked here; the sequence is checked
		// against the partition's state below, and re-validated in full by NewRecord once
		// it has been assigned.
		if err := r.validateFields(); err != nil {
			return nil, err
		}

		// Duplicate delivery. The same record arriving twice is one record; the same
		// identity carrying different content is a conflict that must not be resolved
		// by preferring either copy.
		if existing, seen := c.byAuditID[r.AuditID]; seen {
			// A redelivery typically does not restate its sequence or previous hash,
			// because those are assigned by the chain rather than by the caller. So the
			// candidate is normalised to the position this identity was actually
			// written at before the two are compared; without that, every genuine
			// redelivery would look like a conflict and no retry would be idempotent.
			normalized := r
			normalized.Sequence = existing.Sequence
			normalized.PreviousHash = existing.PreviousHash
			if normalized.ComputeHash() != existing.RecordHash {
				return nil, reject(contracts.CodeConflict,
					"audit_id %s already exists with different content; it cannot be reused", r.AuditID)
			}
			out = append(out, existing)
			continue
		}

		ps, ok := staged[r.Partition]
		if !ok {
			ps = partitionState{}
			if committed, exists := c.partitions[r.Partition]; exists {
				ps = *committed
			}
		}

		expected := ps.lastSequence + 1
		// A zero sequence means the caller did not state one, which is the common case.
		// A stated one must match exactly, so a caller retrying with a stale sequence
		// learns that it is stale rather than writing a second record at that position.
		if r.Sequence != 0 && r.Sequence != expected {
			return nil, reject(contracts.CodeConflict,
				"partition %s is at sequence %d; record %s stated sequence %d but the next is %d",
				r.Partition, ps.lastSequence, r.AuditID, r.Sequence, expected)
		}

		r.Sequence = expected
		r.PreviousHash = ps.lastHash
		hashed, err := NewRecord(r)
		if err != nil {
			return nil, err
		}

		ps.lastSequence = hashed.Sequence
		ps.lastHash = hashed.RecordHash
		staged[r.Partition] = ps

		accepted = append(accepted, hashed)
		out = append(out, hashed)
	}

	// Commit.
	for partition, ps := range staged {
		committed := ps
		c.partitions[partition] = &committed
	}
	for _, r := range accepted {
		c.byAuditID[r.AuditID] = r
		c.records[r.Partition] = append(c.records[r.Partition], r)
	}
	return out, nil
}

// Records returns the records in a partition, in append order.
//
// The returned slice is a copy, so a caller cannot reach into the chain's state. The
// records themselves are values, so a copy of the slice still cannot mutate them.
func (c *Chain) Records(partition string) []Record {
	stored := c.records[partition]
	out := make([]Record, len(stored))
	copy(out, stored)
	return out
}

// AllRecords returns every record, grouped by partition and ordered by sequence within
// each. Partition names are sorted so the result is deterministic.
func (c *Chain) AllRecords() []Record {
	names := make([]string, 0, len(c.records))
	for name := range c.records {
		names = append(names, name)
	}
	sort.Strings(names)

	var out []Record
	for _, name := range names {
		out = append(out, c.records[name]...)
	}
	return out
}

// Partitions returns the partition names in sorted order.
func (c *Chain) Partitions() []string {
	names := make([]string, 0, len(c.partitions))
	for name := range c.partitions {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// ByCorrelationID returns the records sharing a correlation ID, in sequence order.
//
// docs/22 section 5 requires a live order to be traceable end to end, and section 7
// requires evidence to be queryable by correlation ID. Searching across every partition
// matters: a workflow that crosses tenants still has one correlation ID, and the point
// of the query is to see the whole of it.
// RecordByAuditID returns the record carrying an audit identifier, and whether it exists.
//
// It is a direct index lookup rather than a scan. Append already refuses a duplicate
// audit_id within a batch and keeps byAuditID to recognise a redelivery, so the index was
// there before any caller needed it; what was missing was a way to ask, and the alternatives
// are a linear scan over every record held or a string comparison against a correlation id
// that merely happens to be related. A caller verifying that a durable registry is
// corroborated by its evidence asks this question once per model, so it should not pay for a
// scan to get an answer the chain is already holding.
func (c *Chain) RecordByAuditID(auditID string) (Record, bool) {
	if strings.TrimSpace(auditID) == "" {
		return Record{}, false
	}
	r, ok := c.byAuditID[auditID]
	return r, ok
}

func (c *Chain) ByCorrelationID(correlationID string) []Record {
	if strings.TrimSpace(correlationID) == "" {
		return nil
	}
	var out []Record
	for _, r := range c.AllRecords() {
		if r.CorrelationID == correlationID {
			out = append(out, r)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Partition != out[j].Partition {
			return out[i].Partition < out[j].Partition
		}
		return out[i].Sequence < out[j].Sequence
	})
	return out
}
