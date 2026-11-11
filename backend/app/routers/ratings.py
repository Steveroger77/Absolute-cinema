"""User rating upsert, delete, and listing routes with atomic movie aggregate updates."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models import Movie, Rating, User
from app.routers.movies import movie_to_summary
from app.schemas.api import RatingOut, RatingUpsertRequest
from app.security import limiter
from app.services.recommender_service import recommender_service

router = APIRouter(prefix="/api/ratings", tags=["ratings"])


def _recompute_movie_aggregates(movie: Movie, db: Session) -> None:
    avg_val, count_val = db.execute(
        select(func.avg(Rating.rating), func.count(Rating.id)).where(Rating.movie_id == movie.id)
    ).one()
    movie.rating_avg = round(float(avg_val or 0.0), 3)
    movie.rating_count = int(count_val or 0)


@router.get("/me", response_model=list[RatingOut])
def get_my_ratings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RatingOut]:
    rows = db.scalars(select(Rating).where(Rating.user_id == user.id).order_by(desc(Rating.rated_at))).all()
    summaries = recommender_service.get_movie_summaries([r.movie_id for r in rows], db)
    return [
        RatingOut(
            movie_id=rating.movie_id,
            rating=rating.rating,
            source=rating.source,
            rated_at=rating.rated_at,
            movie=summaries[rating.movie_id],
        )
        for rating in rows
        if rating.movie_id in summaries
    ]


@router.put("/{movie_id}", response_model=RatingOut)
@limiter.limit("60/minute")
def upsert_rating(
    request: Request,
    movie_id: int,
    payload: RatingUpsertRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RatingOut:
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    existing = db.scalar(select(Rating).where(Rating.user_id == user.id, Rating.movie_id == movie_id))
    now = datetime.now(timezone.utc)
    if existing:
        existing.rating = payload.rating
        existing.rated_at = now
        existing.source = "user"
        record = existing
    else:
        record = Rating(
            user_id=user.id,
            movie_id=movie_id,
            rating=payload.rating,
            source="user",
            rated_at=now,
        )
        db.add(record)

    db.flush()
    _recompute_movie_aggregates(movie, db)
    db.commit()
    db.refresh(record)
    db.refresh(movie)
    recommender_service.update_movie_summary(db, movie)
    recommender_service.invalidate_user_cache(user.id)

    return RatingOut(
        movie_id=record.movie_id,
        rating=record.rating,
        source=record.source,
        rated_at=record.rated_at,
        movie=movie_to_summary(movie),
    )


@router.delete("/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute")
def delete_rating(
    request: Request,
    movie_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    existing = db.scalar(select(Rating).where(Rating.user_id == user.id, Rating.movie_id == movie_id))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")
    movie = db.get(Movie, movie_id)
    db.delete(existing)
    db.flush()
    if movie is not None:
        _recompute_movie_aggregates(movie, db)
    db.commit()
    if movie is not None:
        db.refresh(movie)
        recommender_service.update_movie_summary(db, movie)
    recommender_service.invalidate_user_cache(user.id)
