from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.services.oauth_service import OAuthService


@pytest.mark.anyio
async def test_oauth_redirect_google(client: AsyncClient):
    response = await client.get("/api/v1/auth/oauth/google")
    assert response.status_code == 501


@pytest.mark.anyio
async def test_oauth_redirect_github(client: AsyncClient):
    response = await client.get("/api/v1/auth/oauth/github")
    assert response.status_code == 501


@pytest.mark.anyio
async def test_oauth_redirect_unsupported(client: AsyncClient):
    response = await client.get("/api/v1/auth/oauth/unknown")
    assert response.status_code == 400


@pytest.mark.anyio
async def test_oauth_callback_missing_code(client: AsyncClient):
    response = await client.get("/api/v1/auth/oauth/google/callback")
    assert response.status_code == 400


@pytest.mark.anyio
async def test_oauth_service_google_creates_user(db_session):
    profile = {
        "sub": "123456789",
        "email": "oauthuser@example.com",
        "name": "OAuth User",
        "picture": "https://example.com/pic.jpg",
    }

    service = OAuthService(db_session)
    with patch.object(service, "_exchange_google", return_value=profile):
        user, access_token, refresh_token = await service.authenticate(
            "google", "abc123", "http://test/callback"
        )

    assert user.email == "oauthuser@example.com"
    assert access_token is not None
    assert refresh_token is not None
