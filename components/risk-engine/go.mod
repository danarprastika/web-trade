module github.com/danarprastika/web-trade/components/risk-engine

go 1.26.2

// The canonical contracts module is workspace-local. The version is a placeholder resolved
// by go.work to ./contracts/go, and the local replace guarantees no tool can silently
// satisfy this import from the network. The module path is a subpath of this repository's
// public remote, so an unpinned import here would let a resolver fetch contracts from a
// published commit instead of from the authoritative local source.
//
// The Risk Engine depends on the canonical contracts and on nothing else. In particular it
// does not depend on services/control-plane: a component that cannot reach a service cannot
// be handed authority by one, and the policy the engine evaluates is projected into
// risk.Policy rather than imported as the control plane's own type.
require github.com/danarprastika/web-trade/contracts/go v0.0.0

replace github.com/danarprastika/web-trade/contracts/go => ../../contracts/go
