from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.trade import Trade
from app.models.trading_account import TradingAccount

logger = structlog.get_logger(__name__)


class OrderService:
    async def create_order(
        self,
        db: AsyncSession,
        user_id: int,
        account_id: int,
        asset_id: int,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None,
        idempotency_key: str,
        strategy_id: int | None = None,
    ) -> Order:
        # Check idempotency
        existing = await self.get_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            logger.bind(idempotency_key=idempotency_key, order_id=existing.id).info(
                "order_idempotent_hit"
            )
            return existing

        # Validate account exists and is active
        account = await db.get(TradingAccount, account_id)
        if account is None or account.status != "active":
            raise ValueError("Trading account not found or inactive")

        order = Order(
            user_id=user_id,
            account_id=account_id,
            strategy_id=strategy_id,
            asset_id=asset_id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            idempotency_key=idempotency_key,
            status=OrderStatus.PENDING,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        logger.bind(order_id=order.id, idempotency_key=idempotency_key).info("order_created")
        return order

    async def get_by_idempotency_key(self, db: AsyncSession, idempotency_key: str) -> Order | None:
        result = await db.execute(select(Order).where(Order.idempotency_key == idempotency_key))
        return result.scalar_one_or_none()

    async def fill_order(self, db: AsyncSession, order: Order, fill_price: float) -> Order:
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return order

        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(order)

        # Create trade record
        trade = Trade(
            user_id=order.user_id,
            account_id=order.account_id,
            order_id=order.id,
            asset_id=order.asset_id,
            side=order.side,
            quantity=float(order.quantity),
            price=fill_price,
            pnl=0.0,
        )
        db.add(trade)
        await db.commit()

        logger.bind(order_id=order.id, fill_price=fill_price).info("order_filled")
        return order

    async def cancel_order(self, db: AsyncSession, order_id: int, user_id: int) -> Order | None:
        order = await db.get(Order, order_id)
        if order is None or order.user_id != user_id:
            return None
        if order.status != OrderStatus.PENDING:
            return order

        order.status = OrderStatus.CANCELLED
        await db.commit()
        await db.refresh(order)
        logger.bind(order_id=order_id).info("order_cancelled")
        return order

    async def get_user_orders(
        self, db: AsyncSession, user_id: int, limit: int = 100
    ) -> list[Order]:
        result = await db.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_order(self, db: AsyncSession, order_id: int, user_id: int) -> Order | None:
        order = await db.get(Order, order_id)
        if order is None or order.user_id != user_id:
            return None
        return order


order_service = OrderService()
