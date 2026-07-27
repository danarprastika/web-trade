import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import create_app
from app.services.analysis_service import analysis_service


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
        "email": "analysis@quantx.ai",
        "username": "analyst",
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


def test_sma_calculation():
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = analysis_service.calculate_indicators(prices)
    assert result["sma_20"] is None  # not enough data for 20-period
    assert result["ema_20"] is None
    assert result["rsi_14"] is None


def test_sma_with_enough_data():
    prices = list(range(1, 26))  # 1..25
    result = analysis_service.calculate_indicators(prices)
    assert result["sma_20"] == pytest.approx(15.5)
    assert result["ema_20"] is not None
    assert 0 <= result["rsi_14"] <= 100


def test_rsi_extremes():
    # All gains -> RSI = 100
    prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    result = analysis_service.calculate_indicators(prices)
    assert result["rsi_14"] == pytest.approx(100.0, abs=0.1)

    # All losses -> RSI = 0
    prices = [15.0, 14.0, 13.0, 12.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    result = analysis_service.calculate_indicators(prices)
    assert result["rsi_14"] == pytest.approx(0.0, abs=0.1)


def test_get_signal_buy():
    indicators = {"sma_20": 105.0, "ema_20": 100.0, "rsi_14": 25.0}
    assert analysis_service.get_signal(indicators) == "buy"


def test_get_signal_sell():
    indicators = {"sma_20": 95.0, "ema_20": 100.0, "rsi_14": 75.0}
    assert analysis_service.get_signal(indicators) == "sell"


def test_get_signal_hold():
    indicators = {"sma_20": 100.0, "ema_20": 100.0, "rsi_14": 50.0}
    assert analysis_service.get_signal(indicators) == "hold"


@pytest.mark.asyncio
async def test_get_indicators_no_data(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/analysis/indicators/UNKNOWN")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_signal_no_data(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/analysis/signals/UNKNOWN")
    assert resp.status_code == 404
