package audit

import (
	"crypto/ed25519"
	"crypto/rand"
	"sort"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Signature is a checkpoint signature.
//
// It is a byte slice rather than a fixed array because the signing implementation is an
// input: production signs with a managed KMS or HSM key whose algorithm is chosen
// outside this package. The verifier is told which algorithm it is looking at by the
// key ring, so it never has to guess from the signature's length.
type Signature []byte

// Signer signs a checkpoint payload.
//
// It is an interface because docs/22 section 3 requires checkpoints to be signed by a
// managed KMS or HSM key, and a package that imported a key store could not be tested
// without one. The local Ed25519 signer below exists so the mechanics of signing and
// verification are genuinely exercised rather than mocked away; it is not the
// production signer, and the interface is what production implements.
type Signer interface {
	// KeyID names the key. It is recorded on the checkpoint and on every record the
	// checkpoint covers, so evidence names the key that vouches for it.
	KeyID() string
	// Sign returns a signature over message.
	Sign(message []byte) (Signature, error)
}

// KeyStatus is what a key ring will and will not do with a key.
type KeyStatus string

const (
	// KeySigning is a key that may sign new checkpoints.
	KeySigning KeyStatus = "SIGNING"
	// KeyVerifyOnly is a rotated-out key. It may no longer sign, but it must still
	// verify everything it signed while it was active, or rotation would retroactively
	// invalidate evidence that was properly signed at the time.
	KeyVerifyOnly KeyStatus = "VERIFY_ONLY"
	// KeyCompromised is a key believed exposed. It may neither sign nor verify: a
	// compromised key cannot be allowed to vouch for anything, and treating its past
	// signatures as valid would defeat the point of rotating it away.
	KeyCompromised KeyStatus = "COMPROMISED"
)

// KeyEntry is one key in a ring.
type KeyEntry struct {
	// KeyID is the stable name of the key.
	KeyID string
	// PublicKey is the verification key.
	PublicKey ed25519.PublicKey
	// Status controls what the ring permits.
	Status KeyStatus
}

// KeyRing holds the keys a verifier trusts.
//
// The ring is the trust root for checkpoints. A checkpoint signed by a key the ring does
// not hold, or holds in a compromised state, does not verify: that is the difference
// between a signature being checked and a signature being trusted.
type KeyRing struct {
	entries map[string]KeyEntry
}

// NewKeyRing returns an empty ring.
func NewKeyRing() *KeyRing { return &KeyRing{entries: make(map[string]KeyEntry)} }

// Add registers a key.
func (k *KeyRing) Add(entry KeyEntry) error {
	if entry.KeyID == "" {
		return reject(contracts.CodeValidation, "key id is required")
	}
	if len(entry.PublicKey) != ed25519.PublicKeySize {
		return reject(contracts.CodeValidation,
			"key %s has a %d-byte public key, want %d", entry.KeyID, len(entry.PublicKey), ed25519.PublicKeySize)
	}
	if entry.Status == "" {
		entry.Status = KeyVerifyOnly
	}
	if _, exists := k.entries[entry.KeyID]; exists {
		return reject(contracts.CodeConflict, "key %s is already in the ring", entry.KeyID)
	}
	k.entries[entry.KeyID] = entry
	return nil
}

// SetStatus changes what the ring permits for a key.
func (k *KeyRing) SetStatus(keyID string, status KeyStatus) error {
	entry, ok := k.entries[keyID]
	if !ok {
		return reject(contracts.CodeValidation, "key %s is not in the ring", keyID)
	}
	entry.Status = status
	k.entries[keyID] = entry
	return nil
}

// Status returns a key's status.
func (k *KeyRing) Status(keyID string) (KeyStatus, bool) {
	entry, ok := k.entries[keyID]
	if !ok {
		return "", false
	}
	return entry.Status, true
}

// KeyIDs returns the registered key ids, sorted.
func (k *KeyRing) KeyIDs() []string {
	ids := make([]string, 0, len(k.entries))
	for id := range k.entries {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

// SigningKeys returns the ids permitted to sign, sorted.
func (k *KeyRing) SigningKeys() []string {
	var ids []string
	for id, entry := range k.entries {
		if entry.Status == KeySigning {
			ids = append(ids, id)
		}
	}
	sort.Strings(ids)
	return ids
}

// Verify checks a signature against a key in the ring.
//
// It fails for a key the ring does not hold and for a key held as compromised, not only
// for a bad signature. Those are different failures operationally, and collapsing them
// would let a caller treat "this key was retired" as "this evidence is fine".
func (k *KeyRing) Verify(keyID string, message []byte, sig Signature) error {
	entry, ok := k.entries[keyID]
	if !ok {
		return reject(contracts.CodeAuthentication, "key %s is not in the ring", keyID)
	}
	if entry.Status == KeyCompromised {
		return reject(contracts.CodeAuthentication, "key %s is marked compromised and cannot vouch for evidence", keyID)
	}
	if !ed25519.Verify(entry.PublicKey, message, sig) {
		return reject(contracts.CodeAuthentication, "signature from key %s does not verify", keyID)
	}
	return nil
}

// LocalSigner signs with an Ed25519 key held in process.
//
// It exists so that signing, verification, and key rotation are exercised end to end by
// the test suite. docs/22 section 3 requires a managed KMS or HSM key in production, and
// this type is not one; it is a test double for the KMS, and it is deliberately named so
// that a reader does not mistake it for the production path.
type LocalSigner struct {
	keyID string
	key   ed25519.PrivateKey
}

// NewLocalSigner generates a new Ed25519 signing key.
func NewLocalSigner(keyID string) (*LocalSigner, error) {
	if keyID == "" {
		return nil, reject(contracts.CodeValidation, "key id is required")
	}
	_, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, reject(contracts.CodeInternal, "generating key %s: %v", keyID, err)
	}
	return &LocalSigner{keyID: keyID, key: priv}, nil
}

// KeyID implements Signer.
func (s *LocalSigner) KeyID() string { return s.keyID }

// Sign implements Signer.
func (s *LocalSigner) Sign(message []byte) (Signature, error) {
	if len(message) == 0 {
		return nil, reject(contracts.CodeValidation, "refusing to sign an empty payload")
	}
	return ed25519.Sign(s.key, message), nil
}

// PublicKey returns the verification key.
func (s *LocalSigner) PublicKey() ed25519.PublicKey { return s.key.Public().(ed25519.PublicKey) }

// Register adds the signer to a ring with the given status.
func (s *LocalSigner) Register(ring *KeyRing, status KeyStatus) error {
	return ring.Add(KeyEntry{KeyID: s.keyID, PublicKey: s.PublicKey(), Status: status})
}

// Rotate installs a new signing key and demotes every previous signing key to
// verify-only.
//
// The previous keys are retained rather than removed, because evidence they signed
// remains evidence: dropping one would make every checkpoint closed before the rotation
// fail to verify, which reads as tampering when nothing was tampered with.
//
// Rotation is allowed even when no key is currently permitted to sign. That is not a
// gap in the check but the case rotation exists for: the active key has just been marked
// compromised, and installing its successor is the response. The one thing that is
// refused is reintroducing a key that is still trusted, because silently reactivating a
// retired key would undo the exposure rotation was performed to remove.
func (k *KeyRing) Rotate(newSigner Signer, newPublic ed25519.PublicKey) (string, error) {
	keyID := newSigner.KeyID()
	if keyID == "" {
		return "", reject(contracts.CodeValidation, "new key id is required")
	}
	if existing, ok := k.entries[keyID]; ok {
		if existing.Status != KeyCompromised {
			return "", reject(contracts.CodeConflict,
				"key %s is already in the ring as %s; rotation must install a new key", keyID, existing.Status)
		}
		// A compromised key may be replaced in place by its successor; the public key
		// must still match, so a successor cannot be substituted under the same id.
		if !ed25519.PublicKey(existing.PublicKey).Equal(newPublic) {
			return "", reject(contracts.CodeConflict,
				"key %s is compromised; a replacement may not reuse the id unless the key material matches", keyID)
		}
	}

	var demoted []string
	for id, entry := range k.entries {
		if entry.Status == KeySigning {
			demoted = append(demoted, id)
		}
	}

	if _, exists := k.entries[keyID]; !exists {
		if err := k.Add(KeyEntry{KeyID: keyID, PublicKey: newPublic, Status: KeySigning}); err != nil {
			return "", err
		}
	} else if err := k.SetStatus(keyID, KeySigning); err != nil {
		return "", err
	}
	sort.Strings(demoted)
	for _, id := range demoted {
		if err := k.SetStatus(id, KeyVerifyOnly); err != nil {
			return "", err
		}
	}
	return keyID, nil
}
