import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.database import Base, get_db


@pytest_asyncio.fixture
async def client(db_session):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


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


@pytest.mark.anyio
async def test_refresh_token_flow(client: AsyncClient):
    payload = {
        "email": "refresh@quantx.ai",
        "username": "refresher",
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
    client.cookies.set("refresh_token", tokens["refresh_token"], domain="test")

    refresh_resp = await client.post("/api/v1/auth/refresh")
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens


@pytest.mark.anyio
async def test_logout(client: AsyncClient):
    payload = {
        "email": "logout@quantx.ai",
        "username": "logoutuser",
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
    client.cookies.set("refresh_token", tokens["refresh_token"], domain="test")

    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200
