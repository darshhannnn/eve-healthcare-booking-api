"""FastAPI application factory."""

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.session import get_engine
from app.seed import seed_admin, seed_demo_data

logger = logging.getLogger("eve.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Base.metadata.create_all(bind=get_engine())
    with Session(bind=get_engine(), expire_on_commit=False) as db:
        seed_admin(db)
        if settings.SEED_DEMO_DATA:
            seed_demo_data(db)
    logger.info(
        "startup complete",
        extra={"environment": settings.ENVIRONMENT, "database": settings.DATABASE_URL.split("@")[-1]},
    )
    yield
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    # Production deployments can hide interactive docs & the schema entirely.
    docs_kwargs = (
        {}
        if settings.DOCS_ENABLED
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )

    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description=(
            "Backend service for diagnostic test bookings and simulated payments.\n\n"
            "**Auth:** `POST /auth/signup` then `POST /auth/login` (JSON or the OAuth2 "
            "form used by the Authorize button). Send `Authorization: Bearer <token>` "
            "on protected calls.\n\n"
            "**Payments:** `POST /payments` charges a PENDING booking via the mock "
            "gateway; the simulated provider reports back on `POST /payments/webhook`, "
            "which is idempotent."
        ),
        lifespan=lifespan,
        **docs_kwargs,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.ENVIRONMENT == "development" else [],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        """Structured request logging + X-Request-ID propagation."""
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request crashed",
                extra={"request_id": request_id, "method": request.method, "path": request.url.path},
            )
            raise
        logger.info(
            "request handled",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/health", tags=["health"], summary="Liveness probe")
    def health() -> dict:
        return {"status": "ok", "environment": settings.ENVIRONMENT}

    app.include_router(api_router)
    return app


app = create_app()
