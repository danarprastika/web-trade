import time
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {
        "status": "healthy",
        "service": "quantx-backend",
        "version": "0.1.0",
    }


@router.get("/health/ready")
async def health_ready(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    start = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "status": "healthy",
            "checks": {
                "database": {"status": "healthy", "latency_ms": latency_ms},
            },
        }
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "checks": {"database": {"status": "unhealthy", "message": str(exc)}},
            },
        )
