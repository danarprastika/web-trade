import pytest
from httpx import AsyncClient

from app.models.asset import Asset


@pytest.mark.anyio
async def test_watchlist_crud(client: AsyncClient, db_session):
    # Create an asset directly
    asset = Asset(
        symbol="btcusdt", name="Bitcoin", asset_class="crypto", exchange="binance", currency="USD"
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    asset_id = asset.id

    # Register and login
    payload = {
        "email": "watchlist@quantx.ai",
        "username": "watchlister",
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
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # List should be empty
    list_resp = await client.get("/api/v1/watchlist/", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json() == []

    # Add asset
    add_resp = await client.post("/api/v1/watchlist/", json={"asset_id": asset_id}, headers=headers)
    assert add_resp.status_code == 201
    assert add_resp.json()["asset_id"] == asset_id

    # List should have one item
    list_resp = await client.get("/api/v1/watchlist/", headers=headers)
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["asset"]["symbol"] == "btcusdt"

    # Duplicate add should fail
    dup = await client.post("/api/v1/watchlist/", json={"asset_id": asset_id}, headers=headers)
    assert dup.status_code == 400

    # Remove asset
    remove_resp = await client.delete(f"/api/v1/watchlist/{asset_id}", headers=headers)
    assert remove_resp.status_code == 204

    # List should be empty again
    list_resp = await client.get("/api/v1/watchlist/", headers=headers)
    assert list_resp.json() == []


@pytest.mark.anyio
async def test_watchlist_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/watchlist/")
    assert response.status_code == 401
