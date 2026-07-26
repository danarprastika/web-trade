from datetime import datetime

from pydantic import BaseModel, Field

from app.models.trading_account import AccountStatus, AccountType


class TradingAccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    account_type: AccountType = AccountType.PAPER


class TradingAccountCreate(TradingAccountBase):
    pass


class TradingAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: AccountStatus | None = None


class TradingAccountResponse(TradingAccountBase):
    id: int
    user_id: int
    status: AccountStatus
    balance: float
    currency: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
