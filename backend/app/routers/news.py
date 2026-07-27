import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.news import (
    NewsArticleCreate,
    NewsArticleListResponse,
    NewsArticleResponse,
    NewsSourceCreate,
    NewsSourceResponse,
)
from app.services.news_service import news_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/sources", response_model=list[NewsSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[NewsSourceResponse]:
    sources = await news_service.list_sources(db)
    return [NewsSourceResponse.model_validate(s) for s in sources]


@router.post("/sources", response_model=NewsSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: NewsSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NewsSourceResponse:
    source = await news_service.create_source(
        db, name=payload.name, url=payload.url, active=payload.active
    )
    return NewsSourceResponse.model_validate(source)


@router.get("/", response_model=NewsArticleListResponse)
async def list_articles(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NewsArticleListResponse:
    items, total = await news_service.list_articles(db, page=page, page_size=page_size)
    return NewsArticleListResponse(
        items=[NewsArticleResponse.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=NewsArticleResponse, status_code=status.HTTP_201_CREATED)
async def create_article(
    payload: NewsArticleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NewsArticleResponse:
    source = await news_service.get_source(db, payload.source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="News source not found")

    article = await news_service.create_article(
        db,
        source_id=payload.source_id,
        title=payload.title,
        url=payload.url,
        summary=payload.summary,
        published_at=payload.published_at,
    )
    return NewsArticleResponse.model_validate(article)


@router.get("/{article_id}", response_model=NewsArticleResponse)
async def get_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> NewsArticleResponse:
    article = await news_service.get_article(db, article_id)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    return NewsArticleResponse.model_validate(article)
