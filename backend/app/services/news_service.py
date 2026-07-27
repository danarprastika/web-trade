import structlog
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle, NewsSource

logger = structlog.get_logger(__name__)


class NewsService:
    async def list_sources(self, db: AsyncSession) -> list[NewsSource]:
        result = await db.execute(
            select(NewsSource).where(NewsSource.active.is_(True)).order_by(NewsSource.name)
        )
        return list(result.scalars().all())

    async def create_source(
        self, db: AsyncSession, name: str, url: str, active: bool = True
    ) -> NewsSource:
        source = NewsSource(name=name, url=url, active=active)
        db.add(source)
        await db.commit()
        await db.refresh(source)
        return source

    async def get_source(self, db: AsyncSession, source_id: int) -> NewsSource | None:
        return await db.get(NewsSource, source_id)

    async def create_article(
        self,
        db: AsyncSession,
        source_id: int,
        title: str,
        url: str,
        summary: str | None = None,
        published_at: datetime | None = None,
    ) -> NewsArticle:
        article = NewsArticle(
            source_id=source_id,
            title=title,
            url=url,
            summary=summary,
            published_at=published_at,
        )
        db.add(article)
        await db.commit()
        await db.refresh(article)
        return article

    async def list_articles(
        self, db: AsyncSession, page: int = 1, page_size: int = 20
    ) -> tuple[list[NewsArticle], int]:
        stmt = select(NewsArticle).order_by(
            NewsArticle.published_at.desc().nullslast(), NewsArticle.id.desc()
        )
        count_stmt = select(NewsArticle)

        result = await db.execute(count_stmt)
        total = len(result.scalars().all())

        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def get_article(self, db: AsyncSession, article_id: int) -> NewsArticle | None:
        return await db.get(NewsArticle, article_id)


news_service = NewsService()
