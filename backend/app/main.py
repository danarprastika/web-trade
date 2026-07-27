from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from structlog.stdlib import BoundLogger

from app.routers import auth, health, market, oauth, watchlist

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.config as config_module
    import app.database as db_module

    async with db_module.engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database_connection_verified", app_name=config_module.settings.app_name)
    yield
    await db_module.engine.dispose()


def create_app() -> FastAPI:
    import app.config as config_module

    app = FastAPI(
        title=config_module.settings.app_name,
        version=config_module.settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config_module.settings.allowed_origins,
        allow_credentials=config_module.settings.allow_credentials,
        allow_methods=config_module.settings.allowed_methods,
        allow_headers=config_module.settings.allowed_headers,
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "unknown")
        bound_logger: BoundLogger = logger.bind(request_id=request_id)
        try:
            response = await call_next(request)
            bound_logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response
        except Exception as exc:
            bound_logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                error=str(exc),
                exc_info=True,
            )
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(oauth.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(watchlist.router, prefix="/api/v1")
    app.include_router(market.router, prefix="/api/v1")

    return app


app = create_app()
