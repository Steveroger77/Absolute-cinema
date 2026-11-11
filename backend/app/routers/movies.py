"""Catalogue, search, genre, trending, and fallback poster SVG routes."""

from __future__ import annotations

import math
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_optional_user
from app.models import Genre, Movie, MovieGenre, Rating, User, Watchlist
from app.schemas.api import GenreOut, MovieDetail, MoviePageResponse, MovieSummary
from app.services.poster_svg import render_fallback_poster_svg
from app.services.recommender_service import (
    SUMMARY_LOAD_OPTIONS,
    build_movie_summary,
    recommender_service,
)

router = APIRouter(prefix="/api", tags=["movies"])


def movie_to_summary(movie: Movie) -> MovieSummary:
    return build_movie_summary(movie)


@router.get("/genres", response_model=list[GenreOut])
def list_genres(response: Response, db: Session = Depends(get_db)) -> list[GenreOut]:
    response.headers["Cache-Control"] = "public, max-age=300"
    return recommender_service.get_cached_genres(db)


@router.get("/movies", response_model=MoviePageResponse)
def list_movies(
    page: int = Query(default=1, ge=1, le=500),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = Query(default=None, max_length=64),
    industry: str | None = Query(default=None, max_length=32),
    language: str | None = Query(default=None, max_length=16),
    year: int | None = Query(default=None, ge=1900, le=2030),
    sort: str = Query(default="popular", pattern="^(popular|rating|year|title)$"),
    db: Session = Depends(get_db),
) -> MoviePageResponse:
    stmt = select(Movie).options(*SUMMARY_LOAD_OPTIONS)
    count_stmt = select(func.count(Movie.id))

    if genre:
        g_clean = genre.strip().lower()
        sub = (
            select(MovieGenre.movie_id)
            .join(Genre, Genre.id == MovieGenre.genre_id)
            .where(or_(func.lower(Genre.name) == g_clean, func.lower(Genre.slug) == g_clean))
        )
        stmt = stmt.where(Movie.id.in_(sub))
        count_stmt = count_stmt.where(Movie.id.in_(sub))
    if industry:
        ind = industry.strip().lower()
        stmt = stmt.where(func.lower(Movie.industry) == ind)
        count_stmt = count_stmt.where(func.lower(Movie.industry) == ind)
    if language:
        lang = language.strip().lower()
        stmt = stmt.where(func.lower(Movie.language) == lang)
        count_stmt = count_stmt.where(func.lower(Movie.language) == lang)
    if year:
        stmt = stmt.where(Movie.year == year)
        count_stmt = count_stmt.where(Movie.year == year)

    if sort == "rating":
        stmt = stmt.order_by(desc(Movie.rating_avg), desc(Movie.rating_count))
    elif sort == "year":
        stmt = stmt.order_by(desc(Movie.year), desc(Movie.rating_count))
    elif sort == "title":
        stmt = stmt.order_by(Movie.title.asc())
    else:
        stmt = stmt.order_by(desc(Movie.rating_count), desc(Movie.rating_avg))

    total = int(db.scalar(count_stmt) or 0)
    offset = (page - 1) * page_size
    items = db.scalars(stmt.offset(offset).limit(page_size)).all()

    return MoviePageResponse(
        items=[movie_to_summary(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)) if total else 1,
    )


@router.get("/movies/trending", response_model=list[MovieSummary])
def trending_movies(
    industry: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=16, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[MovieSummary]:
    cache_key = f"trending:{industry or 'all'}:{limit}"
    cached_ids = recommender_service.get_cached_trending_ids(cache_key)
    if cached_ids:
        by_id = recommender_service.get_movie_summaries(cached_ids, db)
        return [by_id[mid] for mid in cached_ids if mid in by_id]

    stmt = select(Movie).options(*SUMMARY_LOAD_OPTIONS).where(Movie.rating_count >= 5)
    if industry:
        stmt = stmt.where(func.lower(Movie.industry) == industry.strip().lower())

    # Balanced Bayesian-style trending score prioritizing acclaimed + popular films
    candidates = list(
        db.scalars(
            stmt.order_by(
                desc(Movie.rating_avg * 0.55 + func.coalesce(Movie.tmdb_rating, 7.0) * 0.15),
                desc(Movie.rating_count),
            ).limit(limit * 3)
        ).all()
    )

    # If mixed ("all"), interleave Hollywood/Bollywood/Tollywood for showcase balance
    if not industry:
        by_ind: dict[str, list[Movie]] = {"hollywood": [], "bollywood": [], "tollywood": []}
        for m in candidates:
            if m.industry in by_ind:
                by_ind[m.industry].append(m)
        # Ensure Bollywood & Tollywood marquee films appear in trending too
        for ind in ("bollywood", "tollywood"):
            if len(by_ind[ind]) < 5:
                extra = db.scalars(
                    select(Movie)
                    .options(*SUMMARY_LOAD_OPTIONS)
                    .where(Movie.industry == ind, Movie.poster_url.is_not(None))
                    .order_by(desc(Movie.rating_count), desc(Movie.rating_avg))
                    .limit(8)
                ).all()
                seen = {x.id for x in by_ind[ind]}
                for e in extra:
                    if e.id not in seen:
                        by_ind[ind].append(e)
        merged: list[Movie] = []
        idx = 0
        while len(merged) < limit and idx < 20:
            for ind in ("hollywood", "tollywood", "bollywood"):
                if idx < len(by_ind[ind]) and len(merged) < limit:
                    merged.append(by_ind[ind][idx])
            idx += 1
        selected = merged
    else:
        selected = candidates[:limit]

    recommender_service.set_cached_trending_ids(cache_key, [m.id for m in selected])
    return [movie_to_summary(m) for m in selected]


@router.get("/movies/search", response_model=list[MovieSummary])
def search_movies(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[MovieSummary]:
    query_str = q.strip()
    if not query_str:
        return []
    q_escaped = query_str.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_pat = f"%{q_escaped}%"
    direct = [
        movie_to_summary(m)
        for m in db.scalars(
            select(Movie)
            .options(*SUMMARY_LOAD_OPTIONS)
            .where(
                or_(
                    Movie.title.ilike(like_pat, escape="\\"),
                    Movie.director.ilike(like_pat, escape="\\"),
                    Movie.cast.ilike(like_pat, escape="\\"),
                    Movie.genres_csv.ilike(like_pat, escape="\\"),
                )
            )
            .order_by(desc(Movie.rating_count), desc(Movie.rating_avg))
            .limit(limit)
        ).all()
    ]

    if len(direct) >= limit:
        return direct

    # Typo-tolerant fallback via lightweight fuzzy matching across cached title tuples
    seen_ids = {m.id for m in direct}
    q_low = query_str.lower()
    all_rows = recommender_service.get_title_index(db)
    scored: list[tuple[float, int]] = []
    for mid, title, rcount in all_rows:
        if mid in seen_ids:
            continue
        ratio = SequenceMatcher(None, q_low, title.lower()).ratio()
        if q_low in title.lower():
            ratio += 0.35
        if ratio >= 0.54:
            scored.append((ratio + min(0.15, (rcount or 0) / 1000.0), mid))

    scored.sort(key=lambda x: x[0], reverse=True)
    extra_ids = [mid for _, mid in scored[: max(0, limit - len(direct))]]
    if extra_ids:
        extra_map = recommender_service.get_movie_summaries(extra_ids, db)
        direct.extend([extra_map[mid] for mid in extra_ids if mid in extra_map])
    return direct[:limit]


@router.get("/movies/{movie_id}", response_model=MovieDetail)
def get_movie_detail(
    movie_id: int,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> MovieDetail:
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    user_rating: float | None = None
    in_watchlist = False
    if user is not None:
        rating_row = db.scalar(select(Rating).where(Rating.user_id == user.id, Rating.movie_id == movie_id))
        if rating_row:
            user_rating = rating_row.rating
        watch_row = db.scalar(
            select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.movie_id == movie_id)
        )
        in_watchlist = watch_row is not None

    summary = movie_to_summary(movie)
    return MovieDetail(
        **summary.model_dump(),
        imdb_id=movie.imdb_id,
        tmdb_id=movie.tmdb_id,
        overview=movie.overview,
        release_date=movie.release_date,
        director=movie.director,
        cast=movie.cast,
        user_rating=user_rating,
        in_watchlist=in_watchlist,
    )


@router.get("/posters/{movie_id}.svg")
def get_fallback_poster_svg(movie_id: int, db: Session = Depends(get_db)) -> Response:
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    svg = render_fallback_poster_svg(movie)
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )
