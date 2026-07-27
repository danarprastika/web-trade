import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.risk_profile import (
    CircuitBreakerResponse,
    KillSwitchResponse,
    RiskProfileCreate,
    RiskProfileResponse,
    RiskProfileUpdate,
)
from app.services.risk_service import risk_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/profile", response_model=RiskProfileResponse)
async def get_risk_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RiskProfileResponse:
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount

    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == current_user.id,
            TradingAccount.account_type == "paper",
            TradingAccount.status == "active",
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active paper trading account"
        )

    profile = await risk_service.get_or_create_risk_profile(db, current_user.id, account.id)
    return RiskProfileResponse.model_validate(profile)


@router.post("/profile", response_model=RiskProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_risk_profile(
    payload: RiskProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RiskProfileResponse:
    profile = await risk_service.create_risk_profile(db, current_user.id, payload.account_id)
    return RiskProfileResponse.model_validate(profile)


@router.patch("/profile", response_model=RiskProfileResponse)
async def update_risk_profile(
    payload: RiskProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RiskProfileResponse:
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount

    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == current_user.id,
            TradingAccount.account_type == "paper",
            TradingAccount.status == "active",
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active paper trading account"
        )

    profile = await risk_service.get_or_create_risk_profile(db, current_user.id, account.id)
    if payload.daily_loss_limit is not None:
        profile.daily_loss_limit = payload.daily_loss_limit
    if payload.max_drawdown is not None:
        profile.max_drawdown = payload.max_drawdown
    if payload.position_limit is not None:
        profile.position_limit = payload.position_limit
    if payload.exposure_limit is not None:
        profile.exposure_limit = payload.exposure_limit

    await db.commit()
    await db.refresh(profile)
    return RiskProfileResponse.model_validate(profile)


@router.post("/kill-switch/activate", response_model=KillSwitchResponse)
async def activate_kill_switch(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> KillSwitchResponse:
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount

    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == current_user.id,
            TradingAccount.account_type == "paper",
            TradingAccount.status == "active",
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active paper trading account"
        )

    profile = await risk_service.activate_kill_switch(db, current_user.id, account.id)
    return KillSwitchResponse(
        kill_switch_active=profile.kill_switch_active, message="Kill switch activated"
    )


@router.post("/kill-switch/deactivate", response_model=KillSwitchResponse)
async def deactivate_kill_switch(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> KillSwitchResponse:
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount

    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == current_user.id,
            TradingAccount.account_type == "paper",
            TradingAccount.status == "active",
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active paper trading account"
        )

    profile = await risk_service.deactivate_kill_switch(db, current_user.id, account.id)
    return KillSwitchResponse(
        kill_switch_active=profile.kill_switch_active, message="Kill switch deactivated"
    )


@router.post("/circuit-breaker/reset", response_model=CircuitBreakerResponse)
async def reset_circuit_breaker(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> CircuitBreakerResponse:
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount

    result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == current_user.id,
            TradingAccount.account_type == "paper",
            TradingAccount.status == "active",
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active paper trading account"
        )

    profile = await risk_service.reset_circuit_breaker(db, current_user.id, account.id)
    return CircuitBreakerResponse(
        circuit_breaker_triggered=profile.circuit_breaker_triggered,
        circuit_breaker_reason=profile.circuit_breaker_reason,
        message="Circuit breaker reset",
    )
