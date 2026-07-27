from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.asset import Asset
from app.models.user import User


class Watchlist(Base):
    __tablename__ = "watchlists"

    __table_args__ = (UniqueConstraint("user_id", "asset_id", name="uq_user_asset"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="watchlists")
    asset: Mapped["Asset"] = relationship("Asset", back_populates="watchlist_entries")
