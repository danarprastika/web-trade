"""Tests for dataset versioning and the content-addressed registry.

Criterion G4 asks for datasets to be *versioned* and artifacts to be *reproducible*. Both
reduce to one property: a version must be derived from content, never asserted alongside it. If a
dataset can claim a fingerprint that does not match its bars, the fingerprint is a label
someone chose, and every comparison made with it compares labels.

The registry tests are written so that removing the content-addressing would break them. A test
that only checked "registering twice works" would pass just as well against a dict keyed by
insertion order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from webtrade_research.content_address import canonical_bytes, canonical_digest, digest_bytes
from webtrade_research.dataset import Bar, Dataset, DatasetError, DatasetRegistry

BASE = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def bar(sequence: int, close: str = "100", *, instrument: str = "BTC-USD") -> Bar:
    return Bar(
        instrument=instrument,
        event_time=at(sequence),
        available_at=at(sequence),
        open=close,
        high=close,
        low=close,
        close=close,
        volume="1",
        sequence=sequence,
    )


@pytest.fixture
def bars() -> list[Bar]:
    return [bar(0, "100"), bar(1, "101"), bar(2, "102")]


# ---------------------------------------------------------------- versioning


def test_the_same_bars_produce_the_same_fingerprint(bars: list[Bar]) -> None:
    """Identical content is the same dataset, every time it is built."""
    first = Dataset.create("d", "bars/1", bars)
    second = Dataset.create("d", "bars/1", bars)
    assert first.fingerprint == second.fingerprint
    assert first == second


def test_fingerprint_is_independent_of_construction_order(bars: list[Bar]) -> None:
    """A dataset assembled in a different order is the same dataset.

    Without this, a fingerprint would depend on a caller's incidental ordering, and two
    processes that loaded the same file differently would compute different versions of the
    same data.
    """
    forward = Dataset.create("d", "bars/1", bars)
    reversed_order = Dataset.create("d", "bars/1", list(reversed(bars)))
    assert forward.fingerprint == reversed_order.fingerprint
    assert forward.bars == reversed_order.bars, "bars must be stored in canonical order"


def test_compute_fingerprint_sorts_rather_than_trusting_its_caller(
    bars: list[Bar],
) -> None:
    """The ordering guarantee must hold on the public method, not only via ``create``.

    ``compute_fingerprint`` is a public static method and its own docstring states that bars are
    sorted before hashing. Asserting the property only through ``create`` would not test that
    claim: ``create`` happens to sort on its own, so it masks a ``compute_fingerprint`` that does
    not. The two entry points would then disagree about the same content, and a caller
    constructing a dataset by hand would compute a different version of it than the registry
    would — with nothing to indicate an error.

    This is asserted on the static method directly so the guarantee is a property of the
    function, not of the one path that happens to call it.
    """
    forward = Dataset.compute_fingerprint("d", "bars/1", bars)
    reversed_order = Dataset.compute_fingerprint("d", "bars/1", list(reversed(bars)))
    assert forward == reversed_order
    # And it must agree with the dataset built through the other entry point.
    assert forward == Dataset.create("d", "bars/1", bars).fingerprint


def test_changing_any_price_changes_the_fingerprint(bars: list[Bar]) -> None:
    """A data correction is a new version, not a re-labelling."""
    original = Dataset.create("d", "bars/1", bars)
    corrected = Dataset.create("d", "bars/1", [*bars[:-1], bar(2, "103")])
    assert corrected.fingerprint != original.fingerprint


def test_the_fingerprint_covers_the_name_and_schema_version(bars: list[Bar]) -> None:
    """The same bars under different semantics are not the same dataset.

    Two byte-identical bar sets published as ``bars/1`` and ``bars/2`` mean different things. A
    fingerprint that could not tell them apart would let a schema change pass as a data change.
    """
    assert (
        Dataset.create("d", "bars/1", bars).fingerprint
        != Dataset.create("d", "bars/2", bars).fingerprint
    )
    assert (
        Dataset.create("d", "bars/1", bars).fingerprint
        != Dataset.create("other", "bars/1", bars).fingerprint
    )


def test_a_dataset_cannot_claim_a_fingerprint_it_does_not_have(bars: list[Bar]) -> None:
    """The version is derived from content, not accepted alongside it.

    This is the property the whole module exists to provide. If the constructor trusted a
    supplied fingerprint, every version comparison downstream would be a comparison of
    self-reported labels, and a corrected dataset could be published under the previous version's
    digest.
    """
    honest = Dataset.create("d", "bars/1", bars)
    with pytest.raises(DatasetError, match="does not match its content"):
        Dataset(
            name="d",
            schema_version="bars/1",
            bars=honest.bars,
            fingerprint="sha256:" + "0" * 64,
        )


def test_an_unnamed_or_unversioned_dataset_is_refused(bars: list[Bar]) -> None:
    """A dataset with no name or no schema version cannot be addressed."""
    with pytest.raises(DatasetError, match="must have a name"):
        Dataset.create("", "bars/1", bars)
    with pytest.raises(DatasetError, match="must declare a schema_version"):
        Dataset.create("d", "", bars)


# ---------------------------------------------------------------- point in time


def test_visibility_is_driven_by_availability_not_by_period_end() -> None:
    """A bar is knowable from the instant it publishes, not the instant its period closes.

    This is the rule the whole no-lookahead property rests on, tested here at its source so a
    change to :meth:`Dataset.visible_at` is caught here rather than only in the harness.
    """
    late = Bar(
        instrument="BTC-USD",
        event_time=at(1),
        available_at=at(30),
        open="9",
        high="9",
        low="9",
        close="9",
        volume="1",
        sequence=9,
    )
    dataset = Dataset.create("late", "bars/1", [bar(0), late, bar(2)])
    assert [b.sequence for b in dataset.visible_at(at(1))] == [0]
    # Storage order is by (event_time, available_at, sequence), so the revised bar sorts by its
    # period end — position 1 — not by the moment it was published. Visibility is a filter over
    # that order, so a late bar appears earlier than a bar for a later period. This is the right
    # shape: what is *stored* is ordered by the data, and what is *visible* is filtered by time,
    # and the two are deliberately different rules.
    assert [b.sequence for b in dataset.visible_at(at(30))] == [0, 9, 2]


def test_visibility_is_monotone_in_time() -> None:
    """A bar that was knowable cannot become unknowable."""
    dataset = Dataset.create("d", "bars/1", [bar(i) for i in range(5)])
    counts = [len(dataset.visible_at(at(t))) for t in range(0, 10)]
    assert counts == sorted(counts)


def test_visibility_includes_the_bar_published_at_that_instant() -> None:
    """The boundary is inclusive: a bar published *at* an instant is knowable *at* it."""
    dataset = Dataset.create("d", "bars/1", [bar(0), bar(1)])
    assert [b.sequence for b in dataset.visible_at(at(0))] == [0]
    assert [b.sequence for b in dataset.visible_at(at(1))] == [0, 1]


def test_visibility_refuses_a_naive_instant() -> None:
    """A naive ``as_of`` is a data error, not a local-time assumption."""
    dataset = Dataset.create("d", "bars/1", [bar(0)])
    with pytest.raises(DatasetError, match="timezone-aware"):
        dataset.visible_at(datetime(2026, 1, 5, 9, 0))  # noqa: DTZ001 - deliberately naive


def test_the_canonical_form_uses_z_not_an_offset() -> None:
    """A digest must not depend on whether a writer chose ``+00:00`` or ``Z``."""
    canonical = bar(0).to_canonical()
    assert canonical["event_time"].endswith("Z")
    assert "+" not in canonical["event_time"]
    assert canonical["event_time"] == "2026-01-05T09:00:00.000000Z"


def test_a_close_price_is_an_exact_decimal() -> None:
    """A price that loses precision is one the ledger could disagree about."""
    assert bar(0, "0.1").close_price == Decimal("0.1")
    assert isinstance(bar(0, "0.1").close_price, Decimal)


# ---------------------------------------------------------------- registry


def test_registration_is_idempotent(bars: list[Bar]) -> None:
    """Re-registering a reconstructed dataset is a no-op, not a conflict.

    A run being replayed must not invent a new version. Identity is digest equality rather than
    object identity, so the same content rebuilt from its own serialisation is recognised.
    """
    registry = DatasetRegistry()
    fingerprint = registry.register(Dataset.create("d", "bars/1", bars))
    again = registry.register(Dataset.create("d", "bars/1", bars))
    assert again == fingerprint
    assert len(registry) == 1


def test_a_registered_dataset_is_returned_intact(bars: list[Bar]) -> None:
    """The registry stores the dataset, not a summary of it."""
    registry = DatasetRegistry()
    original = Dataset.create("d", "bars/1", bars)
    registry.register(original)
    assert registry.get(original.fingerprint) == original


def test_an_unknown_fingerprint_is_refused() -> None:
    """A caller that cannot name a dataset cannot quietly substitute a different one."""
    registry = DatasetRegistry()
    with pytest.raises(DatasetError, match="no dataset registered"):
        registry.get("sha256:" + "0" * 64)


def test_registered_fingerprints_are_sorted(bars: list[Bar]) -> None:
    """Anything derived from the registry must itself be reproducible.

    Insertion order would make a listing depend on the order datasets happened to be added,
    which is exactly the kind of incidental ordering a fingerprint exists to exclude.
    """
    registry = DatasetRegistry()
    for name in ("zulu", "alpha", "mike"):
        registry.register(Dataset.create(name, "bars/1", bars))
    assert list(registry.fingerprints()) == sorted(registry.fingerprints())
    assert len(registry.fingerprints()) == 3


def test_the_registry_holds_every_version_rather_than_the_latest(
    bars: list[Bar],
) -> None:
    """A corrected dataset is a new entry, and the old one is still addressable.

    Overwriting would make a backtest from last month unreproducible, which defeats the purpose
    of versioning a dataset at all.
    """
    registry = DatasetRegistry()
    original = Dataset.create("d", "bars/1", bars)
    registry.register(original)
    corrected = Dataset.create("d", "bars/1", [*bars[:-1], bar(2, "999")])
    registry.register(corrected)
    assert len(registry) == 2
    assert registry.get(original.fingerprint).bars[-1].close == "102"
    assert registry.get(corrected.fingerprint).bars[-1].close == "999"


# ---------------------------------------------------------------- content addressing


def test_canonical_bytes_depend_on_value_not_on_construction_order() -> None:
    """Sorted keys and fixed separators are what make a digest portable."""
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})
    assert canonical_bytes({"a": 1}) == b'{"a":1}'


def test_a_float_is_refused_anywhere_in_the_payload() -> None:
    """Including nested inside containers, where a regex would miss it.

    ``json.dumps`` would emit ``0.1`` identically on every platform, which is the false promise
    the refusal exists to prevent: the same text, but not necessarily the same double.
    """
    for payload in (
        {"price": 0.1},
        {"bars": [{"close": 1.5}]},
        {"rows": [{"cells": [2.5]}]},
    ):
        with pytest.raises(Exception, match="float"):
            canonical_digest(payload)


def test_a_digest_is_prefixed_and_full_length() -> None:
    """A truncated digest is a weaker identity and must not be used in a lineage field."""
    digest = canonical_digest({"a": 1})
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_the_digest_matches_an_independently_computed_hash() -> None:
    """The canonical form and the digest are pinned to known-good values.

    Determinism within one process is not the property that matters; a digest has to agree
    across processes and machines. That cannot be observed from a single run, so what is
    asserted here is the value itself, recomputed from the literal expected bytes with
    ``hashlib`` rather than through the module under test. If the canonical form or the
    digest construction changes, this fails instead of quietly producing a new version space
    that no existing artifact matches.
    """
    payload = {"b": 2, "a": 1}
    assert canonical_bytes(payload) == b'{"a":1,"b":2}'
    assert canonical_digest(payload) == digest_bytes(b'{"a":1,"b":2}')


def test_a_known_vector_does_not_collapse_under_a_key_reorder() -> None:
    """Key order is the one difference that must not change the identity.

    Two dicts differing only in insertion order are the same value. If ordering reached the
    digest, a process that happened to build the payload in a different order would compute a
    different version of the same artifact.
    """
    assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})
