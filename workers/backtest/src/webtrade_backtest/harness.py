"""Deterministic, point-in-time backtest harness.

This module answers one question — "would this have worked?" — and that question is only
meaningful if two things are true. The answer must be *reproducible*, and it must not be
*informed by the future*. The second is the harder one, because a backtest that peeks at a bar
before it was published does not crash, does not warn, and produces a better-looking equity
curve than the strategy deserves.

Determinism
-----------
The contract is byte-identical results for the same inputs, on any machine, on any run
(docs/11 G4). That rules out, by construction rather than by review:

* ambient wall-clock time — nothing here reads the clock, and the harness has no ``now``;
* unseeded randomness — a seed is a required parameter with no default;
* unordered iteration — decisions are driven by an explicit, sorted decision schedule;
* host-dependent float accumulation — all arithmetic is :class:`decimal.Decimal` under an
  explicit context, so there is no vectorisation or summation-order variation to disagree
  about.

The last point is worth expanding. A float64 backtest can differ between two machines for
reasons that have nothing to do with the strategy: fused multiply-add, summation order under
threaded reduction, and libm differences. None of those are bugs, and all of them make a
result irreproducible, which means the result cannot be promoted. Decimal arithmetic is slower
and that is the correct trade for an engine whose output is a governance artifact.

No lookahead bias
-----------------
Every decision is taken at an explicit ``as_of`` instant, and the strategy is shown a
:class:`MarketView` built from :meth:`Dataset.visible_at`, which filters on ``available_at``
rather than ``event_time``. The view is a frozen tuple with no lookup method, so a strategy
cannot ask for a bar it was not given; to see more, it would have to be given more.

That is a control, not an observation, and controls are only real if removing them is visible.
Two mechanisms make removal detectable:

* the result records, for every decision, the set of bar sequences the strategy could see
  (:attr:`DecisionRecord.visible_sequences`), so an artifact carries its own evidence that
  visibility was monotone;
* :func:`assert_no_lookahead` re-derives the visibility claim from the result and the dataset
  independently of the engine, so a bug in the slicing is caught by a different code path than
  the one that could introduce it.

Authority boundary
------------------
This module holds no credentials, opens no connection, and submits nothing
(docs/02, docs/25 section 4). It emits a proposed artifact; promotion is a reviewed control-plane
workflow. A backtest result is a claim about the past, not an authorisation to act.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Final, Protocol, runtime_checkable

from webtrade_research.dataset import Bar, Dataset, DatasetError

__all__ = [
    "BacktestError",
    "LookaheadError",
    "MarketView",
    "Decision",
    "DecisionRecord",
    "BacktestParams",
    "BacktestResult",
    "Strategy",
    "run_backtest",
    "assert_no_lookahead",
]

# Fixed precision for every decimal operation the harness performs. The decimal context is a
# process-global setting, so leaving it to ambient configuration would make results depend on
# whatever else the process did first. Pinning it here is what makes the engine reproducible
# when it is called from a larger program rather than from a test.
DECIMAL_PRECISION: Final = 34


class BacktestError(ValueError):
    """The harness was asked to do something it cannot do reproducibly."""


class LookaheadError(BacktestError):
    """A decision was taken with knowledge it could not have had.

    Raised by :func:`assert_no_lookahead` when a recorded decision saw a bar that was not yet
    available, and by the harness itself when asked to schedule a decision before the data it
    depends on exists. It is a distinct type because a lookahead failure and an arithmetic
    failure call for different responses: the first invalidates the result and usually the
    strategy, the second is a bug in a number.
    """


@runtime_checkable
class MarketView(Protocol):
    """What a strategy is allowed to see at one instant.

    Deliberately not the :class:`Dataset`. A dataset offers iteration over everything it
    holds; a view offers only what was knowable. Handing a strategy the dataset and asking it
    to behave would make correctness a property of the strategy, and one strategy written
    carelessly would be enough to produce a curve that looks tradable.
    """

    @property
    def as_of(self) -> datetime: ...

    @property
    def bars(self) -> tuple[Bar, ...]: ...

    @property
    def random(self) -> random.Random: ...


@dataclass(frozen=True, slots=True)
class _View:
    """Concrete point-in-time view handed to a strategy.

    Module-level and frozen rather than built per call, so a strategy cannot learn anything
    from the identity of the view object. It holds the bars and a seeded generator and offers
    no lookup, no length-agnostic indexing into the dataset, and no way to reach a bar that
    ``available_at`` excluded.
    """

    as_of: datetime
    bars: tuple[Bar, ...]
    random: random.Random


@dataclass(frozen=True, slots=True)
class Decision:
    """A strategy's intent at one instant.

    ``side`` is ``"buy"``, ``"sell"``, or ``"hold"``; ``quantity`` is a base-10 string rather
    than a float, because a quantity that rounds differently on two machines is a quantity
    whose result cannot be reproduced.
    """

    as_of: datetime
    side: str
    quantity: str
    reason: str = ""


_SIDES: Final = frozenset({"buy", "sell", "hold"})


@runtime_checkable
class Strategy(Protocol):
    """A decision function over the point-in-time view."""

    def decide(self, view: MarketView) -> Decision: ...


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One decision, with the evidence of what the strategy could see.

    ``visible_sequences`` is what makes the no-lookahead property auditable after the fact.
    Without it, "the backtest had no lookahead bias" is an assertion by the author; with it,
    the claim can be re-derived from the artifact.
    """

    as_of: datetime
    side: str
    quantity: str
    reason: str
    visible_sequences: tuple[int, ...]
    reference_price: str | None


@dataclass(frozen=True, slots=True)
class BacktestParams:
    """Everything that is not the dataset.

    ``seed`` has no default. A backtest that draws random numbers without recording a seed is
    irreproducible, and an irreproducible result cannot be promoted, so the omission must be a
    type error rather than a silent source of nondeterminism.
    """

    seed: int
    start: datetime
    end: datetime
    initial_cash: str = "100000"

    def __post_init__(self) -> None:
        if self.end <= self.start:
            msg = f"end {self.end.isoformat()} must be after start {self.start.isoformat()}"
            raise BacktestError(msg)
        from webtrade_research.canonical import validate_decimal_string

        validate_decimal_string(self.initial_cash)
        if Decimal(self.initial_cash) <= 0:
            msg = f"initial_cash must be positive, got {self.initial_cash!r}"
            raise BacktestError(msg)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """The outcome of a run, with everything needed to reproduce and audit it."""

    dataset_fingerprint: str
    strategy_name: str
    params: BacktestParams
    decisions: tuple[DecisionRecord, ...]
    final_cash: str
    trades: int

    def to_canonical(self) -> dict[str, object]:
        """Return the wire form used for content addressing.

        Timestamps use the canonical ``Z`` form so the digest does not depend on the writer's
        choice of ``+00:00`` versus ``Z``.
        """
        return {
            "dataset_fingerprint": self.dataset_fingerprint,
            "strategy_name": self.strategy_name,
            "params": {
                "seed": self.params.seed,
                "start": self.params.start.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "end": self.params.end.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "initial_cash": self.params.initial_cash,
            },
            "decisions": [
                {
                    "as_of": d.as_of.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "side": d.side,
                    "quantity": d.quantity,
                    "reason": d.reason,
                    "visible_sequences": list(d.visible_sequences),
                    "reference_price": d.reference_price,
                }
                for d in self.decisions
            ],
            "final_cash": self.final_cash,
            "trades": self.trades,
        }


def _build_view(bars: Sequence[Bar], as_of: datetime, rng: random.Random) -> _View:
    """A frozen, read-only view of the bars knowable at *as_of*.

    Implemented as a concrete frozen dataclass rather than by exposing the dataset, so that the
    view has no method which could return something the visibility filter excluded.
    """
    return _View(as_of=as_of, bars=tuple(bars), random=rng)


def _decision_schedule(dataset: Dataset, params: BacktestParams) -> tuple[datetime, ...]:
    """Return the instants at which a decision is taken.

    The schedule is derived from the dataset's ``available_at`` values within the requested
    window, deduplicated and sorted. Deciding at bar *arrival* rather than on a wall-clock
    grid is what keeps the run a function of the data: no clock is read, and two runs over the
    same dataset decide at the same instants regardless of when they execute.

    Deciding at ``available_at`` is also the only schedule that can be honest. A decision taken
    at ``event_time`` would be taken before the data for that bar was published, which is
    lookahead by construction.
    """
    instants = sorted(
        {
            bar.available_at
            for bar in dataset.bars
            if params.start <= bar.available_at <= params.end
        }
    )
    return tuple(instants)


def run_backtest(
    dataset: Dataset,
    strategy: Strategy,
    params: BacktestParams,
    *,
    strategy_name: str,
) -> BacktestResult:
    """Run *strategy* over *dataset* between the instants named by *params*.

    The returned result is a pure function of its three arguments. It carries no timestamp of
    its own, no host information, and no run identifier, because any of those would make two
    identical runs differ and defeat the reproducibility requirement.
    """
    if not strategy_name:
        msg = "a backtest result must name its strategy; an anonymous result cannot be reviewed"
        raise BacktestError(msg)

    schedule = _decision_schedule(dataset, params)
    if not schedule:
        msg = (
            f"no bar in {dataset.fingerprint} became available between "
            f"{params.start.isoformat()} and {params.end.isoformat()}; the run would be empty"
        )
        raise BacktestError(msg)

    # Each decision gets its own generator, seeded from the run seed *and* the decision index.
    # Seeding a single shared generator would make the stream depend on how many draws earlier
    # decisions happened to make, so inserting or removing one decision would silently change
    # every later result — reproducible, but not comparable. Seeding per index makes each
    # decision's randomness a function of its position alone.
    #
    # `random.Random` seeded from a string uses SHA-512 of that string, which is specified and
    # therefore identical on every platform and Python build, unlike a float or an int.
    #
    # S311 is suppressed deliberately. The flagged rule is correct about secrets and
    # inapplicable here: this generator is not a secret and is not defending an attacker, it is
    # sampling a strategy's own decisions so the run can be replayed. Substituting `secrets`
    # would satisfy the linter by destroying the property the whole module exists to provide —
    # a result nobody can reproduce cannot be promoted (docs/11, G4). The rule is about not
    # using a predictable generator *as* a secret; here the output is required to be
    # predictable, and nothing authenticates on it.
    def stream_for(index: int) -> random.Random:
        return random.Random(f"webtrade-backtest:{params.seed}:{index}")  # noqa: S311

    records: list[DecisionRecord] = []
    cash = Decimal(params.initial_cash)
    trades = 0

    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        for index, as_of in enumerate(schedule):
            visible = dataset.visible_at(as_of)
            view = _build_view(visible, as_of, stream_for(index))
            decision = strategy.decide(view)
            _validate_decision(decision, as_of)
            if decision.side == "hold":
                records.append(
                    DecisionRecord(
                        as_of=as_of,
                        side=decision.side,
                        quantity=decision.quantity,
                        reason=decision.reason,
                        visible_sequences=tuple(bar.sequence for bar in visible),
                        reference_price=None,
                    )
                )
                continue

            # Fill at the close of the last bar that was knowable at this instant. Using the
            # last *visible* bar rather than the current event's bar is the whole point: a
            # strategy that could see the current bar before it published would be trading on
            # information it did not have.
            if not visible:
                records.append(
                    DecisionRecord(
                        as_of=as_of,
                        side="hold",
                        quantity="0",
                        reason="no visible bar to price against",
                        visible_sequences=(),
                        reference_price=None,
                    )
                )
                continue
            price = visible[-1].close_price
            quantity = Decimal(decision.quantity)
            notional = price * quantity
            if decision.side == "buy":
                if notional > cash:
                    records.append(
                        DecisionRecord(
                            as_of=as_of,
                            side="hold",
                            quantity="0",
                            reason="insufficient cash for the requested quantity",
                            visible_sequences=tuple(bar.sequence for bar in visible),
                            reference_price=str(price),
                        )
                    )
                    continue
                cash -= notional
            else:
                cash += notional
            trades += 1
            records.append(
                DecisionRecord(
                    as_of=as_of,
                    side=decision.side,
                    quantity=decision.quantity,
                    reason=decision.reason,
                    visible_sequences=tuple(bar.sequence for bar in visible),
                    reference_price=str(price),
                )
            )

    return BacktestResult(
        dataset_fingerprint=dataset.fingerprint,
        strategy_name=strategy_name,
        params=params,
        decisions=tuple(records),
        final_cash=format(cash, "f"),
        trades=trades,
    )


def _validate_decision(decision: Decision, as_of: datetime) -> None:
    """Reject a decision that is malformed, or that claims a different instant."""
    if not isinstance(decision, Decision):
        msg = f"a strategy must return a Decision, got {type(decision).__name__}"
        raise BacktestError(msg)
    if decision.side not in _SIDES:
        msg = f"unknown side {decision.side!r}; expected one of {sorted(_SIDES)}"
        raise BacktestError(msg)
    if decision.as_of != as_of:
        msg = (
            f"decision claims as_of {decision.as_of.isoformat()} but was taken at "
            f"{as_of.isoformat()}; a decision may not be stamped with another instant"
        )
        raise LookaheadError(msg)
    if decision.quantity == "0" and decision.side != "hold":
        msg = "a non-hold decision must carry a non-zero quantity"
        raise BacktestError(msg)
    if decision.side == "hold":
        return
    from webtrade_research.canonical import validate_decimal_string

    validate_decimal_string(decision.quantity)
    if Decimal(decision.quantity) <= 0:
        msg = f"quantity must be positive, got {decision.quantity!r}"
        raise BacktestError(msg)


def assert_no_lookahead(result: BacktestResult, dataset: Dataset) -> None:
    """Re-derive the no-lookahead claim from the result and the dataset.

    Written to fail on a *result*, not to be called from inside the engine, so that the
    verification runs through a different code path from the slicing it is checking. A guard
    that shares the implementation it guards proves only that the implementation ran.

    Three properties are checked, in increasing order of how badly a violation would mislead:

    1. every recorded decision's visible set is exactly what ``available_at`` permits at that
       instant — the direct definition of lookahead;
    2. the visible sets are monotone, so a strategy cannot have seen a bar disappear;
    3. each decision's ``as_of`` is one the dataset actually supports, so a fabricated instant
       cannot smuggle in a view.
    """
    if result.dataset_fingerprint != dataset.fingerprint:
        msg = (
            f"result was produced from dataset {result.dataset_fingerprint!r} but was checked "
            f"against {dataset.fingerprint!r}"
        )
        raise DatasetError(msg)

    previous: tuple[int, ...] = ()
    for record in result.decisions:
        expected = tuple(bar.sequence for bar in dataset.visible_at(record.as_of))
        if record.visible_sequences != expected:
            missing = sorted(set(expected) - set(record.visible_sequences))
            extra = sorted(set(record.visible_sequences) - set(expected))
            msg = (
                f"decision at {record.as_of.isoformat()} saw {record.visible_sequences} but "
                f"only {expected} was available then"
                + (f"; missing {missing}" if missing else "")
                + (f"; lookahead on {extra}" if extra else "")
            )
            raise LookaheadError(msg)
        if len(record.visible_sequences) < len(previous):
            msg = (
                f"decision at {record.as_of.isoformat()} saw fewer bars "
                f"({len(record.visible_sequences)}) than the previous decision "
                f"({len(previous)}); visibility must be monotone in time"
            )
            raise LookaheadError(msg)
        previous = record.visible_sequences

    available = {bar.available_at for bar in dataset.bars}
    for record in result.decisions:
        if record.as_of not in available:
            msg = (
                f"decision at {record.as_of.isoformat()} is at an instant no bar was published; "
                f"a fabricated decision time can carry a fabricated view"
            )
            raise LookaheadError(msg)
