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
        "email": "risk@quantx.ai",
        "username": "risktrader",
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

    asset = Asset(symbol="DOGEUSDT", name="Dogecoin", asset_class="crypto", exchange="binance")
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    return asset.id


@pytest_asyncio.fixture
async def account_id(db_session, auth_client: AsyncClient):
    from sqlalchemy import select

    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "risk@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    account = TradingAccount(
        user_id=user.id,
        name="Risk Account",
        account_type=AccountType.PAPER,
        status=AccountStatus.ACTIVE,
        balance=10000.0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    from app.models.risk_profile import RiskProfile

    profile = RiskProfile(user_id=user.id, account_id=account.id)
    db_session.add(profile)
    await db_session.commit()

    return account.id


@pytest.mark.anyio
async def test_kill_switch_blocks_trading(auth_client: AsyncClient, asset_id: int, account_id: int):
    # Activate kill switch
    resp = await auth_client.post("/api/v1/risk/kill-switch/activate")
    assert resp.status_code == 200

    # Try to create order - should be blocked
    payload = {
        "asset_id": asset_id,
        "side": "buy",
        "order_type": "market",
        "quantity": 0.1,
        "idempotency_key": "killswitch-test",
    }
    resp = await auth_client.post("/api/v1/orders/", json=payload)
    assert resp.status_code == 403
    assert "kill switch" in resp.json()["detail"].lower()

    # Deactivate kill switch
    resp = await auth_client.post("/api/v1/risk/kill-switch/deactivate")
    assert resp.status_code == 200
    assert resp.json()["kill_switch_active"] is False


@pytest.mark.anyio
async def test_get_risk_profile(auth_client: AsyncClient, account_id: int):
    resp = await auth_client.get("/api/v1/risk/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_loss_limit" in data
    assert "max_drawdown" in data
    assert "position_limit" in data


@pytest.mark.anyio
async def test_update_risk_profile(auth_client: AsyncClient, account_id: int):
    resp = await auth_client.patch(
        "/api/v1/risk/profile",
        json={
            "daily_loss_limit": 500.0,
            "position_limit": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["daily_loss_limit"] == 500.0
    assert data["position_limit"] == 5


@pytest.mark.anyio
async def test_daily_loss_limit_triggers_circuit_breaker(
    db_session: AsyncSession, account_id: int, asset_id: int
):
    from sqlalchemy import select

    from app.models.trade import Trade
    from app.models.user import User
    from app.services.risk_service import risk_service

    result = await db_session.execute(select(User).where(User.email == "risk@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    profile = await risk_service.get_risk_profile(db_session, user.id, account_id)
    assert profile is not None
    profile.daily_loss_limit = 100.0
    await db_session.commit()
    await db_session.refresh(profile)

    from app.models.order import Order

    order = Order(
        user_id=user.id,
        account_id=account_id,
        asset_id=asset_id,
        side="buy",
        order_type="market",
        quantity=0.1,
        status="filled",
        idempotency_key="risk-test-order",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    for _ in range(3):
        trade = Trade(
            user_id=user.id,
            account_id=account_id,
            order_id=order.id,
            asset_id=asset_id,
            side="sell",
            quantity=0.1,
            price=100.0,
            pnl=-50.0,
        )
        db_session.add(trade)
    await db_session.commit()

    ok, reason = await risk_service.validate_trade(db_session, user.id, account_id, 100.0)
    assert ok is False
    assert "daily loss limit" in reason.lower()

    await db_session.refresh(profile)
    assert profile.circuit_breaker_triggered is True
    assert profile.circuit_breaker_reason is not None


@pytest.mark.anyio
async def test_max_drawdown_triggers_circuit_breaker(db_session: AsyncSession, account_id: int):
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount
    from app.models.user import User
    from app.services.risk_service import risk_service

    result = await db_session.execute(select(User).where(User.email == "risk@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    result = await db_session.execute(
        select(TradingAccount).where(TradingAccount.user_id == user.id)
    )
    account = result.scalar_one_or_none()
    assert account is not None

    account.balance = 8000.0
    await db_session.commit()
    await db_session.refresh(account)

    profile = await risk_service.get_risk_profile(db_session, user.id, account_id)
    assert profile is not None
    profile.max_drawdown = 0.2
    await db_session.commit()
    await db_session.refresh(profile)

    ok, reason = await risk_service.validate_trade(db_session, user.id, account_id, 100.0)
    assert ok is False
    assert "max drawdown" in reason.lower()

    await db_session.refresh(profile)
    assert profile.circuit_breaker_triggered is True
    assert profile.circuit_breaker_reason is not None
