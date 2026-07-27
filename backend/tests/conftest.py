import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base, get_db
from app.main import create_app


def _make_test_settings() -> Settings:
    url = f"sqlite+aiosqlite:///./test_{uuid.uuid4().hex}.db"
    return Settings(
        database_url=url, secret_key="test-secret-key-for-testing-only", environment="test"
    )


@pytest_asyncio.fixture(autouse=True)
async def setup_env(monkeypatch):
    test_settings = _make_test_settings()
    import app.config as config_module

    monkeypatch.setattr(config_module, "settings", test_settings)

    import app.database as db_module

    await db_module.engine.dispose()
    db_module.engine = create_async_engine(
        test_settings.database_url, echo=False, pool_pre_ping=True
    )
    db_module.AsyncSessionLocal = async_sessionmaker(
        db_module.engine, expire_on_commit=False, class_=AsyncSession
    )

    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with db_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await db_module.engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    import app.database as db_module

    async with db_module.AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
