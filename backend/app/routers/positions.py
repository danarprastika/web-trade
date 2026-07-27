import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.schemas.position import PositionCloseRequest, PositionResponse
from app.services.position_service import position_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/", response_model=list[PositionResponse])
async def list_positions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[PositionResponse]:
    positions = await position_service.get_open_positions(db, current_user.id)
    return [PositionResponse.model_validate(p) for p in positions]


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PositionResponse:
    position = await position_service.get_position(db, position_id, current_user.id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")
    return PositionResponse.model_validate(position)


@router.post("/{position_id}/close", response_model=PositionResponse)
async def close_position(
    position_id: int,
    payload: PositionCloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PositionResponse:
    position = await position_service.get_position(db, position_id, current_user.id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position not found")

    from decimal import Decimal

    close_price = 100.0  # In production, get from market data
    updated = await position_service.close_position(
        db, position, close_price, Decimal(str(payload.quantity))
    )
    return PositionResponse.model_validate(updated)
