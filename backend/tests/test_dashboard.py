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
        "email": "dash@quantx.ai",
        "username": "dashtrader",
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
async def setup_dashboard(db_session, auth_client: AsyncClient):
    from sqlalchemy import select

    from app.models.asset import Asset
    from app.models.position import Position, PositionSide
    from app.models.risk_profile import RiskProfile
    from app.models.trade import Trade
    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "dash@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    asset = Asset(
        symbol="DASHUSDT", name="Dashboard Token", asset_class="crypto", exchange="binance"
    )
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)

    account = TradingAccount(
        user_id=user.id,
        name="Dash Account",
        account_type=AccountType.PAPER,
        status=AccountStatus.ACTIVE,
        balance=10000.0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    profile = RiskProfile(user_id=user.id, account_id=account.id)
    db_session.add(profile)
    await db_session.commit()

    # Create an open position
    position = Position(
        user_id=user.id,
        account_id=account.id,
        asset_id=asset.id,
        side=PositionSide.LONG,
        quantity=1.0,
        avg_entry_price=100.0,
        current_price=105.0,
        unrealized_pnl=5.0,
        realized_pnl=0.0,
        is_open=True,
    )
    db_session.add(position)
    await db_session.commit()
    await db_session.refresh(position)

    # Create a trade
    trade = Trade(
        user_id=user.id,
        account_id=account.id,
        order_id=0,
        asset_id=asset.id,
        side="buy",
        quantity=1.0,
        price=100.0,
        pnl=2.0,
    )
    db_session.add(trade)
    await db_session.commit()

    return {"user": user, "account": account, "asset": asset, "position": position, "trade": trade}


@pytest.mark.anyio
async def test_dashboard_summary(auth_client: AsyncClient, setup_dashboard):
    resp = await auth_client.get("/api/v1/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()

    assert "portfolio" in data
    assert data["portfolio"]["balance"] == 10000.0
    assert data["portfolio"]["open_positions_count"] == 1

    assert len(data["open_positions"]) == 1
    assert data["open_positions"][0]["unrealized_pnl"] == 5.0

    assert len(data["recent_trades"]) >= 1
