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


@pytest_asyncio.fixture
async def authenticated_client(client: AsyncClient):
    # Register and login a test user
    payload = {
        "email": "trader@quantx.ai",
        "username": "trader1",
        "password": "securepass1",
        "password_confirm": "securepass1",
    }
    await client.post("/api/v1/auth/register", json=payload)
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    tokens = login_resp.json()
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    return client


@pytest_asyncio.fixture
async def setup_account(db_session: AsyncSession, authenticated_client: AsyncClient):
    # Create a paper trading account for the user
    from sqlalchemy import select

    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "trader@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    account = TradingAccount(
        user_id=user.id,
        name="Test Paper Account",
        account_type=AccountType.PAPER,
        status=AccountStatus.ACTIVE,
        balance=10000.0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    # Create risk profile
    from app.models.risk_profile import RiskProfile

    profile = RiskProfile(user_id=user.id, account_id=account.id)
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)

    return {"user": user, "account": account, "profile": profile}
