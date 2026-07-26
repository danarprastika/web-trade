import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.database import Base, get_db
from app.config import Settings
import app.database as db_module
import app.config as config_module
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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
    import asyncio

    url = f"sqlite+aiosqlite:///./test_{__import__('uuid').uuid4().hex}.db"
    test_settings = Settings(database_url=url, secret_key="test-secret-key-for-testing-only", environment="test")
    monkeypatch.setattr(config_module, "settings", test_settings)

    await db_module.engine.dispose()
    db_module.engine = create_async_engine(test_settings.database_url, echo=False, pool_pre_ping=True)
    db_module.AsyncSessionLocal = async_sessionmaker(db_module.engine, expire_on_commit=False, class_=AsyncSession)

    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/health/ready")
        assert response.status_code == 200

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
