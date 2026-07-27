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
        "email": "order@quantx.ai",
        "username": "ordertrader",
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

    asset = Asset(symbol="ETHUSDT", name="Ethereum", asset_class="crypto", exchange="binance")
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    return asset.id


@pytest_asyncio.fixture
async def account_id(db_session, auth_client: AsyncClient):
    from sqlalchemy import select

    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "order@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    account = TradingAccount(
        user_id=user.id,
        name="Order Account",
        account_type=AccountType.PAPER,
        status=AccountStatus.ACTIVE,
        balance=10000.0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    # Create risk profile
    from app.models.risk_profile import RiskProfile

    profile = RiskProfile(user_id=user.id, account_id=account.id)
    db_session.add(profile)
    await db_session.commit()

    return account.id


@pytest.mark.anyio
async def test_create_order(auth_client: AsyncClient, asset_id: int, account_id: int):
    payload = {
        "asset_id": asset_id,
        "side": "buy",
        "order_type": "market",
        "quantity": 0.1,
        "idempotency_key": "test-order-001",
    }
    resp = await auth_client.post("/api/v1/orders/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["side"] == "buy"
    assert data["status"] == "pending"


@pytest.mark.anyio
async def test_idempotency_prevents_duplicate(
    auth_client: AsyncClient, asset_id: int, account_id: int
):
    payload = {
        "asset_id": asset_id,
        "side": "buy",
        "order_type": "market",
        "quantity": 0.1,
        "idempotency_key": "idempotent-order-123",
    }
    resp1 = await auth_client.post("/api/v1/orders/", json=payload)
    assert resp1.status_code == 201
    order_id_1 = resp1.json()["id"]

    # Duplicate request with same idempotency key
    resp2 = await auth_client.post("/api/v1/orders/", json=payload)
    assert resp2.status_code == 201
    order_id_2 = resp2.json()["id"]

    # Should return the same order
    assert order_id_1 == order_id_2


@pytest.mark.anyio
async def test_list_orders(auth_client: AsyncClient, asset_id: int, account_id: int):
    # Create an order first
    await auth_client.post(
        "/api/v1/orders/",
        json={
            "asset_id": asset_id,
            "side": "buy",
            "order_type": "market",
            "quantity": 0.1,
            "idempotency_key": "list-orders-test",
        },
    )
    resp = await auth_client.get("/api/v1/orders/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
