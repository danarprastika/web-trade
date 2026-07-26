import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.user import User
from app.services.market_service import market_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/status")
async def market_status() -> dict:
    return {
        "connected": market_manager.connected,
        "subscribed_symbols": ["btcusdt", "ethusdt", "solusdt", "xrpusdt", "dogeusdt"],
    }


@router.websocket("/ws")
async def market_ws(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    await websocket.accept()
    user: User | None = None

    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            from app.dependencies import get_current_user
            from fastapi import Depends
            # We can't use FastAPI Depends in WebSocket directly easily,
            # so we do manual token validation here
            import app.config as config_module
            from jose import JWTError, jwt
            payload = jwt.decode(token, config_module.settings.secret_key, algorithms=[config_module.settings.algorithm])
            subject = payload.get("sub")
            if subject:
                user = await db.get(User, int(subject))
        except (JWTError, TypeError, ValueError):
            user = None

    if user is None or not user.is_active:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    subscribed_symbols: set[str] = set()
    connection_active = True

    def on_price(payload: dict) -> None:
        try:
            import asyncio
            if connection_active:
                asyncio.create_task(websocket.send_json(payload))
        except Exception as exc:
            logger.error("Failed to send market data to client", exc_info=exc)

    try:
        await market_manager.start()
        for sym in ["btcusdt", "ethusdt", "solusdt", "xrpusdt", "dogeusdt"]:
            market_manager.subscribe(sym, on_price)
            subscribed_symbols.add(sym)

        await websocket.send_json({"type": "status", "connected": market_manager.connected})

        while connection_active:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "subscribe":
                symbols = {s.lower() for s in data.get("symbols", [])}
                for sym in symbols - subscribed_symbols:
                    market_manager.subscribe(sym, on_price)
                    subscribed_symbols.add(sym)
                for sym in subscribed_symbols - symbols:
                    market_manager.unsubscribe(sym, on_price)
                    subscribed_symbols.discard(sym)
                await websocket.send_json({"type": "subscribed", "symbols": sorted(subscribed_symbols)})
            elif msg_type == "unsubscribe":
                symbols = {s.lower() for s in data.get("symbols", [])}
                for sym in symbols & subscribed_symbols:
                    market_manager.unsubscribe(sym, on_price)
                    subscribed_symbols.discard(sym)
                await websocket.send_json({"type": "subscribed", "symbols": sorted(subscribed_symbols)})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error", exc_info=exc)
    finally:
        connection_active = False
        for sym in subscribed_symbols:
            market_manager.unsubscribe(sym, on_price)
