import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.services.position_service import position_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    portfolio = await position_service.get_portfolio_summary(db, current_user.id)
    positions = await position_service.get_open_positions(db, current_user.id)
    trades = await position_service.get_recent_trades(db, current_user.id, limit=5)

    return {
        "portfolio": portfolio,
        "open_positions": [
            {
                "id": p.id,
                "asset_id": p.asset_id,
                "side": p.side,
                "quantity": float(p.quantity),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pnl),
                "realized_pnl": float(p.realized_pnl),
            }
            for p in positions
        ],
        "recent_trades": [
            {
                "id": t.id,
                "asset_id": t.asset_id,
                "side": t.side,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "pnl": float(t.pnl),
                "executed_at": t.executed_at.isoformat(),
            }
            for t in trades
        ],
    }
