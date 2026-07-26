from datetime import datetime

from pydantic import BaseModel, Field


class AssetBase(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    asset_class: str = Field(min_length=1, max_length=50)
    exchange: str | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)


class AssetCreate(AssetBase):
    pass


class AssetResponse(AssetBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
