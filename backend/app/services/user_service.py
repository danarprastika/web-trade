from datetime import datetime, timedelta, UTC
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class DuplicateUserError(Exception):
    pass


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, payload: UserCreate) -> User:
        user = User(
            email=payload.email,
            username=payload.username,
            hashed_password=pwd_context.hash(payload.password),
        )
        self.db.add(user)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise DuplicateUserError from exc
        await self.db.refresh(user)
        return user

    async def authenticate(self, email: str, password: str) -> str | None:
        user = await self.get_by_email(email)
        if user is None or not pwd_context.verify(password, user.hashed_password):
            return None
        import app.config as config_module
        expire = datetime.now(UTC) + timedelta(
            minutes=config_module.settings.access_token_expire_minutes
        )
        return jwt.encode(
            {"sub": str(user.id), "exp": expire},
            config_module.settings.secret_key,
            algorithm=config_module.settings.algorithm,
        )

    def create_refresh_token(self, user_id: int) -> str:
        import app.config as config_module
        expire = datetime.now(UTC) + timedelta(
            minutes=config_module.settings.refresh_token_expire_minutes
        )
        return jwt.encode(
            {"sub": str(user_id), "type": "refresh", "exp": expire},
            config_module.settings.secret_key,
            algorithm=config_module.settings.algorithm,
        )

    def create_access_token(self, user_id: int) -> str:
        import app.config as config_module
        expire = datetime.now(UTC) + timedelta(
            minutes=config_module.settings.access_token_expire_minutes
        )
        return jwt.encode(
            {"sub": str(user_id), "exp": expire},
            config_module.settings.secret_key,
            algorithm=config_module.settings.algorithm,
        )
