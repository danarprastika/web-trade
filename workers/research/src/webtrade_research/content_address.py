"""Content addressing and canonical serialization for research artifacts.

docs/02 requires that research "receives immutable/versioned datasets and produces
signed/versioned artifacts", and docs/02 section 10 requires a reproducible artifact digest.
Both reduce to one question: can two independent processes, on two machines, serialise the
same logical value to the same bytes? If not, a fingerprint is a local identifier and cannot be
used to decide whether two artifacts are the same thing.

The rules here are the same ones the Go contract package applies, and they are not stylistic:

* **Object keys are sorted.** ``{"a":1,"b":2}`` and ``{"b":2,"a":1}`` are the same value with
  different byte orderings; unsorted keys would make the digest depend on construction order.
* **No incidental whitespace.** Separators are fixed so indentation cannot leak in.
* **No ASCII escaping variance.** ``ensure_ascii=True`` means a non-ASCII character has one
  encoding, not two, so a digest does not depend on the writer's Unicode handling.
* **Floats are refused outright.** A binary float is not reproducible across the platforms
  Python and NumPy run on, and a digest that changes with the machine is worse than no digest,
  because it looks authoritative. Financial and price values cross as base-10 strings
  (see :mod:`webtrade_research.canonical`).

The refusal is a hard error rather than a coercion. A harness that quietly rounds a digest input
is a harness that quietly changes which artifact it claims to be.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = [
    "ArtifactError",
    "canonical_bytes",
    "digest_bytes",
    "canonical_digest",
    "hex_digest",
]


class ArtifactError(ValueError):
    """A value cannot be content-addressed as written."""


def _reject_floats(value: Any, path: str = "$") -> None:
    """Raise if *value* contains a float anywhere, including nested containers.

    ``json.dumps`` would happily emit ``0.1`` as ``0.1`` on every platform, which is exactly
    the false promise this function exists to refuse: the same source produces the same text,
    but not necessarily the same double, and the text hides that. A caller who needs a
    fractional quantity passes a base-10 string, which is exact.
    """
    if isinstance(value, bool):
        return
    if isinstance(value, float):
        msg = (
            f"refusing a float at {path}: a binary float is not reproducible across "
            f"platforms, so a digest over it is not a reliable identifier. Pass a base-10 "
            f"string (docs/03)."
        )
        raise ArtifactError(msg)
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")


def canonical_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 encoding of *value*.

    The output is a pure function of the value: same input, same bytes, on any machine and
    any Python build. That property is what makes a digest a usable identity rather than a
    fingerprint of one particular run.
    """
    _reject_floats(value)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        msg = f"value is not canonically serialisable: {exc}"
        raise ArtifactError(msg) from exc
    return text.encode("utf-8")


def digest_bytes(payload: bytes) -> str:
    """Return ``sha256:<hex>`` for *payload*."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_digest(value: Any) -> str:
    """Return the content digest of *value*.

    A short form is offered for human-facing text, but the full digest is what an artifact
    carries: a truncated digest is a weaker identity, and using it in a lineage field would
    make two different artifacts collide by construction.
    """
    return digest_bytes(canonical_bytes(value))


def hex_digest(value: Any) -> str:
    """Return the bare 64-character hex digest of *value*, without the algorithm prefix.

    The registry's wire format is bare hex, and that is not a cosmetic difference.
    ``digest_bytes`` prefixes its output with ``sha256:`` so a worker's own artifacts state
    their algorithm, which is the right choice for something a human reads in a log. The Go
    control plane's ``model.Digest`` accepts exactly 64 lowercase hex characters and nothing
    else, and that strictness is deliberate and mutation-tested: a digest that could carry a
    prefix could carry a different algorithm, and a lineage field that accepts one would
    stop identifying which algorithm produced the bytes.

    The two sides therefore disagreed about what a digest *is*, and a research-produced
    dataset fingerprint would have been rejected by the registry that consumes it. The fix
    is on this side, not the Go one. The control plane is authoritative for the registry
    wire format, and loosening a check there to accommodate a worker's internal
    representation would trade a real invariant for a cosmetic convenience.

    Use :func:`digest_bytes` for artifacts this worker names in its own output, and this
    function for anything the control plane will parse as a digest.
    """
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
