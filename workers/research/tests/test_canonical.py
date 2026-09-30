"""Python binding conformance against the shared cross-language corpus.

These tests read ``contracts/fixtures/conformance.json`` directly rather than restating its
cases. If the corpus changes, this suite changes with it; it cannot silently drift into
asserting a stale local copy of the rules (docs/02_POLYGLOT_ENGINEERING_STANDARD.md
section 9).

A binding that disagrees with the corpus cannot be promoted.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from webtrade_research.canonical import (
    ActorType,
    ContractError,
    CrockfordError,
    DecimalError,
    Environment,
    Identifier,
    Money,
    validate_decimal_string,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_PATH = REPO_ROOT / "contracts" / "fixtures" / "conformance.json"


def load_corpus() -> dict[str, Any]:
    with CORPUS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


CORPUS = load_corpus()
CASES: list[dict[str, Any]] = CORPUS["cases"]


def cases_for(schema: str) -> list[dict[str, Any]]:
    return [c for c in CASES if c["schema"] == schema]


def case(name: str) -> dict[str, Any]:
    for c in CASES:
        if c["name"] == name:
            return c
    msg = f"corpus has no case named {name!r}; the corpus and the binding have diverged"
    raise AssertionError(msg)


# --------------------------------------------------------------------------- identifiers


@pytest.mark.parametrize("c", cases_for("identifier.schema.json"), ids=lambda c: c["name"])
def test_identifier_matches_corpus(c: dict[str, Any]) -> None:
    """Every identifier case in the shared corpus must hold for the Python binding."""
    value = c["value"]
    if c["expect"] == "accept":
        assert str(Identifier.parse(value)) == value
    else:
        with pytest.raises(CrockfordError):
            Identifier.parse(value)


def test_identifier_prefix_and_entity() -> None:
    parsed = Identifier.parse("ord_01hq3k7m9x2f5rb8n0v6c4tqwx")
    assert parsed.prefix == "ord_"
    assert len(parsed.payload) == 26
    assert str(parsed) == "ord_01hq3k7m9x2f5rb8n0v6c4tqwx"


def test_identifier_is_immutable() -> None:
    """An identifier is an immutable fact; mutability would let a recorded subject change."""
    parsed = Identifier.parse("ord_01hq3k7m9x2f5rb8n0v6c4tqwx")
    with pytest.raises((AttributeError, TypeError)):
        parsed.payload = "0" * 26  # type: ignore[misc]


def test_ambiguous_characters_rejected() -> None:
    """I, L, O and U are excluded from Crockford Base32 to avoid 1/0 confusion."""
    for bad in ("i", "l", "o", "u"):
        with pytest.raises(CrockfordError):
            Identifier(prefix="ord_", payload=f"01hq3k7m9x2f5rb8n0v6c4tq{bad}x")


# ------------------------------------------------------------------------------ decimal


@pytest.mark.parametrize("c", cases_for("decimal.schema.json"), ids=lambda c: c["name"])
def test_decimal_matches_corpus(c: dict[str, Any]) -> None:
    value = c["value"]
    if c["expect"] == "accept":
        assert validate_decimal_string(value) == value
    else:
        with pytest.raises(DecimalError):
            validate_decimal_string(value)


def test_float_is_refused_not_coerced() -> None:
    """The critical rule: a float must be rejected, never quietly stringified."""
    with pytest.raises(DecimalError, match="IEEE-754"):
        validate_decimal_string(1234.5678)


def test_int_is_refused() -> None:
    """An int is a Python float in disguise for our purposes; it is refused too."""
    with pytest.raises(DecimalError):
        validate_decimal_string(1234)


def test_bool_is_refused() -> None:
    """bool is an int subclass in Python and would otherwise slip through as 0 or 1."""
    with pytest.raises(DecimalError):
        validate_decimal_string(True)


def test_decimal_precision_is_exact() -> None:
    """0.1 + 0.2 must not produce 0.30000000000000004 the way binary floats do."""
    total = Decimal("0.1") + Decimal("0.2")
    assert str(total) == "0.3"
    assert total == Decimal("0.3")


# --------------------------------------------------------------------------------- money


@pytest.mark.parametrize(
    "c",
    [c for c in cases_for("money.schema.json") if c.get("x-binding-level") != "document"],
    ids=lambda c: c["name"],
)
def test_money_matches_corpus(c: dict[str, Any]) -> None:
    """Type-level money cases must hold for the Python binding.

    Document-level cases (a missing key, an unexpected extra key) are excluded here on
    purpose: ``Money`` is a type, not a document parser, and cannot observe either. They
    are enforced by the schema layer, and test_schema_layer_rejects_document_cases proves
    that rather than assuming it.
    """
    value = c["value"]
    if c["expect"] == "accept":
        parsed = Money.parse(value["currency"], value["amount"])
        assert parsed.to_wire() == {"currency": value["currency"], "amount": value["amount"]}
    else:
        with pytest.raises(DecimalError):
            Money.parse(value["currency"], value["amount"])


def test_document_level_money_cases_are_classified() -> None:
    """Document-level cases must be labelled, or a binding could silently skip them."""
    document_cases = [
        c for c in cases_for("money.schema.json") if c.get("x-binding-level") == "document"
    ]
    assert document_cases, "corpus no longer classifies any document-level money case"
    for c in document_cases:
        assert c["expect"] == "reject"
        assert "DOCUMENT-level" in c["note"]


def test_schema_layer_rejects_document_cases() -> None:
    """Run the language-neutral corpus validator to prove the document layer enforces them.

    This is the delegation made verifiable: the Python type does not check document shape,
    so the schema layer must, and it must demonstrably do so.
    """
    import subprocess
    import sys

    validator = REPO_ROOT / "tests" / "contracts" / "validate_contracts.py"
    # S603 is suppressed deliberately: the argument vector is built entirely from the
    # interpreter running this test and a repository-relative path constant. No part of it
    # comes from a fixture, a parameter, or the environment, so there is no untrusted input to
    # check. Invoking the corpus validator as a subprocess is the point — the delegation is
    # only demonstrable by running the real thing rather than reimplementing it in Python.
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(validator)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"schema layer failed the corpus:\n{result.stdout}{result.stderr}"
    )
    assert "CONTRACTS VALID" in result.stdout


def test_money_rejects_float_amount() -> None:
    with pytest.raises(DecimalError, match="float"):
        Money(currency="USD", amount=1.0)  # type: ignore[arg-type]


def test_money_round_trips() -> None:
    original = Money.parse("USD", "1234.5678")
    assert original.to_wire() == {"currency": "USD", "amount": "1234.5678"}
    assert str(original) == "1234.5678 USD"


def test_money_zero_is_valid() -> None:
    """Zero is a real amount with a currency, not a null substitute."""
    assert Money.parse("USD", "0").to_wire()["amount"] == "0"


# ------------------------------------------------------------------------ closed enums


def test_environment_is_closed() -> None:
    assert Environment.validate("paper") == "paper"
    with pytest.raises(ContractError, match="not a supported environment"):
        Environment.validate("production")


def test_actor_type_is_closed() -> None:
    assert ActorType.validate("SYSTEM") == "SYSTEM"
    with pytest.raises(ContractError, match="not a supported actor type"):
        ActorType.validate("ROBOT")


def test_corpus_version_is_pinned() -> None:
    """A binding that does not know which contract version it targets is not promotable."""
    assert CORPUS["contract_package_version"] == "1.0.0"
