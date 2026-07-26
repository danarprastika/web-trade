import asyncio
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app
from app.database import Base, get_db


_TEST_DB_LOCK = asyncio.Lock()


def _make_test_settings() -> Settings:
    url = f"sqlite+aiosqlite:///./test_{uuid.uuid4().hex}.db"
    return Settings(database_url=url, secret_key="test-secret-key-for-testing-only", environment="test")


@pytest_asyncio.fixture(autouse=True)
async def setup_env(monkeypatch):
    test_settings = _make_test_settings()
    import app.config as config_module
    monkeypatch.setattr(config_module, "settings", test_settings)

    import app.database as db_module
    await db_module.engine.dispose()
    db_module.engine = create_async_engine(test_settings.database_url, echo=False, pool_pre_ping=True)
    db_module.AsyncSessionLocal = async_sessionmaker(db_module.engine, expire_on_commit=False, class_=AsyncSession)

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


@pytest.mark.anyio
async def test_health_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "quantx-backend"


@pytest.mark.anyio
async def test_health_ready(client: AsyncClient):
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["checks"]["database"]["status"] == "healthy"
    assert "latency_ms" in data["checks"]["database"]


@pytest.mark.anyio
async def test_health_ready_database_failure(monkeypatch):
    import app.database as db_module
    import app.config as config_module

    test_settings = _make_test_settings()
    monkeypatch.setattr(config_module, "settings", test_settings)
    await db_module.engine.dispose()
    db_module.engine = create_async_engine(test_settings.database_url, echo=False, pool_pre_ping=True)
    db_module.AsyncSessionLocal = async_sessionmaker(db_module.engine, expire_on_commit=False, class_=AsyncSession)

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # With a valid DB file, should be healthy
        response = await ac.get("/api/v1/health/ready")
        assert response.status_code == 200

        # Now simulate DB failure by overriding get_db to raise
        class FakeDB:
            async def execute(self, *args, **kwargs):
                raise Exception("simulated database failure")

        async def failing_get_db():
            yield FakeDB()

        app.dependency_overrides[get_db] = failing_get_db
        failure_response = await ac.get("/api/v1/health/ready")
        assert failure_response.status_code == 503
        failure_data = failure_response.json()
        assert failure_data["status"] == "unhealthy"
        assert failure_data["checks"]["database"]["status"] == "unhealthy"
        assert "simulated database failure" in failure_data["checks"]["database"]["message"]

    await db_module.engine.dispose()


@pytest.mark.anyio
async def test_user_registration_and_login(client: AsyncClient):
    # Register
    payload = {
        "email": "trader@quantx.ai",
        "username": "trader1",
        "password": "securepass1",
        "password_confirm": "securepass1",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == payload["email"]
    assert data["username"] == payload["username"]
    assert "id" in data

    # Duplicate registration
    dup = await client.post("/api/v1/auth/register", json=payload)
    assert dup.status_code == 400

    # Login
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"

    # Access protected endpoint
    me_resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == payload["email"]

    # Wrong password
    bad = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": "wrongpass"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert bad.status_code == 401
