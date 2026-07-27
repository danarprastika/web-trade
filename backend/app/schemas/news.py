from datetime import datetime

from pydantic import BaseModel, Field


class NewsSourceBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=255)
    active: bool = True


class NewsSourceCreate(NewsSourceBase):
    pass


class NewsSourceResponse(NewsSourceBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class NewsArticleBase(BaseModel):
    source_id: int
    title: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    published_at: datetime | None = None


class NewsArticleCreate(NewsArticleBase):
    pass


class NewsArticleResponse(NewsArticleBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class NewsArticleListResponse(BaseModel):
    items: list[NewsArticleResponse]
    total: int
    page: int
    page_size: int
