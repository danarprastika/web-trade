from datetime import datetime

from pydantic import BaseModel


class TradeResponse(BaseModel):
    id: int
    user_id: int
    account_id: int
    order_id: int
    asset_id: int
    side: str
    quantity: float
    price: float
    fee: float
    pnl: float
    executed_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
