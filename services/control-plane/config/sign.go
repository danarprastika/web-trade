package config

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// DigestPrefix labels a digest so an operator reading a log or a rejection can tell a
// configuration digest from a config-file checksum without checking the length.
const DigestPrefix = "sha256:"

// Body is the signed content of a configuration revision.
//
// The signature covers the canonical serialisation of this struct, and the digest is
// carried in the envelope alongside it. Splitting the body from the envelope is what makes
// the scheme non-circular: a digest field inside the value being digested would have to hash
// itself.
//
// Struct field order is the canonical field order, because encoding/json emits struct
// fields in declaration order. Declaring a field is therefore the only way to make it
// part of the signed content, and omitting one silently changes the digest, which is
// exactly the behaviour that makes a signature meaningful.
type Body struct {
	// SchemaVersion is the version of this configuration schema, so a future reader can
	// refuse a document it does not understand rather than reinterpret its fields.
	SchemaVersion string `json:"schema_version"`
	// Revision is the configuration revision, which must be a semantic version.
	Revision string `json:"revision"`
	// Environment is the promotion stage this revision is for.
	Environment Environment `json:"environment"`
	// Supersedes is the revision this one replaces. It is required so a promotion chain is
	// traceable and so a rollback target can be identified.
	Supersedes string `json:"supersedes"`
	// CreatedAt is when the revision was authored.
	CreatedAt contracts.Timestamp `json:"created_at"`
	// ActivatedAt is when the revision took effect. Freshness is measured from here, not
	// from CreatedAt, because a revision authored long ago and activated now is current.
	ActivatedAt contracts.Timestamp `json:"activated_at"`
	// Approval is the reviewer attestation required by docs/17 section 6.
	Approval Approval `json:"approval"`
	// Policy is the risk policy dimension set.
	Policy Policy `json:"policy"`
	// Freshness bounds how long this revision may be served, and how long the last
	// verified safe snapshot may be used if this one becomes unavailable.
	Freshness Freshness `json:"freshness"`
	// Flags is the feature-flag state. Only names declared in the documented set are
	// honoured; see flags.go.
	Flags map[string]bool `json:"flags"`
}

// Approval is the reviewer attestation for a revision.
//
// docs/17 section 6 requires schema validation, boundary tests, scenario tests,
// authorization review, audit verification, and a dry-run comparison before a policy
// revision is accepted. Each of those is recorded as a named check so a missing one is a
// rejection rather than an assumption.
type Approval struct {
	// ApproverID is the accountable human.
	ApproverID string `json:"approver_id"`
	// ApproverType must be a human: docs/17 section 6 requires an authorised approver, and
	// section 5 forbids a model or strategy from granting itself permission.
	ApproverType contracts.ActorType `json:"approver_type"`
	// AuthorizedAt is when the approval was granted.
	AuthorizedAt contracts.Timestamp `json:"authorized_at"`
	// Reason is the reviewer-facing justification.
	Reason string `json:"reason"`
	// Checks records the completed acceptance checks by name.
	Checks []string `json:"checks"`
	// SecondApproverID is required for a live revision. docs/17 section 5 requires a
	// two-person approval for system-wide live re-enable, and requiring it at the revision
	// level is what makes that checkable without trusting a downstream note.
	SecondApproverID string `json:"second_approver_id"`
	// RollbackRevision names the revision to return to. docs/17 section 6 requires a
	// rollback revision for production activation.
	RollbackRevision string `json:"rollback_revision"`
}

// requiredChecks are the acceptance checks docs/17 section 6 names. They are matched by
// exact name so a check cannot be satisfied by a paraphrase, which is the difference between
// evidence and a claim.
var requiredChecks = []string{
	"schema_validation",
	"boundary_tests",
	"scenario_tests",
	"authorization_review",
	"audit_verification",
	"dry_run_comparison",
}

// Approval.Validate checks the attestation is complete for the target environment.
func (a Approval) Validate(environment Environment) error {
	if strings.TrimSpace(a.ApproverID) == "" {
		return fmt.Errorf("%w: revision has no approver; an unattributed policy change is not auditable", ErrInvalidConfig)
	}
	if a.ApproverType != contracts.ActorHuman {
		return fmt.Errorf("%w: approver must be a human, got %s; docs/17 section 6 requires an "+
			"authorised approver and forbids a model or strategy granting itself permission",
			ErrInvalidConfig, a.ApproverType)
	}
	if a.AuthorizedAt.IsZero() {
		return fmt.Errorf("%w: revision has no approval timestamp", ErrInvalidConfig)
	}
	if strings.TrimSpace(a.Reason) == "" {
		return fmt.Errorf("%w: revision approval must record a reason", ErrInvalidConfig)
	}
	if environment == EnvLive {
		if strings.TrimSpace(a.RollbackRevision) == "" {
			return fmt.Errorf("%w: a live revision must name a rollback revision", ErrInvalidConfig)
		}
		if strings.TrimSpace(a.SecondApproverID) == "" {
			return fmt.Errorf("%w: a live revision requires a second approver; "+
				"system-wide live re-enable is a two-person approval", ErrInvalidConfig)
		}
		if a.SecondApproverID == a.ApproverID {
			return fmt.Errorf("%w: the second approver must be a different person; "+
				"two-person approval with one identity is one person", ErrInvalidConfig)
		}
	}

	present := make(map[string]struct{}, len(a.Checks))
	for _, c := range a.Checks {
		present[c] = struct{}{}
	}
	var missing []string
	for _, req := range requiredChecks {
		if _, ok := present[req]; !ok {
			missing = append(missing, req)
		}
	}
	if len(missing) > 0 {
		return fmt.Errorf("%w: revision approval is missing %d required check(s): %s; "+
			"a policy revision is accepted only after all of them",
			ErrInvalidConfig, len(missing), strings.Join(missing, ", "))
	}
	return nil
}

// Freshness bounds the usable lifetime of a revision.
//
// Both windows matter and they are not the same control. MaxAge is how long this revision
// may be served at all. MaxLastKnownGoodAge is how long a previously verified snapshot may
// stand in when the flag service or the distribution channel is unavailable. The second is
// the one docs/25 line 97 constrains: "Use last verified safe snapshot only within
// configured freshness; unknown flags never grant authority".
type Freshness struct {
	MaxAge              time.Duration `json:"max_age"`
	MaxLastKnownGoodAge time.Duration `json:"max_last_known_good_age"`
}

// Validate checks the freshness policy is coherent.
func (f Freshness) Validate() error {
	if f.MaxAge <= 0 {
		return fmt.Errorf("%w: freshness.max_age must be positive; a snapshot with no "+
			"expiry could never be stale", ErrInvalidConfig)
	}
	if f.MaxLastKnownGoodAge <= 0 {
		return fmt.Errorf("%w: freshness.max_last_known_good_age must be positive; the "+
			"fallback window is a bound, not a default", ErrInvalidConfig)
	}
	if f.MaxLastKnownGoodAge > f.MaxAge {
		return fmt.Errorf("%w: freshness.max_last_known_good_age (%s) exceeds max_age (%s); "+
			"the fallback snapshot would outlive the revision it stands in for",
			ErrInvalidConfig, f.MaxLastKnownGoodAge, f.MaxAge)
	}
	return nil
}

// Envelope is a signed configuration document as it travels: the body, plus the digest of
// its canonical form and a signature over that digest.
type Envelope struct {
	Digest    string `json:"digest"`
	Signature string `json:"signature"`
	Body      Body   `json:"body"`
}

// CanonicalBytes returns the deterministic serialisation of a body.
//
// The bytes are produced by re-encoding the typed struct rather than by copying the
// document as received. That has two consequences worth stating, because both are relied
// on by the verification pipeline:
//
//   - Key order and whitespace in the incoming document do not affect the digest, so the
//     signature covers semantic content rather than a formatting choice.
//   - Any field not represented in Body cannot affect the digest. This is why decoding is
//     strict: an unknown field must be a rejection, because if it decoded silently it would
//     contribute nothing to the digest while still being present in the document, and the
//     document would then assert a configuration the signature does not cover.
func CanonicalBytes(b Body) ([]byte, error) {
	raw, err := json.Marshal(b)
	if err != nil {
		return nil, fmt.Errorf("%w: cannot canonicalise configuration: %v", ErrInvalidConfig, err)
	}
	return raw, nil
}

// ComputeDigest returns the prefixed SHA-256 digest of the canonical bytes.
func ComputeDigest(canonical []byte) string {
	sum := sha256.Sum256(canonical)
	return DigestPrefix + hex.EncodeToString(sum[:])
}

// digestBytes strips the prefix so the signature covers exactly 32 bytes. Signing the
// prefixed string instead would be equivalent in security but would make the signature
// depend on a human-readable label, so the two encodings could drift apart.
func digestBytes(digest string) ([]byte, error) {
	if !strings.HasPrefix(digest, DigestPrefix) {
		return nil, fmt.Errorf("%w: digest %q is not %s-prefixed", ErrInvalidConfig, digest, DigestPrefix)
	}
	raw, err := hex.DecodeString(strings.TrimPrefix(digest, DigestPrefix))
	if err != nil {
		return nil, fmt.Errorf("%w: digest is not valid hex: %v", ErrInvalidConfig, err)
	}
	if len(raw) != sha256.Size {
		return nil, fmt.Errorf("%w: digest is %d bytes, want %d", ErrInvalidConfig, len(raw), sha256.Size)
	}
	return raw, nil
}

// Sign produces the digest and detached signature for a body.
//
// It is the authoring path. A revision is signed once, by whoever is responsible for it,
// and every service thereafter only verifies. There is deliberately no corresponding
// "resign" operation exposed to a runtime service.
func Sign(b Body, key ed25519.PrivateKey) (Envelope, error) {
	if len(key) != ed25519.PrivateKeySize {
		return Envelope{}, fmt.Errorf("%w: signing key is %d bytes, want %d",
			ErrInvalidConfig, len(key), ed25519.PrivateKeySize)
	}
	canonical, err := CanonicalBytes(b)
	if err != nil {
		return Envelope{}, err
	}
	digest := ComputeDigest(canonical)
	raw, err := digestBytes(digest)
	if err != nil {
		return Envelope{}, err
	}
	return Envelope{
		Digest:    digest,
		Signature: base64.StdEncoding.EncodeToString(ed25519.Sign(key, raw)),
		Body:      b,
	}, nil
}

// TrustStore is the set of public keys permitted to sign configuration, keyed by key id.
//
// A trust store rather than a single key because key rotation is a real operational need and
// rotation without a transition window signs the system out. A key that is not in the store
// is refused, which is what makes adding a signer an explicit, reviewable act.
type TrustStore struct {
	keys map[string]ed25519.PublicKey
	// Revoked keys are retained so a revoked signature is reported as revoked rather than
	// as unknown, which matters when the question is "was this signed by a key we once
	// trusted".
	revoked map[string]struct{}
}

// NewTrustStore builds a trust store from key id to public key.
func NewTrustStore(keys map[string]ed25519.PublicKey) (*TrustStore, error) {
	copied := make(map[string]ed25519.PublicKey, len(keys))
	for id, pub := range keys {
		if strings.TrimSpace(id) == "" {
			return nil, fmt.Errorf("%w: a trust store key has an empty key id", ErrInvalidConfig)
		}
		if len(pub) != ed25519.PublicKeySize {
			return nil, fmt.Errorf("%w: trust store key %q is %d bytes, want %d",
				ErrInvalidConfig, id, len(pub), ed25519.PublicKeySize)
		}
		copied[id] = pub
	}
	return &TrustStore{keys: copied, revoked: map[string]struct{}{}}, nil
}

// Revoke marks a key id as revoked. Verification against it fails with a distinct message,
// and the key stays in the store so a signature made while it was valid can be identified.
func (t *TrustStore) Revoke(keyID string) {
	if t.revoked == nil {
		t.revoked = map[string]struct{}{}
	}
	t.revoked[keyID] = struct{}{}
}

// KeyIDFor derives the trust store key id from a public key, so a verifier can look up the
// right key without the document having to name it. The document deliberately does not name
// the key: a signer-chosen key id would let a document select which trust anchor checks it,
// which is the wrong direction of control.
func KeyIDFor(pub ed25519.PublicKey) string {
	sum := sha256.Sum256(pub)
	return hex.EncodeToString(sum[:8])
}

// SignatureFor returns the trust store key id that would verify a signature made by this
// public key.
func (t *TrustStore) SignatureFor(pub ed25519.PublicKey) (string, bool) {
	id := KeyIDFor(pub)
	if _, ok := t.keys[id]; ok {
		return id, true
	}
	return id, false
}

// verifySignature checks the detached signature over the digest using a trusted key.
//
// Ed25519 verification is the whole check: it covers the message, so a signature made over a
// different digest cannot be replayed onto this document.
func (t *TrustStore) verifySignature(env Envelope) error {
	sig, err := base64.StdEncoding.DecodeString(env.Signature)
	if err != nil {
		return fmt.Errorf("%w: signature is not valid base64: %v", ErrInvalidConfig, err)
	}
	if len(sig) != ed25519.SignatureSize {
		return fmt.Errorf("%w: signature is %d bytes, want %d", ErrInvalidConfig, len(sig), ed25519.SignatureSize)
	}
	raw, err := digestBytes(env.Digest)
	if err != nil {
		return err
	}

	// Try every trusted key. The set is small and fixed at deployment time, and trying all
	// of them avoids making verification depend on a document-supplied key id.
	for id, pub := range t.keys {
		if ed25519.Verify(pub, raw, sig) {
			if _, revoked := t.revoked[id]; revoked {
				return fmt.Errorf("%w: configuration was signed by revoked key %s", ErrInvalidConfig, id)
			}
			return nil
		}
	}
	if len(t.keys) == 0 {
		return fmt.Errorf("%w: trust store is empty; no signature can be verified", ErrInvalidConfig)
	}
	return fmt.Errorf("%w: configuration signature does not verify against any trusted key", ErrInvalidConfig)
}
