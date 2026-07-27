import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.order import OrderCreate, OrderResponse
from app.services.order_service import order_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> OrderResponse:
    from decimal import Decimal

    from sqlalchemy import select

    from app.models.trading_account import TradingAccount
    from app.services.risk_service import risk_service

    # Get active paper account
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
            status_code=status.HTTP_400_BAD_REQUEST, detail="No active paper trading account"
        )

    # Validate risk
    risk_ok, reason = await risk_service.validate_trade(
        db, current_user.id, account.id, float(payload.price or 0)
    )
    if not risk_ok:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    try:
        order = await order_service.create_order(
            db=db,
            user_id=current_user.id,
            account_id=account.id,
            asset_id=payload.asset_id,
            side=payload.side,
            order_type=payload.order_type,
            quantity=Decimal(str(payload.quantity)),
            price=Decimal(str(payload.price)) if payload.price else None,
            idempotency_key=payload.idempotency_key,
            strategy_id=payload.strategy_id,
        )
        return OrderResponse.model_validate(order)
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[OrderResponse]:
    orders = await order_service.get_user_orders(db, current_user.id)
    return [OrderResponse.model_validate(o) for o in orders]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> OrderResponse:
    order = await order_service.get_order(db, order_id, current_user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderResponse.model_validate(order)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    order = await order_service.cancel_order(db, order_id, current_user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
