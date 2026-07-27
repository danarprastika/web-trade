from datetime import datetime

from pydantic import BaseModel, Field


class PositionResponse(BaseModel):
    id: int
    user_id: int
    account_id: int
    asset_id: int
    side: str
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    is_open: bool
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PositionCloseRequest(BaseModel):
    quantity: float = Field(gt=0)
