from datetime import datetime

from pydantic import BaseModel, Field


class RiskProfileBase(BaseModel):
    daily_loss_limit: float = Field(ge=0, default=1000.0)
    max_drawdown: float = Field(ge=0, le=1, default=0.2)
    position_limit: int = Field(ge=1, le=100, default=10)
    exposure_limit: float = Field(ge=0, default=50000.0)


class RiskProfileCreate(RiskProfileBase):
    account_id: int


class RiskProfileUpdate(BaseModel):
    daily_loss_limit: float | None = Field(default=None, ge=0)
    max_drawdown: float | None = Field(default=None, ge=0, le=1)
    position_limit: int | None = Field(default=None, ge=1, le=100)
    exposure_limit: float | None = Field(default=None, ge=0)


class RiskProfileResponse(RiskProfileBase):
    id: int
    user_id: int
    account_id: int
    kill_switch_active: bool
    circuit_breaker_triggered: bool
    circuit_breaker_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KillSwitchResponse(BaseModel):
    kill_switch_active: bool
    message: str


class CircuitBreakerResponse(BaseModel):
    circuit_breaker_triggered: bool
    circuit_breaker_reason: str | None
    message: str
