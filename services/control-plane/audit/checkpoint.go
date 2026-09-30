package audit

import (
	"sort"
	"strconv"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Checkpoint closes a batch of records.
//
// It is the point where a batch stops being a claim and becomes vouched-for evidence: it
// names the range it covers, the hashes at both ends, and the key that signed it. Without
// it, a hash chain only proves internal consistency, and an attacker who rewrote the
// whole chain from the first record forward would produce a perfectly consistent one.
type Checkpoint struct {
	// Partition is the partition the batch belongs to.
	Partition string
	// FirstSequence and LastSequence bound the batch.
	FirstSequence int64
	LastSequence  int64
	// FirstHash and LastHash are the record hashes at those bounds.
	FirstHash Hash
	LastHash  Hash
	// Count is the number of records covered. It is stored rather than derived so that a
	// record removed from the middle of a covered range is detectable as a count
	// mismatch rather than only as a sequence gap.
	Count int
	// CreatedAt is when the checkpoint was made.
	CreatedAt contracts.Timestamp
	// SigningKeyID names the key that signed it.
	SigningKeyID string
	// Signature is over CanonicalJSON.
	Signature Signature
}

// CheckpointSchemaVersion is the canonical serialization version for checkpoints. It is
// carried separately from the record schema version because checkpoints are produced by
// a different writer and may need to change independently.
const CheckpointSchemaVersion = 1

// checkpointFields returns the signed payload's fields in fixed order, for the same
// reason Record.canonicalFields does: the order is part of the format, not an artefact.
func (c Checkpoint) checkpointFields() []canonicalField {
	return []canonicalField{
		{"schema_version", strconv.Itoa(CheckpointSchemaVersion)},
		{"partition", c.Partition},
		{"first_sequence", strconv.FormatInt(c.FirstSequence, 10)},
		{"last_sequence", strconv.FormatInt(c.LastSequence, 10)},
		{"first_hash", c.FirstHash.Hex()},
		{"last_hash", c.LastHash.Hex()},
		{"count", strconv.Itoa(c.Count)},
		{"created_at_utc", c.CreatedAt.String()},
		{"signing_key_id", c.SigningKeyID},
	}
}

// CanonicalJSON renders the signed payload. The signature itself is excluded, because a
// signature cannot be part of what it signs.
func (c Checkpoint) CanonicalJSON() string {
	fields := c.checkpointFields()
	var b []byte
	b = append(b, '{')
	for i, f := range fields {
		if i > 0 {
			b = append(b, ',')
		}
		b = appendQuoted(b, f.key)
		b = append(b, ':')
		b = appendQuoted(b, f.value)
	}
	b = append(b, '}')
	return string(b)
}

// NewCheckpoint builds and signs a checkpoint over a batch of records.
//
// The records must be contiguous, in sequence order, and every one of them must be
// present. A checkpoint that covered a range with a hole in it would vouch for a chain
// it never saw, so contiguity is checked here rather than left to the verifier to
// discover later.
func NewCheckpoint(records []Record, signer Signer, createdAt contracts.Timestamp) (Checkpoint, error) {
	if len(records) == 0 {
		return Checkpoint{}, reject(contracts.CodeValidation, "a checkpoint must cover at least one record")
	}
	if signer == nil {
		return Checkpoint{}, reject(contracts.CodeValidation, "a signer is required")
	}

	ordered := make([]Record, len(records))
	copy(ordered, records)
	sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].Sequence < ordered[j].Sequence })

	partition := ordered[0].Partition
	for i, r := range ordered {
		if r.Partition != partition {
			return Checkpoint{}, reject(contracts.CodeValidation,
				"a checkpoint must cover one partition; record %s is in %q but the batch is in %q",
				r.AuditID, r.Partition, partition)
		}
		if want := ordered[0].Sequence + int64(i); r.Sequence != want {
			return Checkpoint{}, reject(contracts.CodeValidation,
				"records covered by a checkpoint must be contiguous; expected sequence %d, found %d", want, r.Sequence)
		}
	}

	cp := Checkpoint{
		Partition:     partition,
		FirstSequence: ordered[0].Sequence,
		LastSequence:  ordered[len(ordered)-1].Sequence,
		FirstHash:     ordered[0].RecordHash,
		LastHash:      ordered[len(ordered)-1].RecordHash,
		Count:         len(ordered),
		CreatedAt:     createdAt,
		SigningKeyID:  signer.KeyID(),
	}
	sig, err := signer.Sign([]byte(cp.CanonicalJSON()))
	if err != nil {
		return Checkpoint{}, err
	}
	cp.Signature = sig
	return cp, nil
}

// Verify checks the checkpoint's signature against a key ring.
func (c Checkpoint) Verify(ring *KeyRing) error {
	if len(c.Signature) == 0 {
		return reject(contracts.CodeAuthentication, "checkpoint for %s is unsigned", c.Partition)
	}
	return ring.Verify(c.SigningKeyID, []byte(c.CanonicalJSON()), c.Signature)
}
