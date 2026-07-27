from datetime import datetime

from pydantic import BaseModel, Field


class OrderBase(BaseModel):
    asset_id: int
    side: str = Field(pattern="^(buy|sell)$")
    order_type: str = Field(pattern="^(market|limit)$")
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)


class OrderCreate(OrderBase):
    idempotency_key: str = Field(min_length=1, max_length=100)
    strategy_id: int | None = None


class OrderUpdate(BaseModel):
    status: str | None = None
    filled_quantity: float | None = None


class OrderResponse(OrderBase):
    id: int
    user_id: int
    account_id: int
    strategy_id: int | None
    status: str
    idempotency_key: str
    filled_quantity: float
    filled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
