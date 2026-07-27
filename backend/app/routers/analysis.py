import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.services.analysis_service import analysis_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/indicators/{symbol}")
async def get_indicators(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.market_service import market_manager

    prices = market_manager.get_recent_prices(symbol.lower(), limit=50)
    if not prices:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not enough price data for this symbol",
        )
    indicators = analysis_service.calculate_indicators(prices)
    return {"symbol": symbol.upper(), "indicators": indicators}


@router.get("/signals/{symbol}")
async def get_signal(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.market_service import market_manager

    prices = market_manager.get_recent_prices(symbol.lower(), limit=50)
    if not prices:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not enough price data for this symbol",
        )
    indicators = analysis_service.calculate_indicators(prices)
    signal = analysis_service.get_signal(indicators)
    return {"symbol": symbol.upper(), "signal": signal, "indicators": indicators}
