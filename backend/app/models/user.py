from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.trading_account import TradingAccount
    from app.models.user_oauth import UserOAuth
    from app.models.watchlist import Watchlist


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    trading_accounts: Mapped[list[TradingAccount]] = relationship(
        "TradingAccount", back_populates="user", cascade="all, delete-orphan"
    )
    oauth_identities: Mapped[list[UserOAuth]] = relationship(
        "UserOAuth", back_populates="user", cascade="all, delete-orphan"
    )
    watchlists: Mapped[list[Watchlist]] = relationship(
        "Watchlist", back_populates="user", cascade="all, delete-orphan"
    )
    strategies: Mapped[list["Strategy"]] = relationship(
        "Strategy", back_populates="user", cascade="all, delete-orphan"
    )  # noqa: F821,UP037
    orders: Mapped[list["Order"]] = relationship(
        "Order", back_populates="user", cascade="all, delete-orphan"
    )  # noqa: F821,UP037
    positions: Mapped[list["Position"]] = relationship(
        "Position", back_populates="user", cascade="all, delete-orphan"
    )  # noqa: F821,UP037
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="user", cascade="all, delete-orphan"
    )  # noqa: F821,UP037
    risk_profiles: Mapped[list["RiskProfile"]] = relationship(
        "RiskProfile", back_populates="user", cascade="all, delete-orphan"
    )  # noqa: F821,UP037
