# `contracts/` — Canonical contract package

This directory is the **single authoritative source of truth for every type that crosses a language or process
boundary.** Nothing may redefine these types "locally for convenience". If a rule must cross a language boundary, it
is defined here once and generated or validated from these schemas.

Authority: [`docs/03_CANONICAL_CONTRACTS.md`](../../docs/03_CANONICAL_CONTRACTS.md),
[`docs/02_POLYGLOT_ENGINEERING_STANDARD.md`](../../docs/02_POLYGLOT_ENGINEERING_STANDARD.md) §"Contract-first
interoperability" and §9, [`docs/15_API_AND_INTEGRATION_CONTRACTS.md`](../../docs/15_API_AND_INTEGRATION_CONTRACTS.md).

## Layout

```text
contracts/
  schema/     JSON Schema (draft 2020-12) — the canonical definitions
  fixtures/   Golden vectors — the shared cross-language test corpus
```

## Why JSON Schema is the canonical form

`docs/02` requires that a cross-boundary rule be "versioned and generated or validated from one authoritative
schema", and §9 requires that "canonical decimal, timestamp, identifier, enum, error, and pagination
representations are tested against shared fixtures" in **every** producer/consumer language.

JSON Schema satisfies both without privileging a language: Go, TypeScript, and Python all generate or validate
against the same source. Protobuf is reserved for high-volume internal calls where measured throughput warrants it
(`docs/02`), and OpenAPI/AsyncAPI describe the HTTP and event *transports* — they reference these schemas rather
than redefining them.

## Language bindings

| Language | Binding | Location |
|---|---|---|
| Go | Hand-written canonical types with strict JSON binding; runs the shared corpus in `go test` | `contracts/go` |
| TypeScript | Generate types; runtime validation | `apps/web` |
| Python | Generate models (pydantic v2) | `workers/research`, `workers/backtest` |

The Go binding is deliberately not generated. The types carry invariants a generator cannot express: a zero-value
`Decimal` is *unset* rather than numeric zero, a currency mismatch is a hard rejection rather than a conversion, and
`TIMEOUT_UNKNOWN` cannot be constructed with `retryable: true`. Code generation would produce structs that satisfy the
JSON Schema while permitting each of those, which is the failure mode the corpus is meant to catch.

A component **cannot promote** if its binding disagrees with the canonical contract repository
(`docs/02` §9). Schema changes require backward compatibility for one release window unless a coordinated migration
is executed.

## Non-negotiable rules encoded here

1. **No IEEE-754 floating point may cross a financial contract.** Money and quantities are base-10 decimal
   *strings*. A JSON number is not an acceptable representation of a financial value.
2. **Unknown enum values are treated as unsupported, not silently mapped** (`docs/03`, compatibility).
3. **Consumers must tolerate additive fields.** Breaking changes require a new `schema_version` plus dual-read /
   dual-write migration where persisted data is affected.
4. **Persisted timestamps are UTC RFC 3339.** Offsets are normalized at the transport edge, never stored.
5. **Idempotency is scoped to actor, endpoint, and environment** and is enforced by a database uniqueness
   constraint — never by application memory (`docs/03`, WI-123).

## Identifier format

Typed prefix + lowercase Crockford Base32 payload. Crockford Base32 omits `I`, `L`, `O`, and `U` to avoid
transcription ambiguity with `1` and `0`.

```text
<prefix>_<crockford-base32-lowercase>
```

| Prefix | Entity | Example |
|---|---|---|
| `cmd_` | Command | `cmd_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `evt_` | Event | `evt_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `ord_` | Order | `ord_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `str_` | Strategy | `str_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `mdl_` | Model | `mdl_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `run_` | Run (backtest/experiment/deployment) | `run_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `pos_` | Position | `pos_01hq3k7m9x2f5rb8n0v6c4tqwx` |
| `led_` | Ledger entry | `led_01hq3k7m9x2f5rb8n0v6c4tqwx` |

The payload is 26 Crockford Base32 characters (130 bits). Prefix characters are outside that alphabet, so a
prefix is never confused with its payload.

## Money

```json
{ "currency": "USD", "amount": "1234.5678" }
```

`currency` is ISO 4217 for fiat, or an explicitly configured asset code for digital assets. `amount` is a base-10
decimal string. See [`schema/money.schema.json`](schema/money.schema.json).

## Fixtures

[`fixtures/`](fixtures/) holds the golden vectors every language binding must agree on. A language binding is
conformant only when it reproduces the accepted vectors and rejects the rejected vectors in
[`fixtures/conformance.json`](fixtures/conformance.json).

This is the mechanism behind the `docs/02` §9 rule and is exercised by CI as a mandatory merge gate.
