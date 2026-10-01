package audit

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// stagedRecord returns a valid record for the given identity, at whatever position the
// chain assigns it. Sequence and previous hash are deliberately left unset.
func stagedRecord(auditID, partition string) Record {
	r := fixtureRecord()
	r.AuditID = auditID
	r.Partition = partition
	r.Sequence = 0
	r.PreviousHash = GenesisHash
	return r
}

func TestSequenceIsMonotonicWithinAPartition(t *testing.T) {
	c := NewChain()
	out, err := c.Append([]Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
		stagedRecord("aud-3", "tenant-a"),
	})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	for i, r := range out {
		if want := int64(i + 1); r.Sequence != want {
			t.Fatalf("record %d got sequence %d, want %d", i, r.Sequence, want)
		}
	}
}

func TestPreviousHashLinksToThePrecedingRecord(t *testing.T) {
	c := NewChain()
	out, err := c.Append([]Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
		stagedRecord("aud-3", "tenant-a"),
	})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}

	if !out[0].PreviousHash.IsZero() {
		t.Fatal("the first record in a partition must link to genesis")
	}
	for i := 1; i < len(out); i++ {
		if out[i].PreviousHash != out[i-1].RecordHash {
			t.Fatalf("record %d does not link to its predecessor", i)
		}
	}
}

// Partitions are chained independently. A record in one tenant must not reveal or
// depend on another tenant's activity.
func TestPartitionsChainIndependently(t *testing.T) {
	c := NewChain()
	if _, err := c.Append([]Record{
		stagedRecord("aud-a1", "tenant-a"),
		stagedRecord("aud-b1", "tenant-b"),
		stagedRecord("aud-a2", "tenant-a"),
	}); err != nil {
		t.Fatalf("Append: %v", err)
	}

	a := c.Records("tenant-a")
	if len(a) != 2 {
		t.Fatalf("tenant-a has %d records, want 2", len(a))
	}
	if a[1].PreviousHash != a[0].RecordHash {
		t.Fatal("tenant-a's second record must link to its first, not to tenant-b's")
	}
	if c.LastSequence("tenant-b") != 1 {
		t.Fatal("tenant-b must be at sequence 1")
	}
}

func TestAStatedSequenceThatDisagreesIsRefused(t *testing.T) {
	c := NewChain()
	if _, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")}); err != nil {
		t.Fatalf("Append: %v", err)
	}

	bad := stagedRecord("aud-2", "tenant-a")
	bad.Sequence = 99
	if _, err := c.Append([]Record{bad}); err == nil {
		t.Fatal("a record stating a sequence that is not next must be refused")
	}
}

func TestAStatedCorrectSequenceIsAccepted(t *testing.T) {
	c := NewChain()
	if _, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	good := stagedRecord("aud-2", "tenant-a")
	good.Sequence = 2
	out, err := c.Append([]Record{good})
	if err != nil {
		t.Fatalf("a correct stated sequence must be accepted: %v", err)
	}
	if out[0].Sequence != 2 {
		t.Fatalf("got sequence %d, want 2", out[0].Sequence)
	}
}

// A partially-applied batch would leave a hole no writer intended.
func TestAppendIsAtomicAcrossTheBatch(t *testing.T) {
	c := NewChain()
	bad := stagedRecord("aud-2", "tenant-a")
	bad.ActorType = ActorType("NOT_A_REAL_ACTOR")

	if _, err := c.Append([]Record{
		stagedRecord("aud-1", "tenant-a"),
		bad,
		stagedRecord("aud-3", "tenant-a"),
	}); err == nil {
		t.Fatal("a batch containing an invalid record must be refused")
	}

	if got := c.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("a refused batch must leave the chain untouched, but the partition is at sequence %d", got)
	}
	if len(c.Records("tenant-a")) != 0 {
		t.Fatal("a refused batch must write no records")
	}
}

// docs/22 section 7 requires duplicate delivery to be idempotent.
func TestDuplicateDeliveryIsIdempotent(t *testing.T) {
	c := NewChain()
	first, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")})
	if err != nil {
		t.Fatalf("first Append: %v", err)
	}

	// A redelivery that does not restate its sequence or previous hash, because the
	// chain assigns those rather than the caller.
	second, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")})
	if err != nil {
		t.Fatalf("redelivery must be accepted as a no-op, got: %v", err)
	}
	if second[0].RecordHash != first[0].RecordHash {
		t.Fatal("a redelivery must return the record already on the chain")
	}
	if c.LastSequence("tenant-a") != 1 {
		t.Fatalf("a redelivery must not advance the chain, partition is at %d", c.LastSequence("tenant-a"))
	}
	if len(c.Records("tenant-a")) != 1 {
		t.Fatalf("a redelivery must not append a second record, have %d", len(c.Records("tenant-a")))
	}
}

// Reusing an identity for different content is a conflict, not an update. The chain
// holds no update method precisely so this cannot be resolved silently.
func TestReusingAnIdentityForDifferentContentIsRefused(t *testing.T) {
	c := NewChain()
	if _, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")}); err != nil {
		t.Fatalf("Append: %v", err)
	}

	changed := stagedRecord("aud-1", "tenant-a")
	changed.Action = "ORDER_CANCELLED"
	if _, err := c.Append([]Record{changed}); err == nil {
		t.Fatal("reusing an audit_id for different content must be refused")
	}
}

// One identity, one record - including inside a single batch. byAuditID is only written in
// the commit loop, so before this check a batch naming the same audit_id twice staged two
// records at consecutive sequences: the pair was accepted, exported durably, and then
// refused by Restore on the next startup, which is a partition that can never be rehydrated
// again. Both variants are refused, and the identical one is the interesting one: it looks
// like a harmless retry and is exactly as unrecoverable.
func TestAppendRefusesAnAuditIDRepeatedWithinOneBatch(t *testing.T) {
	for name, second := range map[string]func(Record) Record{
		"identical record": func(r Record) Record { return r },
		"different content": func(r Record) Record {
			r.Action = "ORDER_CANCELLED"
			return r
		},
	} {
		t.Run(name, func(t *testing.T) {
			c := NewChain()
			doubled := stagedRecord("aud-1", "tenant-a")
			if _, err := c.Append([]Record{doubled, second(doubled)}); err == nil {
				t.Fatal("two records sharing an audit_id in one batch must be refused")
			}
			// A refused batch writes nothing, which is the point: a half-written identity is
			// the state the audit_id primary key exists to make impossible.
			if got := c.LastSequence("tenant-a"); got != 0 {
				t.Fatalf("a refused batch left the partition at sequence %d", got)
			}
			if len(c.Records("tenant-a")) != 0 {
				t.Fatalf("a refused batch wrote %d record(s)", len(c.Records("tenant-a")))
			}
		})
	}
}

// The within-batch refusal must not reach the redelivery path, which is a different case:
// docs/22 section 7 requires a retry of an earlier delivery to be idempotent, and the retry
// arrives in its own batch rather than doubling up inside one.
func TestAppendStillAcceptsARedeliveryInALaterBatch(t *testing.T) {
	c := NewChain()
	first, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")})
	if err != nil {
		t.Fatalf("first Append: %v", err)
	}
	second, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")})
	if err != nil {
		t.Fatalf("a redelivery in a later batch must remain idempotent: %v", err)
	}
	if second[0].RecordHash != first[0].RecordHash || c.LastSequence("tenant-a") != 1 {
		t.Fatal("the redelivery was not recognised as the record already on the chain")
	}
}

// The duplicate is refused wherever it appears in the batch, not only at the front, and a
// batch whose later half is refused writes none of its earlier records.
func TestAppendRefusesADuplicateThatArrivesAfterOtherRecords(t *testing.T) {
	c := NewChain()
	batch := []Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
		stagedRecord("aud-1", "tenant-a"),
	}
	if _, err := c.Append(batch); err == nil {
		t.Fatal("a duplicate identity in the last position must be refused too")
	}
	if got := c.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("the two records before the duplicate were written anyway (sequence %d); "+
			"Append is all-or-nothing across the batch", got)
	}
}

func TestRecordsAreAppendOnlyThroughTheChain(t *testing.T) {
	c := NewChain()
	if _, err := c.Append([]Record{stagedRecord("aud-1", "tenant-a")}); err != nil {
		t.Fatalf("Append: %v", err)
	}

	// Mutating the returned slice must not reach the chain's state.
	got := c.Records("tenant-a")
	got[0].Action = "TAMPERED"
	got[0].Sequence = 42

	again := c.Records("tenant-a")
	if again[0].Action == "TAMPERED" || again[0].Sequence == 42 {
		t.Fatal("a caller must not be able to mutate the chain through a returned slice")
	}
}

func TestEvidenceIsQueryableByCorrelationID(t *testing.T) {
	c := NewChain()
	a := stagedRecord("aud-1", "tenant-a")
	b := stagedRecord("aud-2", "tenant-b")
	other := stagedRecord("aud-3", "tenant-a")
	other.CorrelationID = "cor-other"

	if _, err := c.Append([]Record{a, b, other}); err != nil {
		t.Fatalf("Append: %v", err)
	}

	found := c.ByCorrelationID(fixtureRecord().CorrelationID)
	if len(found) != 2 {
		t.Fatalf("found %d records for the correlation id, want 2", len(found))
	}
	// A workflow crossing tenants must come back whole, ordered deterministically.
	if found[0].AuditID != "aud-1" || found[1].AuditID != "aud-2" {
		t.Fatalf("unexpected order: %s, %s", found[0].AuditID, found[1].AuditID)
	}
}

func TestByCorrelationIDIgnoresBlankInput(t *testing.T) {
	c := NewChain()
	if got := c.ByCorrelationID("  "); got != nil {
		t.Fatal("a blank correlation id must return nothing")
	}
}

func TestRecordWithoutActorIsRefused(t *testing.T) {
	for name, mutate := range map[string]func(*Record){
		"no audit id":    func(r *Record) { r.AuditID = "" },
		"no partition":   func(r *Record) { r.Partition = "" },
		"no actor id":    func(r *Record) { r.ActorID = "" },
		"bad actor type": func(r *Record) { r.ActorType = ActorType("ROBOT") },
		"no action":      func(r *Record) { r.Action = "" },
		"no environment": func(r *Record) { r.Environment = "" },
		"bad result":     func(r *Record) { r.Result = Result("MAYBE") },
		"no recorded at": func(r *Record) { r.RecordedAt = contracts.Timestamp{} },
		"no occurred at": func(r *Record) { r.OccurredAt = contracts.Timestamp{} },
	} {
		t.Run(name, func(t *testing.T) {
			r := stagedRecord("aud-1", "tenant-a")
			mutate(&r)
			if _, err := NewChain().Append([]Record{r}); err == nil {
				t.Fatal("must be refused")
			}
		})
	}
}

func TestAnEmptyBatchIsAcceptedAndWritesNothing(t *testing.T) {
	c := NewChain()
	out, err := c.Append(nil)
	if err != nil {
		t.Fatalf("Append(nil): %v", err)
	}
	if len(out) != 0 {
		t.Fatalf("got %d records, want 0", len(out))
	}
	if c.LastSequence("tenant-a") != 0 {
		t.Fatal("an empty batch must not touch any partition")
	}
}

func TestPartitionsAreReturnedSorted(t *testing.T) {
	c := NewChain()
	if _, err := c.Append([]Record{
		stagedRecord("aud-z", "tenant-z"),
		stagedRecord("aud-a", "tenant-a"),
		stagedRecord("aud-m", "tenant-m"),
	}); err != nil {
		t.Fatalf("Append: %v", err)
	}
	got := c.Partitions()
	want := []string{"tenant-a", "tenant-m", "tenant-z"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("got %v, want %v", got, want)
	}
}
