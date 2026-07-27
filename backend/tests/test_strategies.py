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
        "email": "strat@quantx.ai",
        "username": "strategist",
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
async def asset_id(db_session):
    from app.models.asset import Asset

    asset = Asset(symbol="BTCUSDT", name="Bitcoin", asset_class="crypto", exchange="binance")
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    return asset.id


@pytest_asyncio.fixture
async def account_id(db_session, auth_client: AsyncClient):
    from sqlalchemy import select

    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "strat@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    account = TradingAccount(
        user_id=user.id,
        name="Strategy Account",
        account_type=AccountType.PAPER,
        status=AccountStatus.ACTIVE,
        balance=10000.0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account.id


@pytest.mark.anyio
async def test_create_strategy(auth_client: AsyncClient, asset_id: int, account_id: int):
    payload = {
        "name": "MA Crossover",
        "asset_id": asset_id,
        "strategy_type": "moving_average_crossover",
        "parameters": {},
        "short_window": 5,
        "long_window": 20,
    }
    resp = await auth_client.post("/api/v1/strategies/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "MA Crossover"
    assert data["status"] == "stopped"
    assert data["is_running"] is False


@pytest.mark.anyio
async def test_list_strategies(auth_client: AsyncClient, asset_id: int):
    # Create a strategy first
    await auth_client.post(
        "/api/v1/strategies/",
        json={
            "name": "Test Strat",
            "asset_id": asset_id,
            "strategy_type": "moving_average_crossover",
            "parameters": {},
            "short_window": 5,
            "long_window": 20,
        },
    )
    resp = await auth_client.get("/api/v1/strategies/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


@pytest.mark.anyio
async def test_start_and_stop_strategy(auth_client: AsyncClient, asset_id: int, account_id: int):
    # Create strategy
    create_resp = await auth_client.post(
        "/api/v1/strategies/",
        json={
            "name": "MA Crossover",
            "asset_id": asset_id,
            "strategy_type": "moving_average_crossover",
            "parameters": {},
            "short_window": 5,
            "long_window": 20,
        },
    )
    strategy_id = create_resp.json()["id"]

    # Start strategy
    start_resp = await auth_client.post(f"/api/v1/strategies/{strategy_id}/start")
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    assert start_data["is_running"] is True
    assert start_data["status"] == "active"

    # Pause strategy
    pause_resp = await auth_client.post(f"/api/v1/strategies/{strategy_id}/pause")
    assert pause_resp.status_code == 200
    pause_data = pause_resp.json()
    assert pause_data["is_running"] is False
    assert pause_data["status"] == "paused"

    # Stop strategy
    stop_resp = await auth_client.post(f"/api/v1/strategies/{strategy_id}/stop")
    assert stop_resp.status_code == 200
    stop_data = stop_resp.json()
    assert stop_data["is_running"] is False
    assert stop_data["status"] == "stopped"
