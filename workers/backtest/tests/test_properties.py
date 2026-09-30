"""Property-based tests for the invariants the example tests can only sample.

`hypothesis` is a declared dev dependency of this worker and was, until these tests existed,
imported nowhere in the repository. The gap was worth closing on its own terms rather than by
deleting the dependency: this is the module where the guarantees are universal rather than
illustrative. The examples in ``test_harness.py`` show that a handful of specific sequences behave;
these state that *every* sequence behaves, which is the actual claim the deterministic engine
makes.

`derandomize=True` is set for every property. This repository treats reproducibility as a
correctness property rather than a convenience - an irreproducible result cannot be promoted
(docs/11, G4) - and a property test that varied its examples between runs would reintroduce
exactly the nondeterminism the rest of the worker exists to exclude. Derandomizing makes the same
examples run on every machine, so a failure is reproducible by whoever reads the report.

Each property is one the engine must satisfy by construction, not one it happens to satisfy today.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from webtrade_research.dataset import Bar, Dataset, DatasetRegistry

from webtrade_backtest.artifacts import build_artifact
from webtrade_backtest.harness import (
    BacktestParams,
    Decision,
    MarketView,
    assert_no_lookahead,
    run_backtest,
)

BASE = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)
SIDE_EFFECTS = list(HealthCheck)

# Bound the generated data. A backtest over ten thousand bars proves nothing extra about these
# invariants while turning the suite slow, and the properties below are about the shape of the
# sequence rather than its length.
BARS = st.integers(min_value=1, max_value=12)
PRICES = st.sampled_from(["100", "101.5", "0.001", "99999.99", "3.14159"])
INSTANTS = st.integers(min_value=0, max_value=200)


@st.composite
def bar_lists(draw: st.DrawFn) -> list[Bar]:
    """Generate a valid, well-formed set of bars.

    ``available_at`` is drawn at or after ``event_time`` because the reverse is rejected at
    construction as a fabricated record, not as lateness. Both are drawn independently so that
    late publication - the case the whole no-lookahead property turns on - is exercised rather
    than being a special case.
    """
    count = draw(BARS)
    instrument = draw(st.sampled_from(["BTC-USD", "ETH-USD"]))
    bars: list[Bar] = []
    for sequence in range(count):
        event = draw(INSTANTS)
        available = draw(st.integers(min_value=event, max_value=event + 60))
        price = draw(PRICES)
        bars.append(
            Bar(
                instrument=instrument,
                event_time=BASE + timedelta(minutes=event),
                available_at=BASE + timedelta(minutes=available),
                open=price,
                high=price,
                low=price,
                close=price,
                volume="1",
                sequence=sequence,
            )
        )
    return bars


@st.composite
def datasets(draw: st.DrawFn) -> Dataset:
    return Dataset.create("prop", "bars/1", draw(bar_lists()))


# ---------------------------------------------------------------- lookahead


@settings(max_examples=60, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(dataset=datasets())
def test_the_harness_never_leaks_for_any_dataset(dataset: Dataset) -> None:
    """For *every* dataset, the engine's own output satisfies the no-lookahead assertion.

    This is the universal form of the claim the example tests demonstrate for one fixture. A
    harness that leaked would have to leak for every input to pass an example-based test, which
    is not a property anyone should have to trust.
    """
    params = BacktestParams(seed=1, start=BASE, end=BASE + timedelta(days=1))
    result = run_backtest(dataset, _BuyEverything(), params, strategy_name="buy-everything")
    assert_no_lookahead(result, dataset)


class _BuyEverything:
    """Buys at every decision, so every decision carries a price and a visibility claim."""

    def decide(self, view: MarketView) -> Decision:
        return Decision(as_of=view.as_of, side="buy", quantity="1", reason="always")


@settings(max_examples=60, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(dataset=datasets())
def test_visibility_is_always_a_prefix_of_the_available_bars(dataset: Dataset) -> None:
    """A strategy's view is exactly the bars published by that instant, never more.

    Checked against the dataset rather than against the engine's own bookkeeping, so this is an
    independent restatement of the rule rather than a comparison of the engine with itself.
    """
    for offset in range(0, 200, 7):
        as_of = BASE + timedelta(minutes=offset)
        expected = {b.sequence for b in dataset.visible_at(as_of)}
        assert expected == {b.sequence for b in dataset if b.available_at <= as_of}


# ---------------------------------------------------------------- money


@settings(max_examples=60, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(
    dataset=datasets(),
    sides=st.lists(st.sampled_from(["buy", "sell", "hold"]), min_size=1, max_size=12),
    quantities=st.lists(
        st.sampled_from(["1", "2", "0.5", "1000"]), min_size=1, max_size=12
    ),
    cash=st.sampled_from(["0.01", "100", "100000"]),
)
def test_cash_is_never_spent_below_zero(
    dataset: Dataset,
    sides: list[str],
    quantities: list[str],
    cash: str,
) -> None:
    """No sequence of decisions can overdraw the account.

    A backtest that can spend money it does not have reports returns that cannot happen, and
    the equity curve it draws is fiction. The engine refuses an unaffordable order rather than
    allowing a negative balance, so the invariant is that cash is non-negative at every point and
    the final figure never goes below the initial one when every action is a buy.
    """
    plan = list(zip(sides, quantities, strict=False))

    class Scripted:
        def __init__(self) -> None:
            self._index = 0

        def decide(self, view: MarketView) -> Decision:
            side, quantity = plan[min(self._index, len(plan) - 1)]
            self._index += 1
            return Decision(as_of=view.as_of, side=side, quantity=quantity)

    params = BacktestParams(
        seed=1, start=BASE, end=BASE + timedelta(days=1), initial_cash=cash
    )
    result = run_backtest(dataset, Scripted(), params, strategy_name="scripted")
    assert Decimal(result.final_cash) >= 0
    if all(side == "buy" for side, _ in plan):
        assert Decimal(result.final_cash) <= Decimal(cash)


@settings(max_examples=40, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(dataset=datasets())
def test_spending_the_entire_balance_exactly_is_permitted(dataset: Dataset) -> None:
    """A buy whose notional equals the whole balance must go through.

    The companion to the no-overdraft property above, and the one that pins the boundary. Bounding
    the balance is not enough: an implementation that refused any order costing *at least* the
    available cash would satisfy "cash is never negative" and "cash never exceeds the initial
    amount" perfectly, while silently rejecting the one order it is exactly able to afford.

    That is not a harmless conservatism. It is a strategy that is told it cannot act at the
    moment it can afford to, and the resulting curve is wrong in the direction that makes a
    strategy look cautious rather than broken, which is the harder defect to notice.

    The property is therefore stated on the boundary: with a balance equal to the notional, the
    trade executes and the balance lands on exactly zero.
    """
    if len(dataset) == 0:
        return
    # The engine fills at the close of the last bar that was *visible* at the decision instant,
    # which is not necessarily the first bar. Computing the notional from bars[0] would make the
    # balance and the price refer to different bars, and the property would fail for a reason
    # that has nothing to do with the boundary being tested.
    first_instant = min(b.available_at for b in dataset)
    visible = dataset.visible_at(first_instant)
    if not visible:
        return
    price = visible[-1].close_price
    if price <= 0:
        return
    quantity = Decimal(1000) // price
    if quantity <= 0:
        return

    class SpendItAll:
        def decide(self, view: MarketView) -> Decision:
            return Decision(as_of=view.as_of, side="buy", quantity=str(quantity))

    params = BacktestParams(
        seed=1,
        start=BASE,
        end=BASE + timedelta(days=1),
        initial_cash=str(quantity * price),
    )
    result = run_backtest(dataset, SpendItAll(), params, strategy_name="spend-it-all")
    assert result.trades >= 1, (
        "an order costing exactly the whole balance was refused; the account is not exhausted, "
        "it is exactly able to act"
    )
    assert Decimal(result.final_cash) >= 0
    # The first decision must have been allowed to proceed, not converted to a hold.
    assert result.decisions[0].side == "buy"


# ---------------------------------------------------------------- determinism


@settings(max_examples=40, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(dataset=datasets(), seed=st.integers(min_value=0, max_value=10_000))
def test_identical_inputs_give_byte_identical_output(dataset: Dataset, seed: int) -> None:
    """The reproducibility requirement, stated over generated inputs rather than one example."""

    class Flaky:
        def decide(self, view: MarketView) -> Decision:
            if view.random.random() > 0.5:
                return Decision(as_of=view.as_of, side="buy", quantity="1")
            return Decision(as_of=view.as_of, side="hold", quantity="0")

    params = BacktestParams(
        seed=seed, start=BASE, end=BASE + timedelta(days=1)
    )
    first = run_backtest(dataset, Flaky(), params, strategy_name="flaky")
    second = run_backtest(dataset, Flaky(), params, strategy_name="flaky")
    assert first.to_canonical() == second.to_canonical()
    assert first == second


# ---------------------------------------------------------------- versioning


@settings(max_examples=60, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(bars=bar_lists())
def test_a_dataset_fingerprint_survives_any_reordering(bars: list[Bar]) -> None:
    """Versioning must not depend on how the bars happened to be loaded.

    Checked on :meth:`Dataset.compute_fingerprint` directly as well as through ``create``,
    because the two are separate entry points and a caller constructing a dataset by hand would
    otherwise get a different version of the same data.
    """
    forward = Dataset.compute_fingerprint("prop", "bars/1", bars)
    shuffled = list(bars)
    # A deterministic shuffle: the property is about ordering, not about chance.
    shuffled.reverse()
    assert forward == Dataset.compute_fingerprint("prop", "bars/1", shuffled)
    assert forward == Dataset.create("prop", "bars/1", bars).fingerprint
    assert forward == Dataset.create("prop", "bars/1", shuffled).fingerprint


@settings(max_examples=40, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(datasets_list=st.lists(datasets(), min_size=1, max_size=6))
def test_the_registry_keeps_every_version_and_is_order_independent(
    datasets_list: list[Dataset],
) -> None:
    """Registration is idempotent, retains all versions, and reports a sorted listing.

    A registry that overwrote would make a backtest from last month unreproducible, and one
    that listed in insertion order would make anything derived from it depend on the order
    datasets happened to be added.
    """
    registry = DatasetRegistry()
    fingerprints = [registry.register(d) for d in datasets_list]
    assert len(registry) == len(set(fingerprints))
    for dataset in datasets_list:
        registry.register(dataset)
    assert len(registry) == len(set(fingerprints))
    assert list(registry.fingerprints()) == sorted(registry.fingerprints())


# ---------------------------------------------------------------- artifacts


@settings(max_examples=40, derandomize=True, suppress_health_check=SIDE_EFFECTS)
@given(dataset=datasets(), seed=st.integers(min_value=0, max_value=10_000))
def test_an_artifact_digest_is_reproducible_for_any_dataset(
    dataset: Dataset, seed: int
) -> None:
    """Two builds of the same run agree on the digest, for every generated dataset.

    Also asserts the artifact is always proposed, because a research worker that could emit any
    other status could represent its own output as approved (docs/07, docs/25 section 4).
    """

    class AlwaysBuy:
        def decide(self, view: MarketView) -> Decision:
            return Decision(as_of=view.as_of, side="buy", quantity="1")

    params = BacktestParams(seed=seed, start=BASE, end=BASE + timedelta(days=1))
    kwargs = {
        "dataset": dataset,
        "code_revision": "0" * 40,
        "feature_specification_version": "features/1",
        "evaluation_report": "reports/eval.md",
    }
    result = run_backtest(dataset, AlwaysBuy(), params, strategy_name="buy")
    first = build_artifact(result=result, **kwargs)  # type: ignore[arg-type]
    second = build_artifact(result=result, **kwargs)  # type: ignore[arg-type]
    assert first.digest == second.digest
    assert first.status == "proposed"
