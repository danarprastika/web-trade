from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.user import TokenResponse
from app.services.oauth_service import OAuthError, OAuthService

router = APIRouter(prefix="/auth/oauth", tags=["auth-oauth"])


@router.get("/{provider}")
async def oauth_redirect(
    provider: str,
    request: Request,
) -> dict:
    if provider not in ("google", "github"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported provider")

    import app.config as config_module

    if provider == "google" and not config_module.settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Google OAuth not configured"
        )
    if provider == "github" and not config_module.settings.github_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="GitHub OAuth not configured"
        )

    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    if provider == "google":
        params = {
            "client_id": config_module.settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    else:
        params = {
            "client_id": config_module.settings.github_client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
        }
        auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"

    return {"auth_url": auth_url}


@router.get("/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code"
        )

    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    service = OAuthService(db)
    try:
        user, access_token, refresh_token = await service.authenticate(provider, code, redirect_uri)
    except OAuthError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err

    import app.config as config_module

    content = TokenResponse(
        access_token=access_token, refresh_token=refresh_token
    ).model_dump_json()
    response = JSONResponse(content=content, media_type="application/json")
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=config_module.settings.environment == "production",
        samesite="strict",
        max_age=config_module.settings.refresh_token_expire_minutes * 60,
        path="/api/v1/auth",
    )
    return response
