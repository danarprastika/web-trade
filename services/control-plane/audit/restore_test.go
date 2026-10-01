package audit

import "testing"

// chainOf builds n linked records in one partition by appending them to a throwaway chain,
// which is the only way to obtain a set that genuinely hashes together. Hand-built records
// would be accepted by Restore only if the test rebuilt every hash correctly by hand, and a
// test that does that is a test of the test.
func chainOf(t *testing.T, n int) []Record {
	t.Helper()
	c := NewChain()
	staged := make([]Record, 0, n)
	for i := 0; i < n; i++ {
		staged = append(staged, stagedRecord(auditIDFor(i), "tenant-a"))
	}
	out, err := c.Append(staged)
	if err != nil {
		t.Fatalf("building the fixture chain: %v", err)
	}
	return out
}

func auditIDFor(i int) string {
	return "aud-" + string(rune('a'+i))
}

func TestARestoredChainContinuesTheSameHistory(t *testing.T) {
	stored := chainOf(t, 3)

	restored := NewChain()
	if err := restored.Restore(stored); err != nil {
		t.Fatalf("Restore: %v", err)
	}

	// The point of restoring. A fresh chain would hand sequence 1 to the next record and
	// collide with a record that has existed in storage for months, so this is the property
	// that makes rehydration possible at all.
	if got := restored.LastSequence("tenant-a"); got != 3 {
		t.Fatalf("last sequence after restore = %d, want 3", got)
	}
	out, err := restored.Append([]Record{stagedRecord("aud-d", "tenant-a")})
	if err != nil {
		t.Fatalf("appending after a restore: %v", err)
	}
	if out[0].Sequence != 4 {
		t.Fatalf("the record after a restore got sequence %d, want 4", out[0].Sequence)
	}
	if out[0].PreviousHash != stored[2].RecordHash {
		t.Fatal("the record after a restore does not link to the restored record; the chain " +
			"was rebuilt without its history and will verify as a break")
	}
}

func TestARestoredChainPreservesRedeliveryIdempotence(t *testing.T) {
	stored := chainOf(t, 2)
	restored := NewChain()
	if err := restored.Restore(stored); err != nil {
		t.Fatalf("Restore: %v", err)
	}
	// Redelivering a stored record must be recognised as the same record, not appended
	// again. Without byAuditID being rebuilt, a retried delivery becomes a second record
	// with the same identity at a new sequence, which is a duplicate the chain cannot see.
	out, err := restored.Append([]Record{stored[0]})
	if err != nil {
		t.Fatalf("redelivering a stored record must be idempotent: %v", err)
	}
	if out[0].Sequence != stored[0].Sequence {
		t.Fatalf("redelivery returned sequence %d, want the original %d",
			out[0].Sequence, stored[0].Sequence)
	}
	if got := restored.LastSequence("tenant-a"); got != 2 {
		t.Fatalf("redelivery advanced the chain to %d, want 2", got)
	}
}

func TestRestoreRefusesATamperedRecord(t *testing.T) {
	stored := chainOf(t, 3)
	tampered := make([]Record, len(stored))
	copy(tampered, stored)
	// Change the content without changing the stored hash. This is what an attacker with
	// write access to the table would do, and it is the case linkage alone cannot catch,
	// because the previous-hash links still point at the right predecessors.
	tampered[1].Reason = "approved by nobody"

	c := NewChain()
	if err := c.Restore(tampered); err == nil {
		t.Fatal("a record whose content no longer matches its stored hash must be refused; " +
			"restoring it would rebuild a chain over altered evidence")
	}
	if got := c.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("a refused restore left sequence %d behind; it must apply nothing at all", got)
	}
}

func TestRestoreRefusesAGapInTheSequence(t *testing.T) {
	stored := chainOf(t, 3)
	withGap := []Record{stored[0], stored[2]} // sequence 2 deleted

	c := NewChain()
	err := c.Restore(withGap)
	if err == nil {
		t.Fatal("a restore with a deleted record must be refused")
	}
	// A chain with a hole in it would let the next append fill the gap with a record that
	// links to nothing, so the refusal is the whole point rather than a nicety.
	if got := c.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("a refused restore applied %d record(s)", got)
	}
}

func TestRestoreRefusesAReorderedArchive(t *testing.T) {
	stored := chainOf(t, 3)
	swapped := []Record{stored[0], stored[2], stored[1]}

	c := NewChain()
	if err := c.Restore(swapped); err == nil {
		t.Fatal("a reordered archive must be refused; a chain that sorted its input would " +
			"make reordering invisible by construction")
	}
}

func TestRestoreRefusesARecomputedButRelinkedChain(t *testing.T) {
	// The stronger tamper: rewrite the record AND recompute its hash, so the stored hash is
	// internally consistent. Only the previous-hash link to the preceding record gives this
	// away, which is why Restore checks it and not just the hash.
	stored := chainOf(t, 3)
	rewritten := make([]Record, len(stored))
	copy(rewritten, stored)
	rewritten[1].Reason = "approved by nobody"
	rehashed, err := NewRecord(rewritten[1])
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	rewritten[1] = rehashed

	c := NewChain()
	if err := c.Restore(rewritten); err == nil {
		t.Fatal("a record that was rewritten and rehashed must be refused on its link, or a " +
			"forged record with a valid hash of itself would be accepted")
	}
}

func TestRestoreRefusesAPartitionThatDoesNotStartAtGenesis(t *testing.T) {
	stored := chainOf(t, 3)
	// Drop the first record: the partition now opens at sequence 2, linked to genesis.
	c := NewChain()
	if err := c.Restore(stored[1:]); err == nil {
		t.Fatal("a partition that does not begin at sequence 1 must be refused")
	}
}

func TestRestoreRefusesIntoAChainThatHasAlreadyStarted(t *testing.T) {
	stored := chainOf(t, 2)
	c := NewChain()
	if _, err := c.Append([]Record{stagedRecord("aud-live", "tenant-b")}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	if err := c.Restore(stored); err == nil {
		t.Fatal("restoring into a chain that already holds records must be refused; the two " +
			"histories would interleave at the same sequence numbers and every record would " +
			"still hash correctly")
	}
	if got := c.LastSequence("tenant-b"); got != 1 {
		t.Fatalf("a refused restore disturbed the live chain: tenant-b is at %d, want 1", got)
	}
}

func TestRestoreRefusesADuplicateAuditID(t *testing.T) {
	stored := chainOf(t, 2)
	doubled := []Record{stored[0], stored[0]}

	c := NewChain()
	if err := c.Restore(doubled); err == nil {
		t.Fatal("the same audit_id twice must be refused; one identity cannot carry two records")
	}
}

func TestRestoreAppliesNothingWhenAnyRecordIsRefused(t *testing.T) {
	stored := chainOf(t, 3)
	tampered := make([]Record, len(stored))
	copy(tampered, stored)
	tampered[2].Action = "something else entirely"

	c := NewChain()
	if err := c.Restore(tampered); err == nil {
		t.Fatal("expected the tampered record to be refused")
	}
	// A partial restore would leave a chain that looks usable and is not, and the next
	// append would build on records whose linkage was never established.
	if c.LastSequence("tenant-a") != 0 {
		t.Fatal("a refused restore left a partially applied chain behind")
	}
	if len(c.Records("tenant-a")) != 0 {
		t.Fatal("a refused restore left records retrievable")
	}
	if _, err := c.Append([]Record{stagedRecord("aud-after", "tenant-a")}); err != nil {
		t.Fatalf("a chain whose restore was refused must still be usable: %v", err)
	}
}

func TestRestoreHandlesSeveralPartitionsIndependently(t *testing.T) {
	c := NewChain()
	staged := []Record{
		stagedRecord("aud-a1", "tenant-a"),
		stagedRecord("aud-b1", "tenant-b"),
		stagedRecord("aud-a2", "tenant-a"),
		stagedRecord("aud-b2", "tenant-b"),
	}
	accepted, err := c.Append(staged)
	if err != nil {
		t.Fatalf("Append: %v", err)
	}

	restored := NewChain()
	if err := restored.Restore(accepted); err != nil {
		t.Fatalf("Restore: %v", err)
	}
	for _, partition := range []string{"tenant-a", "tenant-b"} {
		if got := restored.LastSequence(partition); got != 2 {
			t.Fatalf("partition %s restored to sequence %d, want 2", partition, got)
		}
	}
	if names := restored.Partitions(); len(names) != 2 {
		t.Fatalf("restored partitions = %v, want two", names)
	}
}

func TestRestoreOfAnEmptyArchiveLeavesAnEmptyChain(t *testing.T) {
	c := NewChain()
	if err := c.Restore(nil); err != nil {
		t.Fatalf("restoring nothing must succeed, not fail: %v", err)
	}
	if c.LastSequence("tenant-a") != 0 {
		t.Fatal("an empty restore changed the chain")
	}
}

func TestRestoreRefusesARelinkedGapThatTheHashChainCannotSee(t *testing.T) {
	// Deleting a record from a real archive and relinking the survivor leaves a chain whose
	// hash linkage is completely intact, so the previous-hash check passes and only the
	// sequence check can refuse. This test exists because the plain gap test passes for the
	// wrong reason: in a real archive with a record removed the link check fires first, so
	// deleting the sequence check changes nothing there and the suite would still be green
	// with the check gone.
	stored := chainOf(t, 3)
	relinked := stored[2]
	relinked.PreviousHash = stored[0].RecordHash // skip over the deleted record
	rehashed, err := NewRecord(relinked)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	relinked = rehashed

	c := NewChain()
	if err := c.Restore([]Record{stored[0], relinked}); err == nil {
		t.Fatal("a relinked archive that skips a sequence must be refused; the next append " +
			"would otherwise be handed the sequence number of evidence that no longer exists")
	}
}

func TestRestoreRefusesAReusedAuditIDInsideAnOtherwiseValidChain(t *testing.T) {
	// A well-formed chain that reuses an identity for its last record. Sequence and linkage
	// are both correct, so only the identity check can refuse. Without this test the
	// duplicate check could be deleted and every other test would still pass, because the
	// only other duplicate test trips the sequence check first.
	stored := chainOf(t, 2)
	forged := fixtureRecord()
	forged.AuditID = stored[0].AuditID // one identity, two records
	forged.Partition = "tenant-a"
	forged.Sequence = stored[1].Sequence + 1
	forged.PreviousHash = stored[1].RecordHash
	hashed, err := NewRecord(forged)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}

	c := NewChain()
	if err := c.Restore(append(append([]Record{}, stored...), hashed)); err == nil {
		t.Fatal("a record reusing an audit_id already in the archive must be refused")
	}
}

func TestARestoredChainVerifies(t *testing.T) {
	// The reason a restore has to rebuild the linkage rather than just the counters: a
	// chain restored without its links would continue correctly from a sequence number and
	// verify as broken, which is the worst outcome because it looks alive.
	stored := chainOf(t, 4)
	restored := NewChain()
	if err := restored.Restore(stored); err != nil {
		t.Fatalf("Restore: %v", err)
	}
	after, err := restored.Append([]Record{stagedRecord("aud-e", "tenant-a")})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	v := NewVerifier(NewKeyRing())
	if got := v.Verify(append(append([]Record{}, stored...), after...), nil); !got.OK {
		t.Fatalf("a restored and extended chain must verify, got %v", got.Findings)
	}
}
