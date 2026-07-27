from collections.abc import Sequence
from decimal import Decimal

import structlog

logger = structlog.get_logger(__name__)


def sma(prices: Sequence[float | Decimal], period: int) -> float | None:
    if len(prices) < period:
        return None
    window = [float(p) for p in prices[-period:]]
    return sum(window) / len(window)


def ema(prices: Sequence[float | Decimal], period: int) -> float | None:
    if len(prices) < period:
        return None
    values = [float(p) for p in prices]
    multiplier = 2 / (period + 1)
    # Start with SMA for the first EMA value
    prev = sum(values[:period]) / period
    for price in values[period:]:
        prev = (price - prev) * multiplier + prev
    return prev


def rsi(prices: Sequence[float | Decimal], period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    values = [float(p) for p in prices]
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(0, c) for c in changes]
    losses = [max(0, -c) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        gain = gains[i]
        loss = losses[i]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class AnalysisService:
    def calculate_indicators(self, prices: Sequence[float | Decimal]) -> dict[str, float | None]:
        return {
            "sma_20": sma(prices, 20),
            "ema_20": ema(prices, 20),
            "rsi_14": rsi(prices, 14),
        }

    def get_signal(self, indicators: dict[str, float | None]) -> str:
        rsi = indicators.get("rsi_14")
        sma = indicators.get("sma_20")
        ema = indicators.get("ema_20")

        if rsi is None or sma is None or ema is None:
            return "hold"

        if rsi < 30 and sma > ema:
            return "buy"
        if rsi > 70 and sma < ema:
            return "sell"
        return "hold"


analysis_service = AnalysisService()
