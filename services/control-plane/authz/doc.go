// Package authz decides whether a subject may attempt an action.
//
// Authority. This package answers exactly one question: may this subject attempt this
// operation, in this scope, at this auth strength, right now. It is the platform
// authorization authority (docs/21 section 1) and it is not, and cannot become, the
// financial-risk authority. The Risk Engine owns that. docs/21 section 4 and ADR-018
// state that authorization policy cannot approve or override financial risk, and this
// package is built so that following the rule does not require anyone to remember it:
// there is no decision, rule, or grant here that can express a risk approval, so no
// policy author can write one by mistake.
//
// The properties this package exists to make mechanical:
//
//  1. Deny by default. A request with no matching allow rule is refused. Authorization is
//     never the absence of a prohibition, because absence of a prohibition is the state a
//     forgotten rule leaves behind.
//
//  2. Explicit deny beats allow. If any rule denies, the request is refused even if a
//     narrower rule allows it. This is what makes a deny usable as a safety control
//     rather than only as a default.
//
//  3. Fail closed on stale context. An authorization context older than the configured
//     revocation window is not evaluated on its merits. docs/21 sections 3 and 10 require
//     denial when the identity or policy source is unavailable or stale, because the one
//     thing a stale cache cannot tell you is what changed while it was stale.
//
//  4. Server-side only. Every decision is a pure function of a server-held context. There
//     is no path by which a caller supplies its own decision, its own role list, or its
//     own policy version, so frontend visibility is never mistaken for a control.
//
// This package is pure domain logic. It reads no clock, no identity provider, and no
// network: time, the session, and the policy bundle are inputs, so a decision replays
// identically from a recorded request.
package authz
