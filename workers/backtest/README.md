# `workers/backtest`

Deterministic, point-in-time backtest and simulation engine. **Non-authoritative by
construction**: this worker holds no venue credentials, submits nothing, and has no write path
to any authoritative financial table (`docs/02`, `docs/25` section 4).

## What it produces

A `BacktestArtifact`: a content-addressed, versioned, `proposed` result carrying its lineage —
dataset name, dataset schema version, dataset fingerprint, code revision, feature specification
version, and evaluation report. Every one of those is **inside** the digest rather than printed
beside it, so two artifacts that share a digest cannot disagree about what produced them
(`docs/22` section 5).

The artifact has no `approved_by`, no `reviewer`, and no `deployment_scope` field. They are
omitted rather than left empty on purpose: an empty field invites a later stage to fill it in, a
missing field cannot be filled in at all. Promotion is a reviewed control-plane workflow, and a
research worker that can record its own approval is a worker that can eventually self-approve
(`docs/07` separation of duties). `tests/test_artifacts.py` asserts the field names directly, so
adding one later fails the suite rather than passing review unnoticed.

## The two properties everything else serves

**Reproducible.** The same dataset, parameters, and code produce a byte-identical digest on
every run and every machine. No creation timestamp, no host, no path, no counter enters an
artifact — a timestamp alone would make every artifact unique and destroy the property the
digest exists to provide. All arithmetic is `decimal.Decimal` under a pinned context; floats are
refused at the content-addressing boundary.

**Point-in-time.** Every decision is taken at an explicit `as_of` instant, and the strategy sees
a frozen `MarketView` built by filtering on each bar's `available_at` — the earliest instant it
could have been known to anyone — never on `event_time`, the instant its period closed. A bar
that closes at 10:00 and publishes at 12:00 is invisible to a decision made at 11:00 even though
its period had ended.

That distinction is the single most common way a backtest misleads, and it fails quietly: a
harness that slices on `event_time` does not crash, does not warn, and produces a better-looking
equity curve than the strategy deserves. Three mechanisms make the protection real rather than
aspirational:

* `Dataset.visible_at` is the only sanctioned accessor, so the correct slice is the easy one;
* every decision record carries `visible_sequences`, so the artifact carries its own evidence of
  what the strategy could see and the claim can be re-derived by a reviewer;
* `assert_no_lookahead` re-derives visibility from the result and the dataset through a
  **different code path** from the engine, and `build_artifact` calls it so a caller who forgot
  to check still cannot produce a promotable artifact.

## Testing

Tests are written to fail when the property is removed, not merely to pass when it holds. The
lookahead fixture places a revised bar so that `available_at` and `event_time` rules disagree *at*
a decision instant, and one test asserts they still disagree — a fixture that stopped
discriminating would let every lookahead test pass against a harness with no protection at all.

## Toolchain

Dependencies are pinned exactly and CI fails on a floating or unpinned requirement
(`docs/00` toolchain lifecycle, `docs/02` section 10). The worker shares the research dependency
set deliberately: a version skew between the research that produced a dataset and the backtest
that evaluates it would make a result irreproducible.

See `../research/README.md` for the shared worker boundary.
