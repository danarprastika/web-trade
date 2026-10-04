# G1 Gate Report - Domain Foundation

Specification: docs/11_EXECUTION_GATES.md section G1
Verified at: 2026-10-04T12:45:30Z
**Verdict: FAIL**

## Why the verdict is FAIL

- 9 of 9 mechanical criteria PASS
- reviewer field OUTSTANDING
- commit field PRESENT (HEAD 8cbd4872a04f, 0 untracked/modified path(s))

docs/11_EXECUTION_GATES.md states that a gate is PASS only when every listed
criterion is satisfied and that partial completion is FAIL, not a percentage. All nine
mechanical criteria hold. The report's *reviewer* and *commit* fields cannot be
produced by an automated agent, and the referenced commit does not contain the work
being certified, so the gate cannot be recorded as PASS.

## Mechanical criteria

| Criterion | Result | Evidence |
| --- | --- | --- |
| Canonical IDs | **PASS** | go test ./... in contracts/go: 1 package(s) ok, 0 without tests |
| Timestamps | **PASS** | contracts.Timestamp canonical form and UTC rejection asserted; 1 package(s) ok, 0 without tests |
| Money/quantity types | **PASS** | exact-decimal Money/Quantity/Decimal; no_float_test enforces the absence of binary floating point; 1 package(s) ok, 0 without tests |
| Errors | **PASS** | ErrorCode and ContractError with a stable wire form; 1 package(s) ok, 0 without tests |
| Envelopes | **PASS** | CommandEnvelope and EventEnvelope; actor binding asserted; 1 package(s) ok, 0 without tests |
| Idempotency | **PASS** | idempotency key in the envelope, in OMS apply, and enforced by a unique index in 0001_ledger.sql; ledger idempotency tests pass; 1 package(s) ok, 0 without tests 1 package(s) ok, 0 without tests 11 package(s) ok, 2 without tests |
| Configuration boundaries | **PASS** | typed configuration with signed immutable release snapshot and drift detection; 11 package(s) ok, 2 without tests |
| Migrations | **PASS** | every migration in db/migrations parsed by real_migrations_test.go, which asserts reversibility, explicit BEGIN/COMMIT, and no DROP in an up body; 11 package(s) ok, 2 without tests |
| Domain tests | **PASS** | 1172 test(s) reported PASS: contracts/go 90, components/oms 91, components/risk-engine 136, components/reconciliation 0, adapters/venues 0, services/control-plane 855; declared placeholders with no implementation yet, gated by later work items: adapters/venues, components/reconciliation |

9 of 9 mechanical criteria PASS.

## Required report fields

| Field | Value | Status |
| --- | --- | --- |
| reviewer | `None` | OUTSTANDING |
| commit | `8cbd4872a04fc2781c3b28123026360c9f83cf80` | PRESENT |
| timestamp | `recorded above in verified_at` | PRESENT |
| command_output | `per criterion` | PRESENT |
| binary_pass_fail | `FAIL` | PRESENT |
| evidence_digests | `per artifact` | PRESENT |

### Outstanding fields in detail

**reviewer** - A named human reviewer cannot be produced by an automated agent. docs/11 requires the gate report to identify its reviewer, and the same package treats an unattested specification as not passed (G0.8 REQUIRES_HUMAN_ATTESTATION).

## Evidence digests

Every artifact is identified by repository path and SHA-256 content digest, as
docs/11 requires.

### Canonical IDs (PASS)

Artifact set digest: `sha256:fd7afccea49774917ff8df92d42d11b95ebd4839197cb2fd3750d0c02467ee6c`

- `contracts/go/identifier.go` - `sha256:062fb4141e80179b3f1fae97660ca08a913ba5c8abbc03d4846ae81140864c03`
- `contracts/go/identifier_test.go` - `sha256:4c13fccad4bc9c6173520196152074211e82c6edaf4c6c91ebff85f63dbdff9a`

### Timestamps (PASS)

Artifact set digest: `sha256:d01efe2e6cba47a0554ec1b399916e0c1ee73a1a6105c9914177bf7d594b9f4a`

- `contracts/go/error.go` - `sha256:ed85d34425f16779c1df5df782c923dd35c8fc3f32f1c4bb29f402222e298b61`
- `contracts/go/error_timestamp_test.go` - `sha256:85b5bcf5199ee0803152c7bbf2f13f32c8b207edaac5391426d85f43d5493cf8`

### Money/quantity types (PASS)

Artifact set digest: `sha256:33f19c5ab47a3ffe105e2a7fd2b8b86b79f3a08ce5de898bc61388a5e23f1ba5`

- `contracts/go/money.go` - `sha256:d3b08fcd7bda62a264277e0487d93e802124730f03e597b8c3ab4653ad54ce76`
- `contracts/go/decimal.go` - `sha256:82aa4483d19533c2d268c3ffbfcfe7642fa0cb3854f66825a583c5d3e12b143a`
- `contracts/go/money_test.go` - `sha256:9d15b3b2cbae35bb65682a0d90063af7851124cc280eadb1bdf73e99fc7f9ee7`
- `contracts/go/decimal_test.go` - `sha256:a2c280933463459e04cfad90eb7883c62d52e61e32436e53a8b7f12d5dbd0250`
- `contracts/go/no_float_test.go` - `sha256:a6b71874ea5a3d57ac95f5d07b540857476e662c07b08424bbc1fbc2f9ba0593`

### Errors (PASS)

Artifact set digest: `sha256:69fad08b76944b9f0f9cc90a651407cf3ce5efa464eb0ed59043f18f163df57b`

- `contracts/go/error.go` - `sha256:ed85d34425f16779c1df5df782c923dd35c8fc3f32f1c4bb29f402222e298b61`
- `contracts/go/error_test.go` - `sha256:6aae56cd19570c2f752a98ed4a79f1778bb7ec97a007aa93c2612f7429753c16`

### Envelopes (PASS)

Artifact set digest: `sha256:7a6dc38d828695927a69ffd5b15fe56d22f7e186fee437caac7d7338a0ae18b0`

- `contracts/go/envelope.go` - `sha256:6f7df06454ba4d6e2ba81f8fb86457c65d97672e10c4017c8341731008fa8b44`
- `contracts/go/envelope_test.go` - `sha256:b59ecbf628a9486c718cb4ce709524d0f3ed87d8966a5021b48ff54bbd422df8`
- `contracts/go/envelope_actor_test.go` - `sha256:a77bab1ce6d5fd449673fc7d185020d50c10f17752a139dc334394afd1413804`

### Idempotency (PASS)

Artifact set digest: `sha256:02d1233380149e9c1646593ee5d8d342f7cc8da02b4fccb0f49a63aece27bcf6`

- `contracts/go/envelope.go` - `sha256:6f7df06454ba4d6e2ba81f8fb86457c65d97672e10c4017c8341731008fa8b44`
- `components/oms/order.go` - `sha256:55ea6e0ce30ce60fc16fa2d1646c345596f5f963c6aa8e48953108940f7e097b`
- `services/control-plane/ledger/entry.go` - `sha256:397ed2152d57fbdb7260fb8cfca60ddaae95fc79edb3a576c273bedc3951a912`
- `services/control-plane/ledger/ledger_test.go` - `sha256:ed3928a3bb7b7a2f7c9109ba98326d505fbb659208abe2cf82dfc9b72fa12699`
- `db/migrations/0001_ledger.sql` - `sha256:22d1d4280cdbe5611e7027c36bf6b77e1dc9cd515f5dc2b26303830ba503e262`

### Configuration boundaries (PASS)

Artifact set digest: `sha256:0d20318cd58fb84b9d9a1629b114654802e89ecfbc23a4d1f17caeae0720cb47`

- `services/control-plane/config/config.go` - `sha256:82db4c736d075faa8d1a5ace3fc7a05cc682299179f7f39cc533cf86997400e1`
- `services/control-plane/config/load.go` - `sha256:d7f4e8943f6a38515fd87d775ea124f9d304c101a61ff9b9898c7fa0056ae1bc`
- `services/control-plane/config/sign.go` - `sha256:7bc6441498b1c3b2aaf52238c6a7d2548ce0ff8157f27cb558c1734b73539383`
- `services/control-plane/config/drift.go` - `sha256:d7d0d0d086a2bf0d353e9df45aaf86a2710de24ae699caa5bb3e5f607ff1906c`
- `services/control-plane/config/config_test.go` - `sha256:ff3036cedfedbc73978e485fa1c94d59364f7eeded44fb20b5bf1070f32afc98`

### Migrations (PASS)

Artifact set digest: `sha256:1d8be1c702165a48ec21d434a82e4ba3bc85c6c20c656b1769e0c3ca626fc0a3`

- `services/control-plane/migrate/migrate.go` - `sha256:e27ec916de880e67edc4863b4933614178a48dd2a09ed1459b860b3b9403e34b`
- `services/control-plane/migrate/real_migrations_test.go` - `sha256:a65a46d8bae8c1a737403e6956958b04fc8969e8fd694f91074f88fc7d4c5eda`
- `db/migrations/0001_ledger.sql` - `sha256:22d1d4280cdbe5611e7027c36bf6b77e1dc9cd515f5dc2b26303830ba503e262`
- `db/migrations/0002_audit.sql` - `sha256:6b7e3f280181b92f70bc659946a6e27dc2c3d92fa3a77f5fd7de94b5614afecd`
- `db/migrations/0003_authz.sql` - `sha256:7bd18210a4331ac5d12de1fcecbbdbebcb448c4cd3273a5b09f3bb38377799ce`

