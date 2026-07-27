import asyncio
import contextlib
from collections import deque
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.order import OrderType
from app.models.strategy import Strategy, StrategyStatus
from app.models.trading_account import TradingAccount
from app.services.market_service import market_manager

logger = structlog.get_logger(__name__)


class StrategyEngine:
    def __init__(self) -> None:
        self._running_strategies: dict[int, asyncio.Task] = {}
        self._price_history: dict[str, deque] = {}
        self._lock = asyncio.Lock()

    async def start_strategy(self, db: AsyncSession, strategy_id: int) -> Strategy:
        strategy = await db.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"Strategy {strategy_id} not found")

        if strategy.is_running:
            return strategy

        strategy.status = StrategyStatus.ACTIVE
        strategy.is_running = True
        await db.commit()
        await db.refresh(strategy)

        # Start background task for this strategy
        task = asyncio.create_task(self._run_strategy(db, strategy))
        self._running_strategies[strategy_id] = task

        logger.bind(strategy_id=strategy_id).info("strategy_started")
        return strategy

    async def pause_strategy(self, db: AsyncSession, strategy_id: int) -> Strategy:
        strategy = await db.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"Strategy {strategy_id} not found")

        strategy.status = StrategyStatus.PAUSED
        strategy.is_running = False
        await db.commit()
        await db.refresh(strategy)

        # Cancel background task if exists
        task = self._running_strategies.pop(strategy_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.bind(strategy_id=strategy_id).info("strategy_paused")
        return strategy

    async def stop_strategy(self, db: AsyncSession, strategy_id: int) -> Strategy:
        strategy = await db.get(Strategy, strategy_id)
        if strategy is None:
            raise ValueError(f"Strategy {strategy_id} not found")

        strategy.status = StrategyStatus.STOPPED
        strategy.is_running = False
        await db.commit()
        await db.refresh(strategy)

        task = self._running_strategies.pop(strategy_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        logger.bind(strategy_id=strategy_id).info("strategy_stopped")
        return strategy

    async def _run_strategy(self, db: AsyncSession, strategy: Strategy) -> None:
        symbol = await self._get_symbol(db, strategy.asset_id)
        if symbol is None:
            logger.bind(strategy_id=strategy.id).error("strategy_asset_not_found")
            return

        price_key = symbol.lower()
        if price_key not in self._price_history:
            self._price_history[price_key] = deque(maxlen=max(strategy.long_window + 10, 50))

        def on_price(payload: dict) -> None:
            asyncio.create_task(self._on_price(db, strategy, payload))

        market_manager.subscribe(price_key, on_price)

        try:
            while strategy.is_running:
                await asyncio.sleep(1)
                # Refresh strategy state from DB
                await db.refresh(strategy)
                if not strategy.is_running:
                    break
        finally:
            market_manager.unsubscribe(price_key, on_price)

    async def _on_price(self, db: AsyncSession, strategy: Strategy, payload: dict) -> None:
        if not strategy.is_running:
            return

        symbol = await self._get_symbol(db, strategy.asset_id)
        if symbol is None:
            return

        price_key = symbol.lower()
        price = float(payload.get("price", 0))
        if price <= 0:
            return

        history = self._price_history.get(price_key)
        if history is None:
            return

        history.append(price)

        if len(history) < strategy.long_window:
            return

        short_ma = sum(list(history)[-strategy.short_window :]) / strategy.short_window
        long_ma = sum(list(history)[-strategy.long_window :]) / strategy.long_window

        # Simple crossover logic
        if short_ma > long_ma:
            await self._generate_signal(db, strategy, "buy", price)
        elif short_ma < long_ma:
            await self._generate_signal(db, strategy, "sell", price)

    async def _generate_signal(
        self, db: AsyncSession, strategy: Strategy, side: str, price: float
    ) -> None:
        # Get active paper account
        account = await self._get_paper_account(db, strategy.user_id)
        if account is None:
            return

        # Check risk limits before placing order
        from app.services.order_service import order_service
        from app.services.risk_service import risk_service

        # Check if risk allows this trade
        risk_ok, reason = await risk_service.validate_trade(db, strategy.user_id, account.id, price)
        if not risk_ok:
            logger.bind(strategy_id=strategy.id, reason=reason).warning(
                "strategy_signal_blocked_by_risk"
            )
            return

        # Create order with idempotency key
        idempotency_key = f"strategy_{strategy.id}_{side}_{int(price * 100) % 100000}"
        try:
            order = await order_service.create_order(
                db=db,
                user_id=strategy.user_id,
                account_id=account.id,
                asset_id=strategy.asset_id,
                side=side,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.01"),
                price=None,
                idempotency_key=idempotency_key,
                strategy_id=strategy.id,
            )
            # Immediately fill the order for paper trading
            await order_service.fill_order(db, order, price)
        except ValueError as err:
            logger.bind(strategy_id=strategy.id, error=str(err)).info("order_skipped")

    async def _get_symbol(self, db: AsyncSession, asset_id: int) -> str | None:
        asset = await db.get(Asset, asset_id)
        return asset.symbol if asset else None

    async def _get_paper_account(self, db: AsyncSession, user_id: int) -> TradingAccount | None:
        result = await db.execute(
            select(TradingAccount).where(
                TradingAccount.user_id == user_id,
                TradingAccount.account_type == "paper",
                TradingAccount.status == "active",
            )
        )
        return result.scalar_one_or_none()


strategy_engine = StrategyEngine()
