from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Position, PositionSide
from app.models.trade import Trade
from app.models.trading_account import TradingAccount

logger = structlog.get_logger(__name__)


class PositionService:
    async def get_open_positions(self, db: AsyncSession, user_id: int) -> list[Position]:
        result = await db.execute(
            select(Position)
            .where(Position.user_id == user_id, Position.is_open)
            .order_by(Position.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_position(
        self, db: AsyncSession, position_id: int, user_id: int
    ) -> Position | None:
        position = await db.get(Position, position_id)
        if position is None or position.user_id != user_id:
            return None
        return position

    async def close_position(
        self,
        db: AsyncSession,
        position: Position,
        close_price: float,
        quantity: Decimal | None = None,
    ) -> Position:
        if not position.is_open:
            return position

        close_qty = quantity if quantity is not None else position.quantity
        if close_qty > position.quantity:
            close_qty = position.quantity

        # Calculate P&L
        if position.side == PositionSide.LONG:
            pnl = (close_price - float(position.avg_entry_price)) * float(close_qty)
        else:
            pnl = (float(position.avg_entry_price) - close_price) * float(close_qty)

        position.realized_pnl += pnl
        position.unrealized_pnl = 0
        position.current_price = close_price

        if close_qty >= position.quantity:
            position.is_open = False
            position.closed_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(position)

        # Create trade record
        trade = Trade(
            user_id=position.user_id,
            account_id=position.account_id,
            order_id=0,
            asset_id=position.asset_id,
            side=PositionSide.SELL if position.side == PositionSide.LONG else PositionSide.BUY,
            quantity=float(close_qty),
            price=close_price,
            pnl=pnl,
        )
        db.add(trade)
        await db.commit()

        logger.bind(position_id=position.id, pnl=pnl).info("position_closed")
        return position

    async def update_unrealized_pnl(
        self, db: AsyncSession, position: Position, current_price: float
    ) -> Position:
        if not position.is_open:
            return position

        position.current_price = current_price
        if position.side == PositionSide.LONG:
            position.unrealized_pnl = (current_price - float(position.avg_entry_price)) * float(
                position.quantity
            )
        else:
            position.unrealized_pnl = (float(position.avg_entry_price) - current_price) * float(
                position.quantity
            )

        await db.commit()
        await db.refresh(position)
        return position

    async def get_portfolio_summary(self, db: AsyncSession, user_id: int) -> dict[str, Any]:
        positions = await self.get_open_positions(db, user_id)
        total_unrealized = sum(float(p.unrealized_pnl) for p in positions)
        total_realized = sum(float(p.realized_pnl) for p in positions)

        # Get account balance
        result = await db.execute(
            select(TradingAccount).where(
                TradingAccount.user_id == user_id,
                TradingAccount.account_type == "paper",
                TradingAccount.status == "active",
            )
        )
        account = result.scalar_one_or_none()
        balance = float(account.balance) if account else 0.0

        return {
            "balance": balance,
            "total_unrealized_pnl": total_unrealized,
            "total_realized_pnl": total_realized,
            "portfolio_value": balance + total_unrealized,
            "open_positions_count": len(positions),
        }

    async def get_recent_trades(
        self, db: AsyncSession, user_id: int, limit: int = 20
    ) -> list[Trade]:
        result = await db.execute(
            select(Trade)
            .where(Trade.user_id == user_id)
            .order_by(Trade.executed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


position_service = PositionService()
