module github.com/danarprastika/web-trade/services/control-plane

go 1.26.2

// The canonical contracts module is workspace-local. The version is a placeholder
// resolved by go.work to ./contracts/go; the empty version number makes that explicit, and
// combined with a local replace it guarantees no tool can silently satisfy this import from
// the network. The module path is a subpath of this repository's public remote, so an
// unpinned import here would let a resolver fetch contracts from a published commit instead
// of from the authoritative local source.
require (
	github.com/danarprastika/web-trade/components/oms v0.0.0
	github.com/danarprastika/web-trade/contracts/go v0.0.0
)

require github.com/lib/pq v1.10.9 // indirect

replace github.com/danarprastika/web-trade/contracts/go => ../../contracts/go

// The OMS is a test-only dependency of the control plane, used to drive real order state
// into the ledger so the reconciliation is proven against the state machine rather than
// against a hand-built quantity. Production code must not import it: the ledger trusts the
// OMS as an input, and importing it would let the two authorities call each other.
replace github.com/danarprastika/web-trade/components/oms => ../../components/oms
