from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.user import User


class StrategyStatus(str):
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"


class StrategyType(str):
    MOVING_AVERAGE_CROSSOVER = "moving_average_crossover"


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[str] = mapped_column(String(500), default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=StrategyStatus.STOPPED, nullable=False)
    short_window: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    long_window: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="strategies")  # noqa: F821,UP037
    asset: Mapped["Asset"] = relationship("Asset")  # noqa: F821,UP037
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="strategy")  # noqa: F821,UP037
