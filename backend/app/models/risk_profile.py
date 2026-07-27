from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.trading_account import TradingAccount
    from app.models.user import User


class RiskProfile(Base):
    __tablename__ = "risk_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    daily_loss_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=1000.0, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Numeric(18, 2), default=0.2, nullable=False)
    position_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    exposure_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=50000.0, nullable=False)
    kill_switch_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    circuit_breaker_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    circuit_breaker_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="risk_profiles")
    account: Mapped[TradingAccount] = relationship("TradingAccount")
