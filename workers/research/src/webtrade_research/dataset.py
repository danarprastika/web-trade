"""Immutable, versioned, content-addressed datasets.

docs/02 restricts Python to research and backtest workloads, which "receives immutable/
versioned datasets". This module is the receiving end of that contract, and it exists to make
three properties structural rather than aspirational:

**Versioned.** Every dataset carries a content digest, and a registry refuses two different
payloads claiming the same digest. Versioning is not a field someone remembers to bump; it is
a function of the bytes, so a dataset cannot claim to be version 3 while holding version 2's
data.

**Immutable.** :class:`Dataset` is a frozen slotted dataclass holding a tuple. There is no
mutator to forget to call, and no in-place edit that could leave a fingerprint describing
content the object no longer has.

**Point-in-time honest.** Each :class:`Bar` carries two timestamps, and keeping them apart is
the whole mechanism by which lookahead bias becomes detectable:

``event_time``
    when the market period the bar describes ended.

``available_at``
    the earliest instant at which this bar could have been known to anyone.

These are equal in the common case and are *not* equal whenever a bar is revised, republished
late, or drawn from a feed with delivery lag. A backtest that decides at time *t* must see
only bars with ``available_at <= t``. A harness that instead slices on ``event_time`` will
happily show a strategy a bar for a period that has already closed but that had not yet been
published at decision time, and the resulting equity curve will look better than the strategy
deserves. That error is silent, it is profitable-looking, and it is the single most common way
a backtest misleads.

Storing both timestamps makes the distinction available to the engine. It does not by itself
prevent misuse; :mod:`webtrade_backtest.harness` is what enforces it, and this module is
written so that the correct slice is the easy one.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final

from webtrade_research.canonical import validate_decimal_string
from webtrade_research.content_address import canonical_digest

__all__ = [
    "DatasetError",
    "Bar",
    "Dataset",
    "DatasetRegistry",
]


class DatasetError(ValueError):
    """A dataset is malformed, duplicated, or otherwise not admissible."""


def _require_utc(value: datetime, field: str) -> datetime:
    """Reject a timestamp that is not timezone-aware UTC.

    Mixing aware and naive timestamps raises deep inside an arithmetic comparison with a
    message about ``datetime`` rather than about the dataset, and a naive local timestamp
    silently orders wrong against an aware one. The rule is that a bar timestamp is always
    UTC, exactly as the Go contract package requires of its own timestamps.
    """
    offset = value.utcoffset() if value.tzinfo is not None else None
    if offset is None:
        msg = f"{field} must be timezone-aware and UTC, got {value!r}"
        raise DatasetError(msg)
    if offset.total_seconds() != 0:
        msg = f"{field} must be UTC, got offset {offset}"
        raise DatasetError(msg)
    return value


@dataclass(frozen=True, slots=True, order=True)
class Bar:
    """One price bar with both its period end and its first-availability time.

    Ordered by ``(event_time, available_at, sequence)`` so that iteration order is a function
    of the data and never of insertion order or hash order. A backtest whose result depends on
    iteration order is not reproducible.
    """

    instrument: str
    event_time: datetime
    available_at: datetime
    open: str
    high: str
    low: str
    close: str
    volume: str
    sequence: int

    def __post_init__(self) -> None:
        if not self.instrument:
            msg = "a bar must name its instrument"
            raise DatasetError(msg)
        _require_utc(self.event_time, "event_time")
        _require_utc(self.available_at, "available_at")
        # A bar cannot become available before the period it describes has ended. The
        # converse is legal and normal: late publication is why available_at exists.
        if self.available_at < self.event_time:
            msg = (
                f"bar for {self.instrument} is available at {self.available_at.isoformat()}, "
                f"before its period ends at {self.event_time.isoformat()}; that is a data "
                f"error, not lookahead"
            )
            raise DatasetError(msg)
        for field in ("open", "high", "low", "close", "volume"):
            validate_decimal_string(getattr(self, field))
        if self.sequence < 0:
            msg = f"sequence must be non-negative, got {self.sequence}"
            raise DatasetError(msg)

    def to_canonical(self) -> dict[str, object]:
        """Return the wire form used for content addressing.

        Timestamps are rendered in the canonical ``Z`` form rather than by ``isoformat()``,
        because a digest must not depend on whether a writer chose ``+00:00`` or ``Z``, and
        because the canonical form is what the control plane will compare against.
        """
        return {
            "instrument": self.instrument,
            "event_time": self.event_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "available_at": self.available_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "sequence": self.sequence,
        }

    @property
    def close_price(self) -> Decimal:
        """The close as an exact decimal.

        Decimal, not float: a price that loses precision is a price the backtest and the
        ledger could disagree about, and the whole point of the research/control-plane
        boundary is that they must not.
        """
        return Decimal(self.close)


@dataclass(frozen=True, slots=True)
class Dataset:
    """An immutable, ordered, content-addressed set of bars.

    The fingerprint is computed once at construction from the canonical form of the bars
    *plus* the dataset's declared name and schema version. Including the metadata matters:
    two byte-identical bar sets published under different semantics are not the same dataset,
    and a fingerprint that could not tell them apart would let a schema change pass as a data
    change.
    """

    name: str
    schema_version: str
    bars: tuple[Bar, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.name:
            msg = "a dataset must have a name"
            raise DatasetError(msg)
        if not self.schema_version:
            msg = "a dataset must declare a schema_version"
            raise DatasetError(msg)
        expected = self.compute_fingerprint(self.name, self.schema_version, self.bars)
        if self.fingerprint != expected:
            msg = (
                f"dataset fingerprint {self.fingerprint!r} does not match its content "
                f"({expected!r}); a dataset cannot claim a version it does not have"
            )
            raise DatasetError(msg)

    @staticmethod
    def compute_fingerprint(
        name: str, schema_version: str, bars: Iterable[Bar]
    ) -> str:
        """Return the content digest for a dataset payload.

        Bars are sorted before hashing. A dataset assembled in two different orders is the
        same dataset, and a fingerprint that distinguished them would make reproducibility
        depend on a caller's incidental ordering.
        """
        canonical_bars = [bar.to_canonical() for bar in sorted(bars)]
        return canonical_digest(
            {
                "name": name,
                "schema_version": schema_version,
                "bars": canonical_bars,
            }
        )

    @classmethod
    def create(
        cls, name: str, schema_version: str, bars: Iterable[Bar]
    ) -> Dataset:
        """Build a dataset, computing its fingerprint from the content."""
        materialised = tuple(sorted(bars))
        return cls(
            name=name,
            schema_version=schema_version,
            bars=materialised,
            fingerprint=cls.compute_fingerprint(name, schema_version, materialised),
        )

    def __len__(self) -> int:
        return len(self.bars)

    def __iter__(self) -> Iterator[Bar]:
        return iter(self.bars)

    def visible_at(self, as_of: datetime) -> tuple[Bar, ...]:
        """Return only the bars that were knowable at *as_of*.

        This is the only sanctioned way to read a dataset for a decision, and it filters on
        ``available_at`` rather than ``event_time``. The distinction is the whole point: a bar
        whose period ended at 10:00 but which was not published until 12:00 is invisible to a
        decision made at 11:00, even though its period had closed.

        Callers that need a different rule must not reimplement it here; a second accessor is
        a second opportunity to leak.
        """
        _require_utc(as_of, "as_of")
        return tuple(bar for bar in self.bars if bar.available_at <= as_of)

    def instruments(self) -> tuple[str, ...]:
        return tuple(sorted({bar.instrument for bar in self.bars}))


class DatasetRegistry:
    """Append-only registry of immutable datasets, keyed by fingerprint.

    Append-only rather than mutable for the same reason the audit chain is: a registry that
    can be rewritten is not evidence of what was used. Registering a digest that is already
    present is idempotent, which lets a caller replay a run without inventing a new version.
    Registering *different content* under a known digest is impossible by construction, because
    the digest is derived from the content.
    """

    def __init__(self) -> None:
        self._by_fingerprint: Final[dict[str, Dataset]] = {}

    def register(self, dataset: Dataset) -> str:
        """Add *dataset*, or return the existing one if already present.

        Idempotence is checked by digest equality, not by object identity, so re-registering a
        dataset reconstructed from its own serialization is a no-op rather than a conflict.
        """
        existing = self._by_fingerprint.get(dataset.fingerprint)
        if existing is not None:
            if existing != dataset:
                # Unreachable given the content-addressed fingerprint; kept because an
                # unreachable branch here would be untested code guarding the one invariant
                # the whole registry exists to protect.
                msg = (  # pragma: no cover - defence in depth
                    f"fingerprint {dataset.fingerprint!r} is already registered with different "
                    f"content"
                )
                raise DatasetError(msg)
            return dataset.fingerprint
        self._by_fingerprint[dataset.fingerprint] = dataset
        return dataset.fingerprint

    def get(self, fingerprint: str) -> Dataset:
        """Return the dataset for *fingerprint*, or raise if it was never registered.

        A caller that cannot name a dataset cannot quietly substitute a different one.
        """
        try:
            return self._by_fingerprint[fingerprint]
        except KeyError as exc:
            msg = f"no dataset registered with fingerprint {fingerprint!r}"
            raise DatasetError(msg) from exc

    def fingerprints(self) -> tuple[str, ...]:
        """Every registered fingerprint, sorted.

        Sorted rather than insertion-ordered so that anything derived from the registry is
        itself reproducible.
        """
        return tuple(sorted(self._by_fingerprint))

    def __len__(self) -> int:
        return len(self._by_fingerprint)
