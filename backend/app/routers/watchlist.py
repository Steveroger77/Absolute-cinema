"""User watchlist routes (object-level authorized)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_current_user
from app.models import Movie, User, Watchlist
from app.routers.movies import movie_to_summary
from app.schemas.api import WatchlistItemOut
from app.security import limiter

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("/me", response_model=list[WatchlistItemOut])
def list_watchlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WatchlistItemOut]:
    rows = db.execute(
        select(Watchlist, Movie)
        .join(Movie, Watchlist.movie_id == Movie.id)
        .where(Watchlist.user_id == user.id)
        .order_by(desc(Watchlist.added_at))
    ).all()
    return [
        WatchlistItemOut(
            movie_id=entry.movie_id,
            added_at=entry.added_at,
            movie=movie_to_summary(movie),
        )
        for entry, movie in rows
    ]


@router.post("/{movie_id}", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
def add_to_watchlist(
    request: Request,
    movie_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WatchlistItemOut:
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    existing = db.scalar(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.movie_id == movie_id)
    )
    if existing:
        return WatchlistItemOut(
            movie_id=existing.movie_id,
            added_at=existing.added_at,
            movie=movie_to_summary(movie),
        )

    entry = Watchlist(user_id=user.id, movie_id=movie_id)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return WatchlistItemOut(
        movie_id=entry.movie_id,
        added_at=entry.added_at,
        movie=movie_to_summary(movie),
    )


@router.delete("/{movie_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute")
def remove_from_watchlist(
    request: Request,
    movie_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    existing = db.scalar(
        select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.movie_id == movie_id)
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist item not found")
    db.delete(existing)
    db.commit()
