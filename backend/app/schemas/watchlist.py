from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.asset import AssetResponse


class WatchlistBase(BaseModel):
    asset_id: int = Field(gt=0)


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistResponse(WatchlistBase):
    id: int
    user_id: int
    asset: AssetResponse
    created_at: datetime

    model_config = {"from_attributes": True}
