# `workers/research` and `workers/backtest`

Two Python workers, both **offline and non-authoritative**.

| Worker | Responsibility | Explicitly prohibited |
|---|---|---|
| `workers/research` | Datasets, experiments, feature engineering, offline model evaluation | Live credentials, venue submission, authoritative writes, self-promotion to production |
| `workers/backtest` | Deterministic simulation, artifact production | The same |

The separation is deliberate rather than cosmetic. A dataset is versioned input to a
simulation; the simulation produces a versioned artifact. Collapsing them into one worker
makes it easy for a dataset-building routine to acquire, through a later patch, a write
path that the surrounding design was supposed to prevent.

## The boundary is structural, not documented

Neither worker can reach the authoritative stores because neither has credentials, a network
policy, or a database driver for them. The research trust zone cannot route to control-plane
data stores (`docs/01` section 9). Adding a connection string to either worker is a
boundary violation and is caught at review and by the secret-isolation gate.

`pyproject.toml` enables ruff's `S` (bandit) rules for exactly this reason: a finding such
as a hard-coded credential or a subprocess call in research code is an authority-boundary
warning, not a style note.

## Numerics

Research and backtest numerics are `decimal.Decimal` over base-10 strings. Floats are
**refused at construction**, not coerced: `canonical_digest` raises on a float anywhere in its
input, and `Money` raises on a float amount. A float64 value is not reproducible across the
platforms Python and NumPy run on, and a digest computed over one is worse than no digest,
because it looks authoritative while changing with the machine.

The same reasoning applies to the authoritative side. Authoritative financial arithmetic is Go
plus PostgreSQL decimal, where money is a base-10 decimal string
(`docs/03_CANONICAL_CONTRACTS.md`). So the boundary carries no float in either direction: the
workers will not produce one, and the control plane will not accept one.

`numpy` remains a declared dependency for offline research beyond the digest path, and is
float64. It is permitted **only** offline and must not be used to produce any value that
crosses the boundary or enters a content address.

A consequence worth stating plainly: **a backtest result is not a financial fact.** It is an
input to a human-reviewed decision. A backtest is evidence, never authority.

## The contract binding

`workers/research/src/webtrade_research/canonical.py` is the Python binding of the canonical
contract package. It exists because anything crossing the research/control-plane boundary is
defined once in `contracts/` and validated here rather than re-invented in Python.

It uses `decimal.Decimal` over base-10 strings, never `float`, and `Money` refuses a float at
construction rather than coercing it. Its test suite reads
`contracts/fixtures/conformance.json` directly, so it cannot drift into asserting a stale
local copy of the rules.

## Determinism

The backtest worker requires seeded randomness, stable iteration order, and a
**reproducible** content address. A non-reproducible result cannot be promoted
(`docs/11`, G4). This is a hard requirement, not a code-review preference.

The engine reads no clock at all rather than taking an injected one. An injected clock is the
usual design, but a backtest with no wall-clock dependence needs no seam where a caller could
pass in a different one: decisions are scheduled from the dataset's `available_at` values, so
two runs over the same data decide at the same instants regardless of when they execute. There
is nothing for an ambient clock to perturb.

These properties are verified rather than asserted. `tests/test_authority_boundary.py` parses
both packages and asserts the worker holds no network, database, or process-spawning
capability and that no declared dependency grants one. `../backtest/tests/test_artifacts.py`
asserts the artifact digest is a function of its content including its lineage, and that the
artifact has no field it could be approved with.

## Toolchain

Pinned exactly in `pyproject.toml` to the latest security-supported release at bootstrap
(`docs/00_README.md` toolchain lifecycle). CI fails on an unpinned dependency or lockfile
drift.

Research and backtest intentionally share one dependency set. A version skew between the
research that produced a result and the backtest that evaluates it would make the result
irreproducible, which is the one property a backtest must have.
