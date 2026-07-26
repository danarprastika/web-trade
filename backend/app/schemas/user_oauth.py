from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserOAuthBase(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    provider_user_id: str = Field(min_length=1, max_length=255)
    provider_email: EmailStr


class UserOAuthCreate(UserOAuthBase):
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: datetime | None = None


class UserOAuthResponse(UserOAuthBase):
    id: int
    user_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
