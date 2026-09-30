"""Offline research workloads for the web-trade platform.

Authority boundary
------------------
This package is **non-authoritative by construction**, and the module layout is chosen to
make that structural rather than merely documented:

* It holds no venue credentials and has no code path that submits an order.
* It has no database write path to any authoritative financial table.
* It cannot promote its own artifacts; promotion is a reviewed workflow owned by the
  control plane (docs/02_POLYGLOT_ENGINEERING_STANDARD.md, docs/25 section 4).

Research outputs are *versioned artifacts*, not facts. They are proposed to the control
plane, which validates them. A model may never authorize its own execution
(docs/25 invariant 1).

Numerics
--------
Research numerics use IEEE-754 float64, which is appropriate for offline experimentation
and is explicitly permitted here. It is permitted **only** here: no float value may cross
a financial contract. Authoritative financial arithmetic is Go plus PostgreSQL decimal,
where money is a base-10 decimal string (docs/03_CANONICAL_CONTRACTS.md).

The consequence for this package is that a research result is never a financial fact. It
is an input to a human-reviewed decision.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
