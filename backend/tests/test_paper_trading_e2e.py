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
        "email": "daily@quantx.ai",
        "username": "dailytrader",
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

    asset = Asset(symbol="XRPUSDT", name="XRP", asset_class="crypto", exchange="binance")
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    return asset.id


@pytest_asyncio.fixture
async def account_id(db_session, auth_client: AsyncClient):
    from sqlalchemy import select

    from app.models.risk_profile import RiskProfile
    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "daily@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    account = TradingAccount(
        user_id=user.id,
        name="Daily Loss Account",
        account_type=AccountType.PAPER,
        status=AccountStatus.ACTIVE,
        balance=10000.0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    profile = RiskProfile(user_id=user.id, account_id=account.id, daily_loss_limit=100.0)
    db_session.add(profile)
    await db_session.commit()

    return account.id


@pytest.mark.anyio
async def test_daily_loss_limit_triggers_circuit_breaker(
    auth_client: AsyncClient, asset_id: int, account_id: int, db_session
):
    from sqlalchemy import select

    from app.models.trade import Trade
    from app.models.user import User

    # Create losing trades to exceed daily loss limit
    result = await db_session.execute(select(User).where(User.email == "daily@quantx.ai"))
    user = result.scalar_one_or_none()

    for i in range(5):
        trade = Trade(
            user_id=user.id,
            account_id=account_id,
            order_id=0,
            asset_id=asset_id,
            side="sell",
            quantity=0.1,
            price=100.0 + i,
            pnl=-50.0,  # Each trade loses $50
        )
        db_session.add(trade)
    await db_session.commit()

    # Try to place a new order - should be blocked by risk validation
    payload = {
        "asset_id": asset_id,
        "side": "buy",
        "order_type": "market",
        "quantity": 0.1,
        "idempotency_key": "daily-loss-test",
    }
    resp = await auth_client.post("/api/v1/orders/", json=payload)
    assert resp.status_code == 403
    assert "daily loss limit" in resp.json()["detail"].lower()

    # Reset circuit breaker
    resp = await auth_client.post("/api/v1/risk/circuit-breaker/reset")
    assert resp.status_code == 200
    assert resp.json()["circuit_breaker_triggered"] is False


@pytest.mark.anyio
async def test_strategy_generates_order(
    auth_client: AsyncClient, asset_id: int, account_id: int, db_session
):
    from sqlalchemy import select

    from app.models.strategy import Strategy

    # Create strategy
    create_resp = await auth_client.post(
        "/api/v1/strategies/",
        json={
            "name": "Test MA",
            "asset_id": asset_id,
            "strategy_type": "moving_average_crossover",
            "parameters": {},
            "short_window": 5,
            "long_window": 10,
        },
    )
    assert create_resp.status_code == 201
    strategy_id = create_resp.json()["id"]

    # Start strategy
    start_resp = await auth_client.post(f"/api/v1/strategies/{strategy_id}/start")
    assert start_resp.status_code == 200

    # Simulate price feed by directly calling the strategy engine's price handler
    from app.services.strategy_service import strategy_engine

    result = await db_session.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    assert strategy is not None
    assert strategy.is_running is True

    # Feed prices to trigger crossover (short MA > long MA = buy signal)
    prices_up = [100.0 + i * 0.5 for i in range(12)]  # 12 prices, long_window=10
    for price in prices_up:
        await strategy_engine._on_price(db_session, strategy, {"price": price})

    # Check that an order was created
    resp = await auth_client.get("/api/v1/orders/")
    assert resp.status_code == 200
    orders = resp.json()
    assert len(orders) >= 1

    # Stop strategy
    stop_resp = await auth_client.post(f"/api/v1/strategies/{strategy_id}/stop")
    assert stop_resp.status_code == 200
