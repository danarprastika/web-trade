"""Deterministic backtest and simulation engine.

Authority boundary
------------------
Non-authoritative. This worker holds no venue credentials, submits nothing, and has no
write path to any authoritative financial table (docs/02_POLYGLOT_ENGINEERING_STANDARD.md,
docs/25 section 4).

Determinism is the contract that matters here
---------------------------------------------
A backtest exists to answer "would this have worked", and that question is only meaningful
if the answer is reproducible. A backtest is therefore required to be **deterministic**: the
same dataset, the same parameters, and the same code must produce byte-identical results on
every run and on every machine (docs/11, G4).

That rules out, by construction:

* ambient wall-clock time as an input — no clock is read at all, and none is injected either,
  because decisions are scheduled from the dataset's ``available_at`` values and so are a
  function of the data rather than of when the run happened;
* unordered iteration where order affects results,
* unseeded randomness (a seed is a required parameter, never a default),
* hash-order dependence, and
* float arithmetic anywhere in a content address — all values crossing into a digest are
  base-10 strings, and :func:`webtrade_research.content_address.canonical_digest` raises on a
  float rather than coercing it. A float64 value is not reproducible across platforms, so a
  digest over one would change with the machine while still looking authoritative.

The failure mode this guards against is specific and quiet: a backtest that looks better
on Tuesday than on Wednesday for reasons unrelated to the strategy. Such a result would be
promoted, believed, and acted on.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
