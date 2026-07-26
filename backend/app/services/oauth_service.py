from datetime import datetime, timedelta, UTC
from typing import Literal
from urllib.parse import urlencode

import httpx
import secrets
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.user_oauth import UserOAuth
from app.schemas.user import UserCreate, UserResponse
from app.services.user_service import UserService, pwd_context


class OAuthError(Exception):
    pass


class OAuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def authenticate(self, provider: str, code: str, redirect_uri: str | None = None) -> tuple[UserResponse, str]:
        if provider not in ("google", "github"):
            raise OAuthError("Unsupported OAuth provider")

        if provider == "google":
            profile = await self._exchange_google(code, redirect_uri)
        else:
            profile = await self._exchange_github(code, redirect_uri)

        return await self._get_or_create_user(profile)

    async def _exchange_google(self, code: str, redirect_uri: str | None) -> dict:
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri or settings.oauth_redirect_uri.replace("{provider}", "google"),
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(token_url, data=data)
            if token_resp.status_code != 200:
                raise OAuthError(f"Google token exchange failed: {token_resp.text}")
            tokens = token_resp.json()
            access_token = tokens.get("access_token")
            if not access_token:
                raise OAuthError("Google access token missing")

            user_resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if user_resp.status_code != 200:
                raise OAuthError(f"Google profile fetch failed: {user_resp.text}")
            return user_resp.json()

    async def _exchange_github(self, code: str, redirect_uri: str | None) -> dict:
        token_url = "https://github.com/login/oauth/access_token"
        headers = {"Accept": "application/json"}
        data = {
            "code": code,
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "redirect_uri": redirect_uri or settings.oauth_redirect_uri.replace("{provider}", "github"),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(token_url, headers=headers, data=data)
            if token_resp.status_code != 200:
                raise OAuthError(f"GitHub token exchange failed: {token_resp.text}")
            tokens = token_resp.json()
            access_token = tokens.get("access_token")
            if not access_token:
                raise OAuthError(f"GitHub access token missing: {tokens}")

            user_resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            if user_resp.status_code != 200:
                raise OAuthError(f"GitHub profile fetch failed: {user_resp.text}")
            profile = user_resp.json()
            emails_resp = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            primary_email = None
            if emails_resp.status_code == 200:
                for email_obj in emails_resp.json():
                    if email_obj.get("primary") and email_obj.get("verified"):
                        primary_email = email_obj.get("email")
                        break
            profile["email"] = primary_email or profile.get("email")
            return profile

    async def _get_or_create_user(self, profile: dict) -> tuple[UserResponse, str]:
        provider = profile.get("provider", "unknown")
        provider_user_id = str(profile.get("sub") or profile.get("id") or "")
        provider_email = profile.get("email")
        if not provider_email:
            raise OAuthError("OAuth provider did not return an email")

        stmt = select(UserOAuth).where(
            UserOAuth.provider == provider,
            UserOAuth.provider_user_id == provider_user_id,
        )
        result = await self.db.execute(stmt)
        oauth_identity = result.scalar_one_or_none()

        if oauth_identity:
            user = oauth_identity.user
        else:
            stmt = select(User).where(User.email == provider_email)
            result = await self.db.execute(stmt)
            existing_user = result.scalar_one_or_none()

            if existing_user:
                user = existing_user
            else:
                username = provider_email.split("@")[0][:50]
                base_username = username
                counter = 1
                while True:
                    check = await self.db.execute(select(User).where(User.username == username))
                    if check.scalar_one_or_none() is None:
                        break
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User(
                    email=provider_email,
                    username=username,
                    hashed_password=pwd_context.hash(secrets.token_urlsafe(32)),
                    is_verified=True,
                )
                self.db.add(user)
                await self.db.commit()
                await self.db.refresh(user)

            oauth_identity = UserOAuth(
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
                access_token=profile.get("access_token"),
                refresh_token=profile.get("refresh_token"),
            )
            self.db.add(oauth_identity)
            await self.db.commit()
            await self.db.refresh(oauth_identity)

        access_token = jwt.encode(
            {"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)},
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        refresh_token = jwt.encode(
            {"sub": str(user.id), "type": "refresh", "exp": datetime.now(UTC) + timedelta(minutes=settings.refresh_token_expire_minutes)},
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        return UserResponse.model_validate(user), access_token, refresh_token
