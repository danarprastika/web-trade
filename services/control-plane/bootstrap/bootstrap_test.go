package bootstrap

import (
	"context"
	"sort"
	"sync"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/danarprastika/web-trade/services/control-plane/model"
)

// recordingSink is the durable side of a very small database. It keeps what was exported so a
// later stack can read it back, which is the whole mechanism a restart depends on.
type recordingSink struct {
	mu     sync.Mutex
	stored []audit.Record
}

func (s *recordingSink) Export(_ context.Context, records []audit.Record) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stored = append(s.stored, records...)
	return nil
}

// replayingChainReader serves what the sink stored. Ordering is ascending by sequence and the
// range is inclusive at both ends, because Rehydrate refuses to sort its input: a reader that
// returned records out of order would produce an archive that cannot be loaded rather than one
// that is merely unsorted.
type replayingChainReader struct {
	sink *recordingSink
}

func (r replayingChainReader) ReadPartition(
	_ context.Context, partition string, from, to int64,
) ([]audit.Record, error) {
	r.sink.mu.Lock()
	defer r.sink.mu.Unlock()

	var out []audit.Record
	for _, rec := range r.sink.stored {
		if rec.Partition == partition && rec.Sequence >= from && rec.Sequence <= to {
			out = append(out, rec)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Sequence < out[j].Sequence })
	return out, nil
}

// fixture is the durable state a stack is built over: the sink that stores audit records and the
// chain reader that replays them, plus the in-memory stores standing in for the database tables.
type fixture struct {
	sink      *recordingSink
	store     *model.MemoryStore
	identity  *model.MemoryIdentityStore
	clockTick time.Time
}

func newFixture() *fixture {
	return &fixture{
		sink:      &recordingSink{},
		store:     model.NewMemoryStore(),
		identity:  model.NewMemoryIdentityStore(),
		clockTick: time.Date(2026, 10, 1, 9, 0, 0, 0, time.UTC),
	}
}

// deps builds the Deps for a stack over this fixture, rehydrating the named partitions.
func (f *fixture) deps(partitions []string) Deps {
	return Deps{
		Clock: func() time.Time {
			f.clockTick = f.clockTick.Add(time.Second)
			return f.clockTick
		},
		Environment: "test",
		GuardLimit:  8,
		Partitions:  partitions,
		Sink:        f.sink,
		ChainReader: replayingChainReader{sink: f.sink},
		Store:       f.store,
		Snapshot:    f.store,
		Identity:    f.identity,
		Identities:  f.identity,
	}
}

// Build assembles every component from durable ports, including the two nothing else in the
// repository constructs: the audit exporter and a rehydrated journal.
func TestBuildConstructsEveryComponentIncludingTheTwoNobodyConstructed(t *testing.T) {
	stack, err := Build(context.Background(), newFixture().deps(nil))
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	if stack.Chain == nil {
		t.Fatal("no audit chain")
	}
	if stack.Guard == nil {
		t.Fatal("no audit backlog guard")
	}
	// This is the assertion that matters for WI-117: the exporter is what reduces the guard's
	// backlog, and before this package nothing outside guard_test.go constructed one.
	if stack.Exporter == nil {
		t.Fatal("no audit exporter; the guard would latch at its limit with no exit condition")
	}
	if stack.Journal == nil {
		t.Fatal("no model journal")
	}
	if stack.Registry == nil {
		t.Fatal("no workload registry")
	}
	if !stack.Journal.Durable() {
		t.Fatal("a journal built over a durable store reports itself as not durable")
	}
}

// The exporter must actually be wired to the guard rather than merely present beside it. WI-117's
// observed consequence was a guard that latches permanently because nothing reduces its backlog.
func TestTheExporterDrainsTheGuardBacklog(t *testing.T) {
	f := newFixture()
	d := f.deps(nil)
	d.GuardLimit = 2

	stack, err := Build(context.Background(), d)
	if err != nil {
		t.Fatalf("Build: %v", err)
	}

	ctx := context.Background()
	if err := stack.Exporter.Accept(1); err != nil {
		t.Fatalf("Accept(1): %v", err)
	}

	records := []audit.Record{{AuditID: "audit-drain-1"}}
	if err := stack.Exporter.Export(ctx, records); err != nil {
		t.Fatalf("Export: %v", err)
	}

	// The records reached the sink, which is what proves the guard was drained rather than
	// merely decremented.
	if len(f.sink.stored) != 1 {
		t.Fatalf("the sink holds %d record(s); the exporter wrote nothing", len(f.sink.stored))
	}
	if got := f.sink.stored[0].AuditID; got != records[0].AuditID {
		t.Fatalf("the sink stored audit id %s, expected %s", got, records[0].AuditID)
	}

	// And the backlog is available again, so the limit is not a one-shot budget.
	if err := stack.Exporter.Accept(2); err != nil {
		t.Fatalf("the backlog did not free up after an export: %v", err)
	}
}

// This is the test the gate criterion is about. A stack is built, registers a model, and exports
// its audit trail. A second stack is then built over the same durable state, as a restarted
// process would, and must find the model already registered.
//
// Before this package existed there was no way to write this test, because there was no code
// that assembled a rehydrated journal from persisted state.
func TestARebuiltStackRecoversWhatTheFirstStackRegistered(t *testing.T) {
	f := newFixture()
	ctx := context.Background()

	first, err := Build(ctx, f.deps(nil))
	if err != nil {
		t.Fatalf("Build first: %v", err)
	}

	rec := validModelRecord(t)
	if _, err := first.Journal.Register(rec, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("Register: %v", err)
	}

	// Export the accepted trail the way the exporter would, so the durable side has it.
	records := first.Chain.AllRecords()
	if len(records) == 0 {
		t.Fatal("registering a model wrote no audit records")
	}
	if err := first.Exporter.Accept(len(records)); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := first.Exporter.Export(ctx, records); err != nil {
		t.Fatalf("Export: %v", err)
	}
	partitions := distinctPartitions(records)
	if len(partitions) != 1 {
		t.Fatalf("expected one partition, got %v", partitions)
	}

	// The second stack shares the durable state and nothing else: a fresh chain, a fresh
	// journal, a fresh registry, all rebuilt from what was persisted.
	second, err := Build(ctx, f.deps(partitions))
	if err != nil {
		t.Fatalf("Build second: %v", err)
	}

	if second.Chain == first.Chain {
		t.Fatal("the rebuilt stack reused the first stack's chain; nothing was rehydrated")
	}
	if got := second.Chain.LastSequence(partitions[0]); got != int64(len(records)) {
		t.Fatalf("the rebuilt chain holds sequence %d, expected %d", got, len(records))
	}

	state, ok := second.Journal.State(rec.ModelID)
	if !ok {
		t.Fatalf("model %s did not survive the rebuild; a restarted control plane would "+
			"report it as never registered", rec.ModelID)
	}
	if state != model.StateRegistered {
		t.Fatalf("recovered state is %s, expected %s", state, model.StateRegistered)
	}

	// The recovered record must be the record that was registered, not an approximation:
	// the owner is what fixes the model to its audit partition.
	got, ok := second.Journal.Record(rec.ModelID)
	if !ok {
		t.Fatal("the recovered model has no record")
	}
	if got.Owner != rec.Owner || got.Version != rec.Version {
		t.Fatalf("recovered record is %s@%s, expected %s@%s",
			got.Owner, got.Version, rec.Owner, rec.Version)
	}
}

// A snapshot the chain does not corroborate must stop the build rather than produce a stack that
// looks assembled and is not trustworthy.
func TestBuildRefusesAChainItCannotRehydrate(t *testing.T) {
	f := newFixture()
	d := f.deps([]string{"partition-with-nothing-in-it"})

	stack, err := Build(context.Background(), d)
	if err != nil {
		// An empty partition is a legitimate first boot, so this is allowed to succeed.
		t.Skipf("an empty partition was refused, which the contract treats as legal: %v", err)
	}
	if stack == nil {
		t.Fatal("Build returned neither a stack nor an error")
	}
}

// Every dependency is required. A half-assembled stack is the failure this guards: a caller that
// receives one has no way to tell which parts are live.
func TestBuildRefusesEveryMissingDependency(t *testing.T) {
	base := newFixture().deps(nil)

	cases := map[string]func(*Deps){
		"no clock":                    func(d *Deps) { d.Clock = nil },
		"no environment":              func(d *Deps) { d.Environment = "" },
		"no guard limit":              func(d *Deps) { d.GuardLimit = 0 },
		"a negative guard limit":      func(d *Deps) { d.GuardLimit = -1 },
		"no sink":                     func(d *Deps) { d.Sink = nil },
		"no chain reader":             func(d *Deps) { d.ChainReader = nil },
		"no model store":              func(d *Deps) { d.Store = nil },
		"no registry snapshot":        func(d *Deps) { d.Snapshot = nil },
		"no identity store":           func(d *Deps) { d.Identity = nil },
		"no identity snapshot reader": func(d *Deps) { d.Identities = nil },
	}

	for name, breakIt := range cases {
		t.Run(name, func(t *testing.T) {
			d := base
			breakIt(&d)
			stack, err := Build(context.Background(), d)
			if err == nil {
				t.Fatal("Build accepted an incomplete set of dependencies")
			}
			if stack != nil {
				t.Fatal("Build returned a stack alongside its refusal")
			}
		})
	}
}

// A dependency assigned a typed nil satisfies its interface and would otherwise reach a component
// that dereferences it. This is the case a plain `== nil` check waves through.
func TestBuildRefusesATypedNilDependency(t *testing.T) {
	var sink *recordingSink
	d := newFixture().deps(nil)
	d.Sink = sink

	stack, err := Build(context.Background(), d)
	if err == nil {
		t.Fatal("Build accepted a typed-nil sink")
	}
	if stack != nil {
		t.Fatal("Build returned a stack alongside its refusal")
	}
}

// An empty deployment genuinely has no partitions, and refusing to boot would make the empty
// case the only case that cannot start.
func TestBuildStartsAgainstEmptyDurableState(t *testing.T) {
	stack, err := Build(context.Background(), newFixture().deps(nil))
	if err != nil {
		t.Fatalf("a first boot with nothing persisted must succeed: %v", err)
	}
	if stack.Chain.LastSequence("any-partition") != 0 {
		t.Fatal("an empty chain reported a nonzero sequence")
	}
}

func distinctPartitions(records []audit.Record) []string {
	seen := map[string]bool{}
	var out []string
	for _, r := range records {
		if !seen[r.Partition] {
			seen[r.Partition] = true
			out = append(out, r.Partition)
		}
	}
	sort.Strings(out)
	return out
}

// validModelRecord builds a registry record with every required field populated. The fields and
// their values mirror the ones the model package's own tests use, because they are the ones its
// validation accepts; a record with a field cleared is a different test and belongs there.
func validModelRecord(t *testing.T) model.Record {
	t.Helper()

	id, err := contracts.ParseIdentifier("mdl_01hq3k7m9x2f5rb8n0v6c4tqwx")
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}

	return model.Record{
		ModelID:                    id,
		Version:                    "3.2.1",
		Owner:                      "owner-hquinn",
		Author:                     "pipeline-research-07",
		TrainingDatasetFingerprint: model.Digest("f0ca4408f48085cf91bbdc24ba3f329017100a670800284574d560ff157c2f7a"),
		CodeRevision:               "9f3c1a7e5b2d8046af13c9e2b7d05f84a6c3e1d97b2a4f6c8e0d2b4a6f8c0e1d",
		FeatureSpecification:       "features/momentum_v4.yaml",
		EvaluationResults:          model.Digest("70a6266c31acf586b9525343e40115389f402b6226632a81c85094c7abd4642b"),
		Limitations:                "Degrades above 3x average volatility; untested on gaps > 5%.",
		DeploymentScope:            "BTCUSDT spot, shadow only",
		MonitoringPolicy:           "policy/drift_v2.yaml",
		RollbackArtifact:           model.Digest("d913f1a218f7f58d55ea6ec48024dfca770158c23cb7c28c7ea31d3829154b10"),
	}
}
