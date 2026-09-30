"""Python binding of the canonical contract package.

This module mirrors the Go binding in ``contracts/go``. It exists because a type that
crosses the research/control-plane boundary must be defined once in the canonical contract
repository and validated here, not re-invented in Python (docs/02 section "Contract-first
interoperability").

The shared corpus is ``contracts/fixtures/conformance.json``. A Python binding that
disagreed with it could not be promoted (docs/02 section 9).

Decimal policy
--------------
Money and quantity use :class:`decimal.Decimal` over a base-10 string, never
:class:`float`. Python's ``float`` is IEEE-754 binary and would silently lose precision
on values such as ``0.1``; a research harness that quietly rounds a price is a research
harness that quietly lies. ``Decimal`` is constructed here only from strings, and
``Money`` refuses a float at construction time rather than coercing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

__all__ = [
    "CrockfordError",
    "Identifier",
    "Money",
    "DecimalError",
    "Environment",
    "ActorType",
    "PREFIXES",
    "validate_decimal_string",
]

# Crockford Base32: 0-9, a-h, j, k, m, n, p-t, v-z. I, L, O and U are omitted because
# they are routinely confused with 1 and 0 in transcription, speech and OCR.
_CROCKFORD = re.compile(r"^[0-9a-hjkmnp-tv-z]{26}$")
_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")
_CURRENCY = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")

PAYLOAD_LENGTH: Final = 26

PREFIXES: Final[dict[str, str]] = {
    "cmd_": "Command",
    "evt_": "Event",
    "ord_": "Order",
    "str_": "Strategy",
    "mdl_": "Model",
    "run_": "Run",
    "pos_": "Position",
    "led_": "Ledger entry",
}

# Environment is a closed set (docs/01 section 4). "production" is deliberately not a
# member: inventing an alias would break the isolation guarantee that lower environments
# can never hold live credentials.
_ENVIRONMENTS: Final = frozenset({"dev", "test", "staging", "paper", "shadow", "live"})

_ACTOR_TYPES: Final = frozenset({"HUMAN", "SERVICE", "AGENT", "SYSTEM"})


class ContractError(ValueError):
    """Base class for every canonical contract violation."""


class CrockfordError(ContractError):
    """An identifier did not satisfy the canonical format."""


class DecimalError(ContractError):
    """A decimal or money value did not satisfy the canonical format."""


def validate_decimal_string(value: object) -> str:
    """Return *value* if it is a canonical base-10 decimal string, else raise.

    A ``float`` or ``int`` is rejected outright rather than stringified. Silently
    accepting ``1234.5678`` would let a binary float enter a financial contract, which is
    precisely the failure this contract exists to prevent.
    """
    if isinstance(value, bool) or isinstance(value, (float, int)):
        msg = (
            f"refusing {type(value).__name__} as a financial value: "
            "IEEE-754 must not cross a financial contract (docs/03). "
            "Pass a base-10 string or a decimal.Decimal."
        )
        raise DecimalError(msg)
    if not isinstance(value, str):
        msg = f"expected a string, got {type(value).__name__}"
        raise DecimalError(msg)
    if not _DECIMAL.match(value):
        msg = f"{value!r} is not a canonical base-10 decimal string"
        raise DecimalError(msg)
    return value


@dataclass(frozen=True, slots=True)
class Identifier:
    """A typed, prefixed, lowercase Crockford Base32 identifier.

    Frozen and slotted: an identifier is an immutable fact, and a mutable one would let a
    later stage silently change the subject of a recorded event.
    """

    prefix: str
    payload: str

    def __post_init__(self) -> None:
        if self.prefix not in PREFIXES:
            msg = f"{self.prefix!r} is not a registered prefix"
            raise CrockfordError(msg)
        if not _CROCKFORD.match(self.payload):
            msg = (
                f"{self.payload!r} is not 26 lowercase Crockford Base32 characters. "
                "Uppercase is rejected rather than normalised, so a producer emitting "
                "'ORD_...' fails loudly instead of being silently corrected."
            )
            raise CrockfordError(msg)

    def __str__(self) -> str:
        return f"{self.prefix}{self.payload}"

    @classmethod
    def parse(cls, raw: str) -> Identifier:
        """Parse the canonical textual form, for example ``ord_01hq3k7m9x2f5rb8n0v6c4tqwx``."""
        for prefix in PREFIXES:
            if raw.startswith(prefix):
                return cls(prefix=prefix, payload=raw[len(prefix) :])
        msg = f"{raw!r} has no registered prefix"
        raise CrockfordError(msg)


@dataclass(frozen=True, slots=True)
class Money:
    """An amount bound to a currency. Never a bare number, never a float."""

    currency: str
    amount: Decimal

    def __post_init__(self) -> None:
        if not _CURRENCY.match(self.currency):
            msg = f"{self.currency!r} is not a valid currency code"
            raise DecimalError(msg)
        if isinstance(self.amount, float):  # pragma: no cover - guarded by construction
            msg = "Money must not be constructed from a float"
            raise DecimalError(msg)
        if not isinstance(self.amount, Decimal):
            msg = "Money.amount must be a decimal.Decimal"
            raise DecimalError(msg)
        try:
            canonical = format(self.amount, "f")
        except InvalidOperation as exc:  # pragma: no cover - defensive
            msg = f"amount {self.amount!r} is not representable as a decimal string"
            raise DecimalError(msg) from exc
        validate_decimal_string(canonical)

    @classmethod
    def parse(cls, currency: str, amount: str) -> Money:
        """Build from canonical wire strings."""
        validate_decimal_string(amount)
        return cls(currency=currency, amount=Decimal(amount))

    def to_wire(self) -> dict[str, str]:
        """Serialise to the canonical contract shape."""
        return {"currency": self.currency, "amount": format(self.amount, "f")}

    def __str__(self) -> str:
        return f"{format(self.amount, 'f')} {self.currency}"


def _validate_choice(value: str, allowed: frozenset[str], kind: str) -> str:
    """Reject a value outside a closed set rather than mapping it to a default.

    Unknown enum values are treated as unsupported, never silently mapped
    (docs/03_CANONICAL_CONTRACTS.md, compatibility).
    """
    if value not in allowed:
        msg = f"{value!r} is not a supported {kind}; expected one of {sorted(allowed)}"
        raise ContractError(msg)
    return value


class Environment:
    """Closed environment namespace."""

    ALL: Final = _ENVIRONMENTS

    @staticmethod
    def validate(value: str) -> str:
        return _validate_choice(value, _ENVIRONMENTS, "environment")


class ActorType:
    """Closed actor classification."""

    ALL: Final = _ACTOR_TYPES

    @staticmethod
    def validate(value: str) -> str:
        return _validate_choice(value, _ACTOR_TYPES, "actor type")
