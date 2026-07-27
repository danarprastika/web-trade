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
        "email": "pos@quantx.ai",
        "username": "postrader",
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

    asset = Asset(symbol="SOLUSDT", name="Solana", asset_class="crypto", exchange="binance")
    db_session.add(asset)
    await db_session.commit()
    await db_session.refresh(asset)
    return asset.id


@pytest_asyncio.fixture
async def account_id(db_session, auth_client: AsyncClient):
    from sqlalchemy import select

    from app.models.trading_account import AccountStatus, AccountType, TradingAccount
    from app.models.user import User

    result = await db_session.execute(select(User).where(User.email == "pos@quantx.ai"))
    user = result.scalar_one_or_none()
    assert user is not None

    account = TradingAccount(
        user_id=user.id,
        name="Position Account",
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
async def test_list_positions_empty(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/positions/")
    assert resp.status_code == 200
    assert resp.json() == []
