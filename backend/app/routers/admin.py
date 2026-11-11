"""Admin model hot-swap, model metrics info, and service health routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import require_admin
from app.models import User
from app.schemas.api import HealthResponse, ModelInfoResponse
from app.security import limiter
from app.services.recommender_service import recommender_service

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    overall = "ok" if (db_status == "ok" and recommender_service.is_loaded) else "degraded"
    return HealthResponse(
        status=overall,
        database=db_status,
        model_loaded=recommender_service.is_loaded,
        model_version=recommender_service.version,
    )


@router.get("/model/info", response_model=ModelInfoResponse)
def model_info() -> ModelInfoResponse:
    return ModelInfoResponse(
        loaded=recommender_service.is_loaded,
        version=recommender_service.version,
        sha256=recommender_service.sha256,
        metrics=recommender_service.metrics,
    )


@router.post("/admin/model/reload", response_model=ModelInfoResponse)
@limiter.limit("10/minute")
def admin_reload_model(
    request: Request,
    version: str | None = Query(default=None, pattern=r"^v[0-9]+(?:[._-][0-9A-Za-z]+)*$"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ModelInfoResponse:
    try:
        recommender_service.load_model(version=version, db=db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ModelInfoResponse(
        loaded=recommender_service.is_loaded,
        version=recommender_service.version,
        sha256=recommender_service.sha256,
        metrics=recommender_service.metrics,
    )
