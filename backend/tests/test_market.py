import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_market_status_returns_status(client: AsyncClient):
    response = await client.get("/api/v1/market/status")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "subscribed_symbols" in data
