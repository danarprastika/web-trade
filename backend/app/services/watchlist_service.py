from typing import Sequence

from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.watchlist import Watchlist
from app.schemas.watchlist import WatchlistCreate, WatchlistResponse


class WatchlistService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, user_id: int) -> list[WatchlistResponse]:
        stmt = select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.created_at.desc())
        result = await self.db.execute(stmt)
        watchlists = result.scalars().all()
        return [WatchlistResponse.model_validate(item) for item in watchlists]

    async def add(self, user_id: int, payload: WatchlistCreate) -> WatchlistResponse:
        asset = await self.db.get(Asset, payload.asset_id)
        if asset is None or not asset.is_active:
            raise ValueError("Asset not found or inactive")

        watchlist = Watchlist(user_id=user_id, asset_id=payload.asset_id)
        self.db.add(watchlist)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError("Asset already in watchlist")
        await self.db.refresh(watchlist)
        return WatchlistResponse.model_validate(watchlist)

    async def remove(self, user_id: int, asset_id: int) -> None:
        stmt = delete(Watchlist).where(Watchlist.user_id == user_id, Watchlist.asset_id == asset_id)
        await self.db.execute(stmt)
        await self.db.commit()
