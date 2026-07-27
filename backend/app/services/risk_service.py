from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk_profile import RiskProfile
from app.models.trade import Trade
from app.models.trading_account import TradingAccount

logger = structlog.get_logger(__name__)


class RiskService:
    async def get_risk_profile(
        self, db: AsyncSession, user_id: int, account_id: int
    ) -> RiskProfile | None:
        result = await db.execute(
            select(RiskProfile).where(
                RiskProfile.user_id == user_id, RiskProfile.account_id == account_id
            )
        )
        return result.scalar_one_or_none()

    async def create_risk_profile(
        self, db: AsyncSession, user_id: int, account_id: int
    ) -> RiskProfile:
        profile = RiskProfile(user_id=user_id, account_id=account_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile

    async def get_or_create_risk_profile(
        self, db: AsyncSession, user_id: int, account_id: int
    ) -> RiskProfile:
        profile = await self.get_risk_profile(db, user_id, account_id)
        if profile is None:
            profile = await self.create_risk_profile(db, user_id, account_id)
        return profile

    async def validate_trade(
        self, db: AsyncSession, user_id: int, account_id: int, price: float
    ) -> tuple[bool, str | None]:
        profile = await self.get_or_create_risk_profile(db, user_id, account_id)

        # Kill switch check
        if profile.kill_switch_active:
            return False, "Kill switch is active. All trading is halted."

        # Circuit breaker check
        if profile.circuit_breaker_triggered:
            return False, f"Circuit breaker triggered: {profile.circuit_breaker_reason}"

        # Get open positions count
        from app.services.position_service import position_service

        positions = await position_service.get_open_positions(db, user_id)

        # Position limit check
        if len(positions) >= profile.position_limit:
            return False, f"Position limit reached ({profile.position_limit})"

        # Exposure limit check (simplified: count open positions)
        total_exposure = sum(float(p.quantity) * price for p in positions)
        if total_exposure >= float(profile.exposure_limit):
            return False, f"Exposure limit reached ({profile.exposure_limit})"

        # Daily loss check
        daily_loss = await self._calculate_daily_loss(db, user_id, account_id)
        if daily_loss <= -float(profile.daily_loss_limit):
            # Trigger circuit breaker
            profile.circuit_breaker_triggered = True
            profile.circuit_breaker_reason = f"Daily loss limit exceeded: {daily_loss:.2f}"
            await db.commit()
            await db.refresh(profile)
            return False, f"Daily loss limit exceeded: {daily_loss:.2f}"

        # Max drawdown check
        drawdown = await self._calculate_drawdown(db, user_id, account_id)
        if drawdown >= float(profile.max_drawdown):
            profile.circuit_breaker_triggered = True
            profile.circuit_breaker_reason = f"Max drawdown exceeded: {drawdown:.2%}"
            await db.commit()
            await db.refresh(profile)
            return False, f"Max drawdown exceeded: {drawdown:.2%}"

        return True, None

    async def activate_kill_switch(
        self, db: AsyncSession, user_id: int, account_id: int
    ) -> RiskProfile:
        profile = await self.get_or_create_risk_profile(db, user_id, account_id)
        profile.kill_switch_active = True
        await db.commit()
        await db.refresh(profile)
        logger.bind(user_id=user_id, account_id=account_id).warning("kill_switch_activated")
        return profile

    async def deactivate_kill_switch(
        self, db: AsyncSession, user_id: int, account_id: int
    ) -> RiskProfile:
        profile = await self.get_or_create_risk_profile(db, user_id, account_id)
        profile.kill_switch_active = False
        profile.circuit_breaker_triggered = False
        profile.circuit_breaker_reason = None
        await db.commit()
        await db.refresh(profile)
        logger.bind(user_id=user_id, account_id=account_id).info("kill_switch_deactivated")
        return profile

    async def reset_circuit_breaker(
        self, db: AsyncSession, user_id: int, account_id: int
    ) -> RiskProfile:
        profile = await self.get_or_create_risk_profile(db, user_id, account_id)
        profile.circuit_breaker_triggered = False
        profile.circuit_breaker_reason = None
        await db.commit()
        await db.refresh(profile)
        logger.bind(user_id=user_id, account_id=account_id).info("circuit_breaker_reset")
        return profile

    async def _calculate_daily_loss(self, db: AsyncSession, user_id: int, account_id: int) -> float:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await db.execute(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.account_id == account_id,
                Trade.executed_at >= today_start,
            )
        )
        trades = result.scalars().all()
        return sum(float(t.pnl) for t in trades)

    async def _calculate_drawdown(self, db: AsyncSession, user_id: int, account_id: int) -> float:
        # Simplified drawdown: (current balance - peak balance) / peak balance
        result = await db.execute(
            select(TradingAccount).where(
                TradingAccount.user_id == user_id,
                TradingAccount.id == account_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            return 0.0

        # For simplicity, we'll use a placeholder peak
        # In production, track historical peak balance
        current_balance = float(account.balance)
        peak_balance = max(current_balance, 10000.0)  # Starting capital assumption
        if peak_balance == 0:
            return 0.0
        return (peak_balance - current_balance) / peak_balance


risk_service = RiskService()
