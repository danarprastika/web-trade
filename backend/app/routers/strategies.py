import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.strategy import StrategyStatus
from app.models.user import User
from app.schemas.strategy import (
    StrategyCreate,
    StrategyResponse,
    StrategyStartResponse,
    StrategyUpdate,
)
from app.services.risk_service import risk_service
from app.services.strategy_service import strategy_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.post("/", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    payload: StrategyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StrategyResponse:
    from app.models.strategy import Strategy

    strategy = Strategy(
        user_id=current_user.id,
        asset_id=payload.asset_id,
        name=payload.name,
        strategy_type=payload.strategy_type,
        parameters=str(payload.parameters),
        short_window=payload.short_window,
        long_window=payload.long_window,
        status=StrategyStatus.STOPPED,
        is_running=False,
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


@router.get("/", response_model=list[StrategyResponse])
async def list_strategies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[StrategyResponse]:
    from sqlalchemy import select

    from app.models.strategy import Strategy

    result = await db.execute(select(Strategy).where(Strategy.user_id == current_user.id))
    strategies = result.scalars().all()
    return [StrategyResponse.model_validate(s) for s in strategies]


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StrategyResponse:
    from app.models.strategy import Strategy

    strategy = await db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    return StrategyResponse.model_validate(strategy)


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    payload: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StrategyResponse:
    from app.models.strategy import Strategy

    strategy = await db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    if strategy.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update running strategy. Pause it first.",
        )

    if payload.name is not None:
        strategy.name = payload.name
    if payload.parameters is not None:
        strategy.parameters = str(payload.parameters)
    if payload.short_window is not None:
        strategy.short_window = payload.short_window
    if payload.long_window is not None:
        strategy.long_window = payload.long_window

    await db.commit()
    await db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


@router.post("/{strategy_id}/start", response_model=StrategyStartResponse)
async def start_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StrategyStartResponse:
    from app.models.strategy import Strategy

    strategy = await db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    # Check kill switch
    from sqlalchemy import select

    from app.models.trading_account import TradingAccount

    account_result = await db.execute(
        select(TradingAccount).where(
            TradingAccount.user_id == current_user.id,
            TradingAccount.account_type == "paper",
            TradingAccount.status == "active",
        )
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No active paper trading account found"
        )

    risk_profile = await risk_service.get_or_create_risk_profile(db, current_user.id, account.id)
    if risk_profile.kill_switch_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kill switch is active. Cannot start strategy.",
        )

    updated = await strategy_engine.start_strategy(db, strategy_id)
    return StrategyStartResponse(
        id=updated.id,
        status=updated.status,
        is_running=updated.is_running,
        message="Strategy started successfully",
    )


@router.post("/{strategy_id}/pause", response_model=StrategyStartResponse)
async def pause_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StrategyStartResponse:
    from app.models.strategy import Strategy

    strategy = await db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    updated = await strategy_engine.pause_strategy(db, strategy_id)
    return StrategyStartResponse(
        id=updated.id,
        status=updated.status,
        is_running=updated.is_running,
        message="Strategy paused successfully",
    )


@router.post("/{strategy_id}/stop", response_model=StrategyStartResponse)
async def stop_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> StrategyStartResponse:
    from app.models.strategy import Strategy

    strategy = await db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    updated = await strategy_engine.stop_strategy(db, strategy_id)
    return StrategyStartResponse(
        id=updated.id,
        status=updated.status,
        is_running=updated.is_running,
        message="Strategy stopped successfully",
    )


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    from app.models.strategy import Strategy

    strategy = await db.get(Strategy, strategy_id)
    if strategy is None or strategy.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    if strategy.is_running:
        await strategy_engine.stop_strategy(db, strategy_id)

    await db.delete(strategy)
    await db.commit()
