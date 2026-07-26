from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, TokenResponse
from app.services.user_service import DuplicateUserError, UserService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = UserService(db)
    existing = await service.get_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    try:
        user = await service.create(payload)
    except DuplicateUserError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered") from err
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    import app.config as config_module
    service = UserService(db)
    access_token = await service.authenticate(form_data.username, form_data.password)
    if access_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await service.get_by_email(form_data.username)
    refresh_token = service.create_refresh_token(user.id)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=config_module.settings.environment == "production",
        samesite="strict",
        max_age=config_module.settings.refresh_token_expire_minutes * 60,
        path="/api/v1/auth",
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    import app.config as config_module

    cookie = response.headers.get("set-cookie")
    token: str | None = None
    if cookie:
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("refresh_token="):
                token = part.split("=", 1)[1]
                break
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    try:
        payload = jwt.decode(token, config_module.settings.secret_key, algorithms=[config_module.settings.algorithm])
        user_id = int(payload.get("sub"))
        token_type = payload.get("type")
        if token_type != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    except (JWTError, TypeError, ValueError) as err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from err

    service = UserService(db)
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    new_access = service.create_access_token(user.id)
    new_refresh = service.create_refresh_token(user.id)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=config_module.settings.environment == "production",
        samesite="strict",
        max_age=config_module.settings.refresh_token_expire_minutes * 60,
        path="/api/v1/auth",
    )
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)
