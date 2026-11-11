"""FastAPI application entrypoint, security middleware, exception envelopes, and lifecycle."""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.db.session import SessionLocal
from app.routers import admin, auth, movies, ratings, recommendations, watchlist
from app.security import limiter
from app.services.recommender_service import recommender_service

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("absolute_cinema.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_runtime_security()
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        artifacts_dir = Path(settings.model_artifacts_dir)
        if artifacts_dir.exists() and list(artifacts_dir.glob("model_v*.joblib")):
            try:
                recommender_service.load_model(db=db)
            except Exception as exc:
                logger.error("Failed to load recommender artifact cleanly: %s", exc)
        else:
            logger.warning("No trained model artifact found in %s at startup.", artifacts_dir)
        if not settings.google_client_id:
            logger.warning(
                "GOOGLE_CLIENT_ID is not configured; Google Sign-In (/api/auth/google) is disabled."
            )
    except Exception as exc:
        logger.critical("Database connectivity check failed during startup: %s", exc)
        raise RuntimeError("Database unreachable on startup") from exc
    finally:
        db.close()
    yield


app = FastAPI(
    title="ABSOLUTE CINEMA API",
    version="1.0.0",
    description=(
        "Hybrid Collaborative Filtering Movie Recommendation API across Hollywood, Bollywood & Tollywood."
    ),
    lifespan=lifespan,
    docs_url="/api/docs" if not settings.is_production else None,
    redoc_url=None,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers_and_timing(request: Request, call_next: Any):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/posters/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


def _error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(f"http_{exc.status_code}", str(exc.detail)),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_req: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_payload("validation_error", "Invalid request parameters", safe_errors),
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(_req: Request, _exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=_error_payload("rate_limited", "Too many requests. Please wait briefly."),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_req: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error during request: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload("internal_error", "An unexpected error occurred."),
    )


app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(movies.router)
app.include_router(ratings.router)
app.include_router(watchlist.router)
app.include_router(recommendations.router)
