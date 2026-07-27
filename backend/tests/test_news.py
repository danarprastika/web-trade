import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import create_app


@pytest_asyncio.fixture
async def client(db_session):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    payload = {
        "email": "news@quantx.ai",
        "username": "newser",
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
async def source_id(db_session):
    from app.services.news_service import news_service

    source = await news_service.create_source(
        db_session, name="Test Source", url="https://example.com"
    )
    return source.id


@pytest.mark.asyncio
async def test_create_and_list_sources(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/v1/news/sources", json={"name": "Reuters", "url": "https://reuters.com"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Reuters"
    assert data["active"] is True

    resp = await auth_client.get("/api/v1/news/sources")
    assert resp.status_code == 200
    items = resp.json()
    assert any(item["name"] == "Reuters" for item in items)


@pytest.mark.asyncio
async def test_create_article(auth_client: AsyncClient, source_id: int):
    payload = {
        "source_id": source_id,
        "title": "BTC surges past 100k",
        "url": "https://example.com/btc-100k",
        "summary": "Bitcoin hits new all-time high.",
        "published_at": "2026-01-01T00:00:00Z",
    }
    resp = await auth_client.post("/api/v1/news/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "BTC surges past 100k"
    assert data["source_id"] == source_id


@pytest.mark.asyncio
async def test_list_articles_pagination(auth_client: AsyncClient, source_id: int):
    for i in range(5):
        await auth_client.post(
            "/api/v1/news/",
            json={
                "source_id": source_id,
                "title": f"Article {i}",
                "url": f"https://example.com/{i}",
            },
        )

    resp = await auth_client.get("/api/v1/news/?page_size=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


@pytest.mark.asyncio
async def test_get_article_not_found(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/news/999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_article_invalid_source(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/v1/news/",
        json={"source_id": 999999, "title": "Fake", "url": "https://example.com"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_article_missing_fields(auth_client: AsyncClient):
    resp = await auth_client.post("/api/v1/news/", json={"title": "No source"})
    assert resp.status_code == 422
