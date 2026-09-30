"""Determinism and no-lookahead tests for the backtest harness.

Two properties are tested here, and they are tested against the adversarial fixture rather than
the convenient one, because the convenient fixture cannot distinguish a harness with the
protection from one without it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pytest
from conftest import at
from webtrade_research.dataset import Bar, Dataset

from webtrade_backtest.harness import (
    BacktestError,
    BacktestParams,
    BacktestResult,
    Decision,
    DecisionRecord,
    LookaheadError,
    MarketView,
    assert_no_lookahead,
    run_backtest,
)


@dataclass
class BuyOnFirstBarThenHold:
    """Buys once, then holds. Simple enough that any difference is the harness's."""

    def decide(self, view: MarketView) -> Decision:
        if view.as_of == at(0):
            return Decision(as_of=view.as_of, side="buy", quantity="1", reason="first bar")
        return Decision(as_of=view.as_of, side="hold", quantity="0")


@dataclass
class AlwaysBuy:
    """Buys at every decision. Exercises repeated fills and cash accounting."""

    def decide(self, view: MarketView) -> Decision:
        return Decision(as_of=view.as_of, side="buy", quantity="1", reason="always")


class EventTimeLeaker:
    """A harness that slices visibility on ``event_time`` instead of ``available_at``.

    Stands in for the bug the whole design exists to prevent, and is used only to prove the
    fixture can tell a leaking harness from a correct one. It reports what an ``event_time``
    view would have contained, so the comparison against the correct view is explicit rather
    than implied.
    """

    def __init__(self, dataset: Dataset) -> None:
        self._bars = dataset.bars

    def visible_at(self, as_of: datetime) -> tuple[Bar, ...]:
        return tuple(b for b in self._bars if b.event_time <= as_of)


def event_time_sliced_result(
    dataset: Dataset, params: BacktestParams
) -> BacktestResult:
    """A result built the way a leaking harness would have built it.

    Each decision claims the visibility ``event_time`` permits. This is not a hypothetical
    construction: it is precisely the record a harness with the wrong slice would emit, which
    is why it can be fed to the assertion and must be rejected.
    """
    leaker = EventTimeLeaker(dataset)
    records = [
        DecisionRecord(
            as_of=as_of,
            side="hold",
            quantity="0",
            reason="",
            visible_sequences=tuple(b.sequence for b in leaker.visible_at(as_of)),
            reference_price=None,
        )
        for as_of in sorted({b.available_at for b in dataset.bars})
    ]
    return BacktestResult(
        dataset_fingerprint=dataset.fingerprint,
        strategy_name="event-time-leaker",
        params=params,
        decisions=tuple(records),
        final_cash="100000",
        trades=0,
    )


# ---------------------------------------------------------------- determinism


def test_identical_inputs_produce_an_identical_result(simple_dataset: Dataset) -> None:
    """The reproducibility requirement, stated as the simplest possible equality."""
    params = BacktestParams(seed=7, start=at(0), end=at(60))
    first = run_backtest(simple_dataset, AlwaysBuy(), params, strategy_name="always-buy")
    second = run_backtest(simple_dataset, AlwaysBuy(), params, strategy_name="always-buy")
    assert first == second
    assert first.to_canonical() == second.to_canonical()


def test_the_seed_changes_the_result_so_it_is_load_bearing(
    simple_dataset: Dataset,
) -> None:
    """A seed parameter that changes nothing is worse than no seed parameter.

    A strategy that draws from ``view.random`` must produce a different result under a
    different seed, otherwise the seed is decoration and a result is quietly irreproducible in
    the way that matters.
    """

    @dataclass
    class RandomisedBuy:
        def decide(self, view: MarketView) -> Decision:
            roll = view.random.random()
            if roll > 0.5:
                return Decision(as_of=view.as_of, side="buy", quantity="1", reason="roll up")
            return Decision(as_of=view.as_of, side="hold", quantity="0", reason="roll down")

    results = {
        seed: run_backtest(
            simple_dataset,
            RandomisedBuy(),
            BacktestParams(seed=seed, start=at(0), end=at(60)),
            strategy_name="randomised",
        )
        for seed in (1, 2, 3, 4, 5, 6, 7, 8)
    }
    # json rather than a set: the decision list is nested and unhashable, and frozenset of
    # repr would have compared a different thing from what is being asserted.
    distinct = {
        json.dumps(r.to_canonical()["decisions"], sort_keys=True)
        for r in results.values()
    }
    assert len(distinct) > 1, (
        "every seed produced an identical decision sequence; the seed is not reaching the "
        "strategy"
    )


def test_the_seed_is_stable_for_a_given_run(simple_dataset: Dataset) -> None:
    """A randomised strategy must still be reproducible under a fixed seed."""

    @dataclass
    class RandomisedBuy:
        def decide(self, view: MarketView) -> Decision:
            if view.random.random() > 0.5:
                return Decision(as_of=view.as_of, side="buy", quantity="1")
            return Decision(as_of=view.as_of, side="hold", quantity="0")

    params = BacktestParams(seed=42, start=at(0), end=at(60))
    a = run_backtest(simple_dataset, RandomisedBuy(), params, strategy_name="r")
    b = run_backtest(simple_dataset, RandomisedBuy(), params, strategy_name="r")
    assert a.to_canonical() == b.to_canonical()


def test_one_decision_s_random_draws_do_not_shift_the_next(
    late_publication_dataset: Dataset,
) -> None:
    """Each decision draws from its own stream, so runs stay comparable.

    Seeding one shared generator would make a decision's draw depend on how many draws the
    decisions before it happened to make, so changing what decision 0 does would silently
    change every later result — reproducible, but no longer comparable to the run it replaced.
    Per-index seeding makes each decision's randomness a function of its position alone.

    Within a single decision, extra draws still advance that decision's own stream, which is
    correct: a strategy's draws are its own business.
    """

    class VariableDraws:
        """Draws a variable number of times at the first decision, then records a probe."""

        def __init__(self, extra_draws: int) -> None:
            self._extra = extra_draws

        def decide(self, view: MarketView) -> Decision:
            is_first = view.as_of == at(0)
            for _ in range(self._extra if is_first else 0):
                view.random.random()
            return Decision(
                as_of=view.as_of,
                side="hold",
                quantity="0",
                reason=f"{view.random.random():.6f}",
            )

    params = BacktestParams(seed=99, start=at(0), end=at(60))
    greedy = run_backtest(late_publication_dataset, VariableDraws(50), params, strategy_name="v")
    frugal = run_backtest(late_publication_dataset, VariableDraws(0), params, strategy_name="v")

    # Decision 0 differs, because the first decision's own stream was advanced.
    assert greedy.decisions[0].reason != frugal.decisions[0].reason
    # Decisions 1 onward must be identical, because each has its own stream.
    assert [d.reason for d in greedy.decisions[1:]] == [
        d.reason for d in frugal.decisions[1:]
    ]


def test_the_result_carries_no_ambient_state(simple_dataset: Dataset) -> None:
    """A result must not encode when or where it was produced.

    A run timestamp, host, or counter would make two identical runs differ, which is the exact
    failure the reproducibility requirement exists to prevent.
    """
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    result = run_backtest(simple_dataset, AlwaysBuy(), params, strategy_name="always-buy")
    canonical = result.to_canonical()
    assert set(canonical) == {
        "dataset_fingerprint",
        "strategy_name",
        "params",
        "decisions",
        "final_cash",
        "trades",
    }
    serialised = repr(canonical)
    for forbidden in ("hostname", "127.0.0.1", "C:\\\\", "pid", "run_id"):
        assert forbidden not in serialised


# ---------------------------------------------------------------- no lookahead


def test_a_late_published_bar_is_invisible_before_it_is_published(
    late_publication_dataset: Dataset,
) -> None:
    """The core no-lookahead assertion, on the fixture where the two rules disagree.

    Sequence 2 closes at minute 1 alongside sequence 1 but publishes at minute 30. At minute 1
    it is not in the world yet, and ``event_time`` says otherwise, which is the trap.
    """
    assert [b.sequence for b in late_publication_dataset.visible_at(at(1))] == [0, 1]
    assert [b.sequence for b in late_publication_dataset.visible_at(at(2))] == [0, 1, 3]
    assert [b.sequence for b in late_publication_dataset.visible_at(at(30))] == [0, 1, 2, 3, 4]


def test_the_two_timestamps_disagree_at_a_decision_instant(
    late_publication_dataset: Dataset,
) -> None:
    """The fixture can tell a correct harness from a leaking one.

    Without this, every lookahead test in this file could pass against a harness that slices
    on the wrong timestamp, because a fixture whose two rules agree everywhere would produce
    identical results either way.
    """
    leaker = EventTimeLeaker(late_publication_dataset)
    for as_of in (at(0), at(1), at(2), at(3), at(30)):
        correct = [b.sequence for b in late_publication_dataset.visible_at(as_of)]
        leaked = [b.sequence for b in leaker.visible_at(as_of)]
        if correct != leaked:
            return  # the discriminating instant exists
    pytest.fail(
        "the fixture never distinguishes the two slicing rules; the lookahead tests are vacuous"
    )


def test_the_harness_decides_at_publication_time_not_period_end(
    late_publication_dataset: Dataset,
) -> None:
    """There is no decision between a period ending and its bar being published.

    Deciding at ``event_time`` would mean acting on a bar the market had not yet reported.
    """
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    result = run_backtest(
        late_publication_dataset, AlwaysBuy(), params, strategy_name="always-buy"
    )
    decision_times = [d.as_of for d in result.decisions]
    assert decision_times == [at(0), at(1), at(2), at(3), at(30)]
    assert at(15) not in decision_times


def test_a_result_built_by_slicing_on_event_time_is_rejected(
    late_publication_dataset: Dataset,
) -> None:
    """The assertion catches a leaking harness, by name.

    This is the claim the whole module rests on, so it is stated directly: a result whose
    recorded visibility matches ``event_time`` rather than ``available_at`` is rejected, and
    the error says lookahead rather than something incidental. An assertion that merely
    returned false would leave a reader unable to tell which control fired.
    """
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    leaked = event_time_sliced_result(late_publication_dataset, params)
    with pytest.raises(LookaheadError, match="lookahead"):
        assert_no_lookahead(leaked, late_publication_dataset)


def test_the_view_exposes_no_path_to_the_dataset(
    late_publication_dataset: Dataset,
) -> None:
    """The view is the only channel a strategy has, and it is a dead end.

    The harness cannot police a strategy that closes over the dataset itself, so the control
    is structural: the object handed to ``decide`` holds the visible bars and nothing else
    that could reach the rest. This asserts that structurally rather than trusting it, because
    adding a convenience accessor later would reintroduce the whole problem silently.
    """
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    captured: list[MarketView] = []

    @dataclass
    class Captor:
        def decide(self, view: MarketView) -> Decision:
            captured.append(view)
            return Decision(as_of=view.as_of, side="hold", quantity="0")

    run_backtest(late_publication_dataset, Captor(), params, strategy_name="captor")
    assert captured
    for view in captured:
        # A frozen dataclass with slots: no instance dictionary to stash a dataset in, and
        # no attribute that is not one of the three declared here.
        assert not hasattr(view, "__dict__"), "the view carries an instance dictionary"
        public = {n for n in dir(view) if not n.startswith("_")}
        assert public <= {"as_of", "bars", "random"}, f"unexpected view surface: {public}"
        assert not callable(getattr(view, "get", None))
        assert not callable(getattr(view, "dataset", None))


def test_the_harness_itself_does_not_leak(late_publication_dataset: Dataset) -> None:
    """The engine's own output must satisfy the assertion it ships with."""
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    result = run_backtest(
        late_publication_dataset, AlwaysBuy(), params, strategy_name="always-buy"
    )
    assert_no_lookahead(result, late_publication_dataset)
    # And the same result would be rejected if it had been sliced the other way, which is the
    # only way to know the assertion is discriminating rather than vacuously true.
    with pytest.raises(LookaheadError):
        assert_no_lookahead(
            event_time_sliced_result(late_publication_dataset, params),
            late_publication_dataset,
        )


def test_visibility_is_monotone_across_the_run(late_publication_dataset: Dataset) -> None:
    """A strategy must never see fewer bars than it did at an earlier instant.

    Bars can be revised or withdrawn, so this is a genuine invariant to assert rather than
    assume. It is checked separately because a harness that recomputed visibility incorrectly
    could produce a non-monotone sequence that a per-decision equality check might not catch.
    """
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    result = run_backtest(
        late_publication_dataset, AlwaysBuy(), params, strategy_name="always-buy"
    )
    counts = [len(d.visible_sequences) for d in result.decisions]
    assert counts == sorted(counts), f"visibility shrank during the run: {counts}"


def test_a_decision_stamped_with_another_instant_is_refused(
    simple_dataset: Dataset,
) -> None:
    """A strategy cannot backdate or forward-date its own decision.

    Without this, a strategy could stamp a decision at an instant that reveals more data, and
    the recorded view would be inconsistent with the recorded time.
    """

    @dataclass
    class TimeTraveller:
        def decide(self, view: MarketView) -> Decision:
            return Decision(as_of=at(999), side="buy", quantity="1")

    params = BacktestParams(seed=1, start=at(0), end=at(60))
    with pytest.raises(LookaheadError, match="may not be stamped with another instant"):
        run_backtest(simple_dataset, TimeTraveller(), params, strategy_name="traveller")


def test_a_fabricated_decision_instant_is_rejected(
    simple_dataset: Dataset,
) -> None:
    """A result carrying a decision time the dataset never supported is rejected.

    This closes the obvious bypass of the per-decision visibility check: if the recorded
    ``as_of`` is itself fabricated, the expected visibility computed from it would be empty and
    the strategy would appear to have seen nothing.
    """
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    good = run_backtest(simple_dataset, AlwaysBuy(), params, strategy_name="always-buy")
    fabricated = good.__class__(
        dataset_fingerprint=good.dataset_fingerprint,
        strategy_name=good.strategy_name,
        params=good.params,
        decisions=(
            good.decisions[0].__class__(
                as_of=at(37),
                side="buy",
                quantity="1",
                reason="fabricated",
                visible_sequences=(0, 1, 2, 3, 4),
                reference_price="100",
            ),
        ),
        final_cash=good.final_cash,
        trades=1,
    )
    with pytest.raises(LookaheadError, match="no bar was published"):
        assert_no_lookahead(fabricated, simple_dataset)


# ---------------------------------------------------------------- result shape


def test_cash_accounting_refuses_to_spend_more_than_is_held(
    simple_dataset: Dataset,
) -> None:
    """A backtest that can spend money it does not have reports returns that cannot happen."""

    @dataclass
    class Spender:
        def decide(self, view: MarketView) -> Decision:
            return Decision(as_of=view.as_of, side="buy", quantity="1000")

    params = BacktestParams(seed=1, start=at(0), end=at(60), initial_cash="100")
    result = run_backtest(simple_dataset, Spender(), params, strategy_name="spender")
    assert result.trades == 0
    assert Decimal(result.final_cash) == Decimal("100")
    assert all(d.side == "hold" for d in result.decisions)


def test_an_empty_window_is_refused_rather_than_returning_an_empty_result(
    simple_dataset: Dataset,
) -> None:
    """A zero-decision run is a mistake, not a result.

    Returning an empty success would let a mistyped window be promoted as a backtest that
    simply found no opportunities.
    """
    params = BacktestParams(seed=1, start=at(500), end=at(600))
    with pytest.raises(BacktestError, match="the run would be empty"):
        run_backtest(simple_dataset, AlwaysBuy(), params, strategy_name="always-buy")


def test_an_anonymous_strategy_is_refused(simple_dataset: Dataset) -> None:
    """A result nobody can attribute is not reviewable."""
    params = BacktestParams(seed=1, start=at(0), end=at(60))
    with pytest.raises(BacktestError, match="must name its strategy"):
        run_backtest(simple_dataset, AlwaysBuy(), params, strategy_name="")


def test_a_non_datetime_decision_payload_is_refused(simple_dataset: Dataset) -> None:
    """A strategy must return a Decision, not a dict that happens to have the keys."""

    @dataclass
    class Sloppy:
        def decide(self, view: MarketView) -> dict[str, object]:
            return {"as_of": view.as_of, "side": "buy", "quantity": "1"}

    params = BacktestParams(seed=1, start=at(0), end=at(60))
    with pytest.raises(BacktestError, match="must return a Decision"):
        run_backtest(simple_dataset, Sloppy(), params, strategy_name="sloppy")


def test_bar_cannot_be_available_before_its_period_ends() -> None:
    """The mirror-image error is also a data error.

    A bar available before the period it describes has ended is not lateness, it is a
    fabricated record, and it would invert the meaning of both timestamps.
    """
    with pytest.raises(Exception, match="before its period ends"):
        Bar(
            instrument="BTC-USD",
            event_time=at(10),
            available_at=at(5),
            open="1",
            high="1",
            low="1",
            close="1",
            volume="1",
            sequence=0,
        )


def test_naive_timestamps_are_refused() -> None:
    """A naive datetime is a data error, not a local-time assumption."""
    with pytest.raises(Exception, match="timezone-aware"):
        Bar(
            instrument="BTC-USD",
            event_time=datetime(2026, 1, 5, 9, 0),  # noqa: DTZ001 - deliberately naive
            available_at=datetime(2026, 1, 5, 9, 1),  # noqa: DTZ001 - deliberately naive
            open="1",
            high="1",
            low="1",
            close="1",
            volume="1",
            sequence=0,
        )
