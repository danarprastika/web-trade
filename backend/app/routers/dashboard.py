import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.asset import Asset
from app.models.user import User
from app.models.watchlist import Watchlist
from app.services.analysis_service import analysis_service
from app.services.market_service import market_manager
from app.services.news_service import news_service
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

    # Collect watchlist symbols for technical signals
    watchlist_result = await db.execute(
        select(Watchlist, Asset)
        .join(Asset, Watchlist.asset_id == Asset.id)
        .where(Watchlist.user_id == current_user.id)
    )
    watchlist_rows = watchlist_result.all()
    signals = []
    for _watch, asset in watchlist_rows:
        prices = market_manager.get_recent_prices(asset.symbol.lower(), limit=50)
        if prices:
            indicators = analysis_service.calculate_indicators(prices)
            signal = analysis_service.get_signal(indicators)
            signals.append(
                {
                    "symbol": asset.symbol,
                    "signal": signal,
                    "sma_20": indicators.get("sma_20"),
                    "rsi_14": indicators.get("rsi_14"),
                }
            )

    # Latest news
    articles, _ = await news_service.list_articles(db, page=1, page_size=5)
    latest_news = [
        {
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        for a in articles
    ]

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
        "latest_news": latest_news,
        "technical_signals": signals,
    }
