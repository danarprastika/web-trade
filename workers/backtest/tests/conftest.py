"""Shared fixtures: a dataset that can detect lookahead bias.

The central fixture is deliberately adversarial. It contains a bar whose ``event_time`` has
passed but whose ``available_at`` has not, which is what a revised, late-delivered, or
back-filled record looks like. A harness that slices on ``event_time`` will show that bar to a
decision that could not have seen it, and the resulting equity curve will look better than the
strategy deserves.

Every test in this suite that claims the harness is point-in-time rests on this fixture being
able to distinguish the two slicing rules. If it could not, the tests would pass against a
harness with no protection at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from webtrade_research.dataset import Bar, Dataset

BASE = datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return BASE + timedelta(minutes=minutes)


def bar(
    sequence: int,
    event_minute: int,
    available_minute: int,
    close: str,
    instrument: str = "BTC-USD",
) -> Bar:
    """Build a bar. The two minute arguments are separate on purpose."""
    return Bar(
        instrument=instrument,
        event_time=at(event_minute),
        available_at=at(available_minute),
        open=close,
        high=close,
        low=close,
        close=close,
        volume="1",
        sequence=sequence,
    )


@pytest.fixture
def simple_dataset() -> Dataset:
    """Five bars, each available at the instant its period ended.

    No lateness, so a correct harness and a lookahead harness agree here. A test that only used
    this fixture could not tell the two apart.
    """
    return Dataset.create(
        name="simple",
        schema_version="bars/1",
        bars=[
            bar(0, 0, 0, "100"),
            bar(1, 1, 1, "101"),
            bar(2, 2, 2, "102"),
            bar(3, 3, 3, "103"),
            bar(4, 4, 4, "104"),
        ],
    )


@pytest.fixture
def late_publication_dataset() -> Dataset:
    """A dataset whose ``event_time`` and ``available_at`` disagree at a decision instant.

    Sequence 2 describes the *same* period as sequence 1 — both close at minute 1 — but it was
    revised and not published until minute 30. At the decision instant minute 1:

    * ``available_at <= 1`` yields ``[0, 1]`` — two bars, the correct answer;
    * ``event_time <= 1`` yields ``[0, 1, 2]`` — three bars, one of them a value that did not
      exist yet in the world.

    That second view is the lookahead, and it is what a harness slicing on the wrong timestamp
    would hand a strategy. The fixture has to place the two answers at a disagreement, not
    merely at a gap: if no decision instant separates them, an ``event_time``-based harness
    produces the same result as a correct one and the test cannot tell them apart.
    """
    return Dataset.create(
        name="late-publication",
        schema_version="bars/1",
        bars=[
            bar(0, 0, 0, "100"),
            bar(1, 1, 1, "101"),
            bar(2, 1, 30, "999"),
            bar(3, 2, 2, "102"),
            bar(4, 3, 3, "103"),
        ],
    )


@pytest.fixture
def window() -> tuple[datetime, datetime]:
    """A decision window covering every bar in both fixtures."""
    return at(0), at(60)
