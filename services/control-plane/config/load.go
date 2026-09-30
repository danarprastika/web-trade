package config

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// SchemaVersion is the configuration schema version this build understands.
//
// It is checked on load and compared against the document's own declared version. A
// document written for a different schema is refused rather than reinterpreted, because the
// canonical bytes of a document are only meaningful relative to a schema, and a signature
// that verified under an older field layout would otherwise be treated as covering fields
// this build does not even have.
const SchemaVersion = "1.0.0"

// Rejection is a refusal to accept a configuration snapshot.
//
// It mirrors the Rejection type in the strategy lifecycle package and for the same reason:
// a single formatted error cannot carry both the canonical wire code, which a caller on
// another service needs, and the local sentinel, which keeps errors.Is working in process.
// Formatting an ErrorCode with %w is not valid Go, and formatting it with %s would discard
// exactly the machine-readable part that must survive.
type Rejection struct {
	// Code is the canonical error code from docs/03.
	Code contracts.ErrorCode
	// Cause is the local sentinel, reachable through errors.Is.
	Cause error
	// Reason is the human-facing explanation. Never parsed.
	Reason string
}

func (r Rejection) Error() string { return fmt.Sprintf("%s: %s", r.Code, r.Reason) }

// Unwrap exposes the local sentinel to errors.Is and errors.As.
func (r Rejection) Unwrap() error { return r.Cause }

func reject(code contracts.ErrorCode, format string, args ...any) Rejection {
	return Rejection{Code: code, Cause: ErrInvalidConfig, Reason: fmt.Sprintf(format, args...)}
}

// Snapshot is a configuration revision that has passed every check and may be served.
type Snapshot struct {
	// Body is the signed content.
	Body Body
	// Digest is the recomputed digest of the canonical body. It is not the digest claimed
	// by the document, because the pipeline only succeeds when those two are equal, and
	// carrying the recomputed one means a later drift check compares against a value this
	// process derived itself rather than one it was handed.
	Digest string
	// ActivatedAt is when the revision took effect, for freshness arithmetic.
	ActivatedAt time.Time
	// Environment is the promotion stage.
	Environment Environment
}

// Revision returns the configuration revision identifier.
func (s Snapshot) Revision() string { return s.Body.Revision }

// LoadOptions are the inputs to the load pipeline that are not part of the document.
type LoadOptions struct {
	// Trust is the set of keys permitted to sign configuration.
	Trust *TrustStore
	// Now is the evaluation time. It is an argument rather than a call to time.Now so the
	// staleness check is testable at a boundary instead of only in the present, and so a
	// replay reproduces exactly.
	Now time.Time
	// Previous is the snapshot this one supersedes, if any. It is required for anything
	// above dev, so promotion is a chain rather than a free jump.
	Previous *Snapshot
	// RequireTwoPersonApproval is set by deployments that mandate the two-person rule for
	// every environment rather than only for live.
	RequireTwoPersonApproval bool
}

// Load decodes and verifies a configuration document.
//
// The order of the checks is the design, and each step can only be reached by clearing the
// previous one:
//
//  1. Strict decode. An unknown field is refused here. This is the whole of the
//     "no undocumented configuration" guarantee: a field this build does not know about
//     cannot enter a live snapshot, and it cannot be smuggled in as a comment-adjacent
//     field that the signature does not cover.
//  2. Schema version agreement, so the canonical bytes mean what this build thinks.
//  3. Structural validation of every policy dimension and every limit, which is the
//     fail-safe completeness gate from docs/17 section 2.
//  4. Approval validation, including the live two-person rule.
//  5. Digest agreement, then signature verification. A document whose claimed digest does
//     not match its own canonical form is a document that was edited, not one that was
//     re-signed.
//  6. Freshness, which needs the signature to have passed first. Age is only meaningful
//     for configuration whose provenance is established.
//  7. Promotion legality, which needs the freshness policy to have been validated.
//
// Signature verification deliberately precedes the policy checks' consequences but follows
// the structural ones. Structural checks are pure and cheap, so a malformed document is
// reported as malformed; the signature is verified before any policy value is trusted, so
// a document from an untrusted signer is reported as untrusted even when it is also
// incomplete. Reporting the signature failure first would tell a caller less about why the
// document was refused than reporting the structural failure first, and reporting the
// structural failure for an untrusted document would spend an attacker's budget of
// validation on a document that should never have been parsed as authoritative.
func Load(document []byte, opts LoadOptions) (Snapshot, error) {
	if opts.Trust == nil {
		return Snapshot{}, reject(contracts.CodeValidation, "no trust store supplied; "+
			"configuration cannot be verified without one")
	}
	if len(bytes.TrimSpace(document)) == 0 {
		return Snapshot{}, reject(contracts.CodeValidation, "configuration document is empty")
	}

	// Step 1: strict decode. DisallowUnknownFields is what makes the signed content and the
	// document content the same thing; see CanonicalBytes for why that equivalence matters.
	dec := json.NewDecoder(bytes.NewReader(document))
	dec.DisallowUnknownFields()
	var env Envelope
	if err := dec.Decode(&env); err != nil {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration does not match the schema exactly: %v", err)
	}
	// A second value in the stream is refused. Trailing content would be a second
	// configuration that the canonical bytes of the first do not describe, which is the
	// same smuggling shape as an unknown field.
	if dec.More() {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration document contains trailing content after the envelope")
	}

	b := env.Body

	// Step 2: schema version.
	if b.SchemaVersion != SchemaVersion {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration declares schema %q but this build implements %q; a document for a "+
				"different schema is refused rather than reinterpreted",
			b.SchemaVersion, SchemaVersion)
	}
	if !b.Environment.Valid() {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration names unknown environment %q", b.Environment)
	}
	if strings.TrimSpace(b.Revision) == "" {
		return Snapshot{}, reject(contracts.CodeValidation, "configuration has no revision")
	}
	if strings.TrimSpace(b.Supersedes) == "" {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration revision %q supersedes nothing; a promotion chain must be traceable",
			b.Revision)
	}
	if b.CreatedAt.IsZero() || b.ActivatedAt.IsZero() {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration must record both created_at and activated_at")
	}
	if b.ActivatedAt.Before(b.CreatedAt) {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration activated_at precedes created_at")
	}

	// Step 3: structural validation.
	if err := b.Policy.Validate(); err != nil {
		return Snapshot{}, asRejection(err)
	}
	if err := b.Freshness.Validate(); err != nil {
		return Snapshot{}, asRejection(err)
	}
	// The flag set is part of the configuration, so the closed set is enforced here rather
	// than left to whichever caller happens to call ResolveFlags. Leaving it to the caller
	// would make the guarantee depend on every consumer remembering, and a consumer that
	// forgot would read an undocumented flag as simply absent.
	if _, err := ResolveFlags(b.Flags); err != nil {
		return Snapshot{}, asRejection(err)
	}

	// Step 4: approval.
	if err := b.Approval.Validate(b.Environment); err != nil {
		return Snapshot{}, asRejection(err)
	}
	if opts.RequireTwoPersonApproval && strings.TrimSpace(b.Approval.SecondApproverID) == "" {
		return Snapshot{}, reject(contracts.CodeAuthorization,
			"this deployment requires a second approver for every revision, and none is recorded")
	}

	// Step 5: digest, then signature.
	canonical, err := CanonicalBytes(b)
	if err != nil {
		return Snapshot{}, asRejection(err)
	}
	computed := ComputeDigest(canonical)
	if computed != env.Digest {
		return Snapshot{}, reject(contracts.CodeValidation,
			"configuration digest is %s but its content digests to %s; the document was "+
				"modified after signing or was not signed at all", env.Digest, computed)
	}
	if err := opts.Trust.verifySignature(env); err != nil {
		return Snapshot{}, asRejection(err)
	}

	// Step 6: freshness.
	snap := Snapshot{
		Body:        b,
		Digest:      computed,
		ActivatedAt: b.ActivatedAt.Time(),
		Environment: b.Environment,
	}
	age := opts.Now.Sub(snap.ActivatedAt)
	if age > b.Freshness.MaxAge {
		return Snapshot{}, reject(contracts.CodeDataStale,
			"configuration revision %q is %s old, beyond its %s freshness limit; "+
				"stale configuration is refused rather than served",
			b.Revision, age.Truncate(time.Second), b.Freshness.MaxAge)
	}
	if age < 0 {
		// A snapshot activated in the future is refused rather than given the benefit of
		// the doubt, because a clock that is wrong in this direction will also make the
		// staleness check meaningless until it catches up.
		return Snapshot{}, reject(contracts.CodeDataStale,
			"configuration revision %q reports activated_at %s, in the future relative to %s",
			b.Revision, snap.ActivatedAt.UTC().Format(time.RFC3339), opts.Now.UTC().Format(time.RFC3339))
	}

	// Step 7: promotion legality.
	if err := checkPromotion(b, opts); err != nil {
		return Snapshot{}, asRejection(err)
	}

	return snap, nil
}

// checkPromotion enforces that a revision advances exactly one step of the ladder and that
// live is never reached by copying a lower environment.
//
// docs/17 section 1: "Live configuration cannot be copied automatically from lower
// environments." A live revision must therefore name a predecessor that was verified in the
// immediately preceding stage, rather than being authored fresh for live.
func checkPromotion(b Body, opts LoadOptions) error {
	if b.Environment == EnvDev {
		// Dev is the origin of the ladder, so it has no predecessor requirement.
		return nil
	}
	if opts.Previous == nil {
		return reject(contracts.CodeValidation,
			"configuration for %s has no verified predecessor; a snapshot may only be promoted "+
				"one step at a time from an environment it was already verified in", b.Environment)
	}
	prev := opts.Previous
	if !prev.Environment.Valid() {
		return reject(contracts.CodeValidation,
			"predecessor snapshot reports unknown environment %q", prev.Environment)
	}
	if prev.Body.Revision != b.Supersedes {
		return reject(contracts.CodeValidation,
			"configuration supersedes %q but the predecessor in use is revision %q; the "+
				"promotion chain and the document disagree", b.Supersedes, prev.Body.Revision)
	}
	want := prev.Environment.Rank() + 1
	if got := b.Environment.Rank(); got != want {
		return reject(contracts.CodeValidation,
			"configuration promotes revision %q from %s (rank %d) to %s (rank %d); only a "+
				"single promotion step is permitted, and live configuration is never copied "+
				"automatically from a lower environment",
			b.Revision, prev.Environment, prev.Environment.Rank(), b.Environment, got)
	}
	return nil
}

// asRejection converts an error from the validation helpers into a Rejection, so a caller
// sees a canonical code rather than a bare wrapped sentinel.
func asRejection(err error) error {
	if r, ok := err.(Rejection); ok {
		return r
	}
	return reject(contracts.CodeValidation, "%v", err)
}
