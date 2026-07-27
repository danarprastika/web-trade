from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class StrategyBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    asset_id: int
    strategy_type: str = "moving_average_crossover"
    parameters: dict[str, Any] = Field(default_factory=dict)
    short_window: int = Field(ge=2, le=200)
    long_window: int = Field(ge=5, le=500)


class StrategyCreate(StrategyBase):
    pass


class StrategyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parameters: dict[str, Any] | None = None
    short_window: int | None = Field(default=None, ge=2, le=200)
    long_window: int | None = Field(default=None, ge=5, le=500)


class StrategyResponse(StrategyBase):
    id: int
    user_id: int
    status: str
    is_running: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("parameters", mode="before")
    @classmethod
    def parse_parameters(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            import json

            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}
        return value

    model_config = {"from_attributes": True}


class StrategyStartResponse(BaseModel):
    id: int
    status: str
    is_running: bool
    message: str
