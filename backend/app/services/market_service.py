import asyncio
import contextlib
import json
import logging
from asyncio import Lock
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

import websockets
from websockets.client import WebSocketClientProtocol

from app.config import settings

logger = logging.getLogger(__name__)


class MarketConnectionManager:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[Callable[[dict], None]]] = {}
        self._connection: WebSocketClientProtocol | None = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._lock = Lock()
        self._reconnect_delay = settings.market_reconnect_delay
        self._task: asyncio.Task | None = None
        self._price_history: dict[str, deque[float]] = {}
        self._max_history: int = 200

    def subscribe(self, symbol: str, callback: Callable[[dict], None]) -> None:
        self._subscribers.setdefault(symbol.lower(), set()).add(callback)

    def unsubscribe(self, symbol: str, callback: Callable[[dict], None]) -> None:
        callbacks = self._subscribers.get(symbol.lower())
        if callbacks:
            callbacks.discard(callback)
            if not callbacks:
                del self._subscribers[symbol.lower()]

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        async with self._lock:
            if self._connection and not self._connection.closed:
                await self._connection.close()
            self._connection = None
            self._connected = False

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Market connection error", exc_info=exc)
            if self._stop_event.is_set():
                break
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(
                self._reconnect_delay * 2, settings.market_reconnect_max_delay
            )

    async def _connect_and_listen(self) -> None:
        streams = [f"{sym}@miniTicker" for sym in settings.market_subscribed_symbols]
        url = f"{settings.binance_ws_base}/stream?streams={'/'.join(streams)}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            async with self._lock:
                self._connection = ws
                self._connected = True
                self._reconnect_delay = settings.market_reconnect_delay
            logger.info("Market websocket connected", url=url)
            async for raw in ws:
                if self._stop_event.is_set():
                    break
                try:
                    message = json.loads(raw)
                    if "data" in message and "s" in message.get("data", {}):
                        self._broadcast(message["data"])
                except json.JSONDecodeError:
                    continue
        async with self._lock:
            self._connected = False
            self._connection = None

    def _broadcast(self, ticker: dict) -> None:
        symbol = ticker.get("s", "").lower()
        callbacks = self._subscribers.get(symbol, set())
        if not callbacks:
            return
        price = float(ticker.get("c", 0))
        payload = {
            "symbol": symbol,
            "price": price,
            "open": float(ticker.get("o", 0)),
            "high": float(ticker.get("h", 0)),
            "low": float(ticker.get("l", 0)),
            "volume": float(ticker.get("v", 0)),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # Store price history for analysis endpoints
        history = self._price_history.setdefault(symbol, deque(maxlen=self._max_history))
        if price > 0:
            history.append(price)
        for callback in list(callbacks):
            try:
                callback(payload)
            except Exception as exc:
                logger.error("Market callback error", exc_info=exc)

    def get_recent_prices(self, symbol: str, limit: int = 50) -> list[float]:
        history = self._price_history.get(symbol.lower())
        if not history:
            return []
        return list(history)[-limit:]


market_manager = MarketConnectionManager()
