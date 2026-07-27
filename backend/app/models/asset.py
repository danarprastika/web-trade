from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.watchlist import Watchlist


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    watchlist_entries: Mapped[list[Watchlist]] = relationship(
        "Watchlist", back_populates="asset", cascade="all, delete-orphan"
    )
