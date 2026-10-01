// Package bootstrap composes the control plane's durable stack.
//
// Until now every piece of that stack existed and every piece had been tested, and nothing
// assembled them. Each package offered constructors - a chain, a bounded guard, an exporter,
// stores and readers, and rehydrating constructors that rebuild a journal and a workload
// registry from durable state - and no production code path called any of them. Two
// consequences were recorded as open blockers rather than as bugs: WI-117's AC4 stayed
// unimplemented because the audit exporter was constructed by nothing outside its own test, and
// the audit trail could not be shown to survive a restart because no process ever rehydrated a
// journal.
//
// This package is the missing assembly.
//
// It composes over ports rather than over query interfaces. Each component already exposes the
// narrow interface it consumes - Sink, ChainReader, Store, SnapshotReader, IdentityStore,
// IdentitySnapshotReader - and depending on those rather than on SQL accessors is what lets the
// wiring be tested at all: a composition root is exactly the code most likely to be wrong in an
// order nobody notices, and the in-memory implementations behind those ports can drive it
// without a database.
//
// It is not a process entrypoint. It opens no socket, reads no configuration, and starts no
// server. What it establishes is that the durable stack can be built and rebuilt over persisted
// state, which is the part that was missing and the part a restart depends on.
package bootstrap

import (
	"context"
	"errors"
	"fmt"
	"reflect"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/danarprastika/web-trade/services/control-plane/model"
)

// Deps are the durable ports the stack is assembled over, plus the facts that are properties of
// the deployment rather than of any one component.
type Deps struct {
	// Clock supplies occurred_at and recorded_at. Required: audit timestamps are load-bearing
	// and must not default to the wall clock by omission.
	Clock func() time.Time

	// Environment places every audit record. Required, because the audit chain refuses a blank
	// environment and a placement nobody supplied is not a placement.
	Environment string

	// GuardLimit is the bounded audit backlog. Required and positive, because a guard with no
	// limit is an unbounded queue wearing the name of a bound.
	GuardLimit int

	// Partitions are the audit partitions to rehydrate.
	//
	// Rehydrate takes them explicitly because there is no "list partitions" query, and
	// deriving them from the models that happen to exist would silently skip a partition whose
	// models were all deleted - which is precisely the partition whose audit trail would then
	// be lost. Supplying them is the caller's decision and the caller's risk.
	Partitions []string

	// Sink persists accepted audit records.
	Sink audit.Sink

	// CheckpointSigner signs the checkpoint that closes each exported batch of audit records.
	//
	// Required, and required for the same reason the clock and the environment are. Those two
	// describe facts about the deployment; this is a third, and a deployment with none cannot
	// produce the anchor that makes a truncated archive detectable. Without it the audit trail
	// stays internally consistent, hashes correctly, and can still have had its tail deleted -
	// which is the state the anchored restore exists to refuse.
	//
	// It is not handed to the sink, because the caller built the sink and built it with this
	// signer; repeating the wiring here would only be a second chance to disagree with itself.
	// The requirement is restated anyway because Build is where a deployment declares what it
	// is composed of, and a stack assembled without a signer is one whose evidence nothing
	// vouches for. So the refusal exists at both layers: audit refuses to build a sink that
	// cannot anchor, and this refuses to assemble a deployment that has no signer to build it
	// with.
	CheckpointSigner audit.Signer

	// ChainReader reads stored audit records back for rehydration.
	ChainReader audit.ChainReader

	// Store persists registry rows and transition idempotency.
	Store model.Store

	// Snapshot reads the registry back for rehydration.
	Snapshot model.SnapshotReader

	// Identity persists workload identity issuance and revocation.
	Identity model.IdentityStore

	// Identities reads identity and revocation rows back for rehydration.
	Identities model.IdentitySnapshotReader
}

// Stack is the assembled durable control plane.
//
// The components are exported because assembling them is the whole job: a caller that needs to
// export accepted audit records needs the exporter, and a caller that needs to know whether it
// can still accept operations needs the guard.
type Stack struct {
	// Chain is the audit chain, rehydrated from stored records before anything else is built.
	Chain *audit.Chain

	// Guard holds accepted records not yet durably stored, and latches fail-closed at its
	// limit. Exported because whether it is halted is not something a caller should have to
	// infer.
	Guard *audit.Guard

	// Exporter drains that backlog into the sink.
	//
	// Constructing it here is what closes WI-117's AC4. Without an exporter the guard latches
	// at its limit with no producer for its exit condition, and no wiring downstream can repair
	// that: the backlog is reduced by exactly this one function.
	Exporter *audit.Exporter

	// Sink persists accepted audit records.
	Sink audit.Sink

	// Journal is the model registry's write path, rehydrated from the registry snapshot and
	// verified against the chain.
	Journal *model.Journal

	// Registry holds workload identities, rehydrated from persisted issuance and revocation.
	Registry *model.WorkloadRegistry

	// Store and Identity are the durable ports the two components above write through.
	Store    model.Store
	Identity model.IdentityStore
}

// Build assembles the durable stack over persisted state.
//
// The order is load-bearing, and each step sits where it does for a reason:
//
//  1. The chain is rehydrated first. The journal verifies every model in the snapshot against
//     the chain, so a journal restored against an empty chain would refuse every model it
//     should accept - and would refuse them for a reason that looks like tampering.
//  2. The exporter is built before the journal. It is the only producer of the guard's exit
//     condition, and a stack whose guard cannot drain will halt on operations that were
//     succeeding.
//  3. The journal is rehydrated rather than constructed empty. A control plane that started
//     with an empty registry would report every already-registered model as unknown, and the
//     caller's natural response - register it again - would write a second SUCCEEDED record
//     for a registration that already happened.
//
// A refusal at any step returns an error and no Stack, so a caller can never receive a
// half-assembled stack and mistake it for a working one.
func Build(ctx context.Context, d Deps) (*Stack, error) {
	if err := validate(d); err != nil {
		return nil, err
	}

	chain := audit.NewChain()
	if err := audit.Rehydrate(ctx, chain, d.ChainReader, d.Partitions); err != nil {
		return nil, fmt.Errorf("rehydrating the audit chain: %w", err)
	}

	guard, err := audit.NewGuard(d.GuardLimit)
	if err != nil {
		return nil, fmt.Errorf("building the audit backlog guard: %w", err)
	}

	exporter, err := audit.NewExporter(guard, d.Sink)
	if err != nil {
		return nil, fmt.Errorf("building the audit exporter: %w", err)
	}

	journal, err := model.RehydratedJournal(ctx, chain, d.Clock, d.Environment, d.Store, d.Snapshot)
	if err != nil {
		return nil, fmt.Errorf("rehydrating the model journal: %w", err)
	}

	registry, err := model.RehydratedWorkloadRegistry(ctx, d.Clock, d.Identity, d.Identities)
	if err != nil {
		return nil, fmt.Errorf("rehydrating the workload registry: %w", err)
	}

	return &Stack{
		Chain:    chain,
		Guard:    guard,
		Exporter: exporter,
		Sink:     d.Sink,
		Journal:  journal,
		Registry: registry,
		Store:    d.Store,
		Identity: d.Identity,
	}, nil
}

// validate refuses an incomplete Deps before anything is built.
//
// Every field is checked rather than defaulted, because a default here does not degrade
// quietly: a nil clock produces audit records with the wrong timestamps, a blank environment
// produces records the chain rejects outright, a non-positive guard limit produces a backlog
// with no bound, and no checkpoint signer produces audit evidence that nothing has promised
// reaches any particular sequence - a gap the anchored restore is built to catch and could not
// catch if nothing ever wrote the anchor. Partitions are the one exception - an unwritten deployment genuinely
// has none, and refusing to boot would make the empty case the only case that cannot start.
//
// The components downstream carry their own guards. These exist so a caller assembling the
// stack is told what it forgot, rather than discovering it several layers down or, worse,
// succeeding with a nil that a later dereference turns into a panic.
func validate(d Deps) error {
	if d.Clock == nil {
		return errors.New("bootstrap requires a clock; occurred_at and recorded_at are " +
			"load-bearing audit fields and cannot be defaulted to the wall clock by omission")
	}
	if d.Environment == "" {
		return errors.New("bootstrap requires a deployment environment; the audit chain refuses " +
			"a record that cannot be placed, and a placement nobody supplied is not one")
	}
	if d.GuardLimit <= 0 {
		return fmt.Errorf(
			"bootstrap requires a positive audit backlog limit; %d would be an unbounded "+
				"queue wearing the name of a bound", d.GuardLimit)
	}

	// Checked in a fixed order with one message each, so the refusal a caller sees is the same
	// on every run and names the specific thing that is missing.
	for _, dep := range []struct {
		name  string
		value any
	}{
		{"a sink for accepted audit records", d.Sink},
		{"a signer for the audit checkpoints that anchor each exported batch", d.CheckpointSigner},
		{"a reader to rehydrate the audit chain from", d.ChainReader},
		{"a durable store for the model registry", d.Store},
		{"a reader to rehydrate the model registry from", d.Snapshot},
		{"a durable store for workload identity", d.Identity},
		{"a reader to rehydrate workload identity from", d.Identities},
	} {
		if isNil(dep.value) {
			return fmt.Errorf("bootstrap requires %s", dep.name)
		}
	}
	return nil
}

// isNil reports whether a dependency was left unset, including when it was assigned a typed nil
// rather than left unassigned. A typed nil satisfies its interface, so the plain `== nil`
// comparison would wave through a dependency that panics the moment it is used.
func isNil(q any) bool {
	if q == nil {
		return true
	}
	value := reflect.ValueOf(q)
	switch value.Kind() {
	case reflect.Ptr, reflect.Interface, reflect.Map, reflect.Slice, reflect.Func, reflect.Chan:
		return value.IsNil()
	default:
		return false
	}
}
