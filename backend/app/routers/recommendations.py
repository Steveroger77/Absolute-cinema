"""Recommendation endpoints: personalized (cold-start aware), shelves, similarity, and explanations."""

from __future__ import annotations

from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import get_optional_user
from app.models import Movie, Rating, User
from app.routers.movies import movie_to_summary
from app.schemas.api import (
    BecauseRatedResponse,
    BecauseRatedRowOut,
    ExplainMovieResponse,
    RecommendationReason,
    RecommendationsResponse,
    RecommendedMovieOut,
    TasteProfileResponse,
)
from app.services.recommender_service import recommender_service

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


def _require_model() -> None:
    if not recommender_service.is_loaded:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation model is currently unavailable",
        )


def _load_user_context(
    user: User | None, db: Session
) -> tuple[int, dict[int, float], dict[int, float], list[str], list[str]]:
    """Derive live rating history, timestamps, and onboarding prefs strictly from the authenticated user."""
    if user is None:
        return 0, {}, {}, [], []

    rows = db.execute(
        select(Rating.movie_id, Rating.rating, Rating.rated_at).where(Rating.user_id == user.id)
    ).all()
    history: dict[int, float] = {}
    timestamps: dict[int, float] = {}
    for mid, rating, rated_at in rows:
        m_int = int(mid)
        history[m_int] = float(rating)
        if rated_at is not None:
            dt = rated_at.replace(tzinfo=timezone.utc) if rated_at.tzinfo is None else rated_at
            timestamps[m_int] = float(dt.timestamp())

    pref_genres = [g.strip() for g in (user.preferred_genres or "").split(",") if g.strip()]
    pref_industries = [i.strip() for i in (user.preferred_industries or "").split(",") if i.strip()]
    return user.id, history, timestamps, pref_genres, pref_industries


def _fetch_movie_map(mids: list[int], db: Session) -> dict[int, Movie]:
    if not mids:
        return {}
    movies = db.scalars(select(Movie).where(Movie.id.in_(set(mids)))).all()
    return {m.id: m for m in movies}


def _hydrate_with_map(items: list[Any], by_id: dict[int, Movie]) -> list[RecommendedMovieOut]:
    out: list[RecommendedMovieOut] = []
    for it in items:
        m = by_id.get(it.movie_id)
        if m is None:
            continue
        out.append(
            RecommendedMovieOut(
                movie=movie_to_summary(m),
                score=it.score,
                source=it.source,
                reasons=[RecommendationReason(**r) for r in it.reasons],
            )
        )
    return out


def _hydrate_recommendations(items: list[Any], db: Session) -> list[RecommendedMovieOut]:
    if not items:
        return []
    by_id = _fetch_movie_map([it.movie_id for it in items], db)
    return _hydrate_with_map(items, by_id)


@router.get("/me", response_model=RecommendationsResponse)
def recommend_for_me(
    k: int = Query(default=20, ge=1, le=50),
    genre: str | None = Query(default=None, max_length=64),
    industry: str | None = Query(default=None, max_length=32),
    language: str | None = Query(default=None, max_length=16),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    _require_model()
    uid, history, timestamps, pref_genres, pref_industries = _load_user_context(user, db)

    recs = recommender_service.recommend_for_user(
        user_id=uid,
        user_history=history,
        k=k,
        genre=genre,
        industry=industry,
        language=language,
        preferred_genres=pref_genres,
        preferred_industries=pref_industries,
        user_timestamps=timestamps,
    )
    if history:
        strategy = "personalized_hybrid_cf"
    elif pref_genres or pref_industries:
        strategy = "onboarding_cold_start"
    else:
        strategy = "popular_cold_start"
    return RecommendationsResponse(
        strategy=strategy,
        model_version=recommender_service.version or "unknown",
        items=_hydrate_recommendations(recs, db),
    )


@router.get("/profile", response_model=TasteProfileResponse)
def get_taste_profile(
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> TasteProfileResponse:
    _require_model()
    uid, history, timestamps, pref_genres, pref_industries = _load_user_context(user, db)
    prof = recommender_service.taste_profile(
        user_id=uid,
        user_history=history,
        user_timestamps=timestamps,
        preferred_genres=pref_genres,
        preferred_industries=pref_industries,
    )
    return TasteProfileResponse(
        genre_order=prof.genre_order,
        industry_order=prof.industry_order,
        genre_scores={k: round(v, 4) for k, v in prof.genre_scores.items()},
        industry_scores={k: round(v, 4) for k, v in prof.industry_scores.items()},
    )


@router.get("/because", response_model=BecauseRatedResponse)
def recommend_because_you_rated(
    industry: str | None = Query(default=None, max_length=32),
    limit_rows: int = Query(default=3, ge=1, le=5),
    k: int = Query(default=16, ge=4, le=30),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> BecauseRatedResponse:
    _require_model()
    uid, history, timestamps, pref_genres, pref_industries = _load_user_context(user, db)
    prof = recommender_service.taste_profile(
        user_id=uid,
        user_history=history,
        user_timestamps=timestamps,
        preferred_genres=pref_genres,
        preferred_industries=pref_industries,
    )
    raw_rows = (
        recommender_service.because_you_rated_rows(
            user_id=uid,
            user_history=history,
            user_timestamps=timestamps,
            industry=industry,
            limit_rows=limit_rows,
            k=k,
        )
        if history
        else []
    )
    needed_ids: list[int] = []
    for anchor_mid, _, items in raw_rows:
        needed_ids.append(anchor_mid)
        needed_ids.extend(it.movie_id for it in items)
    by_id = _fetch_movie_map(needed_ids, db)

    hydrated_rows: list[BecauseRatedRowOut] = []
    for anchor_mid, rating_val, items in raw_rows:
        anchor_movie = by_id.get(anchor_mid)
        if anchor_movie is None:
            continue
        rec_items = _hydrate_with_map(items, by_id)
        if rec_items:
            hydrated_rows.append(
                BecauseRatedRowOut(
                    anchor=movie_to_summary(anchor_movie),
                    user_rating=rating_val,
                    items=rec_items,
                )
            )

    return BecauseRatedResponse(
        model_version=recommender_service.version or "unknown",
        genre_order=prof.genre_order,
        industry_order=prof.industry_order,
        rows=hydrated_rows,
    )


@router.get("/explain/{movie_id}", response_model=ExplainMovieResponse)
def explain_movie(
    movie_id: int,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> ExplainMovieResponse:
    _require_model()
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    if user is None:
        return ExplainMovieResponse(movie_id=movie_id, reasons=[])

    uid, history, timestamps, _, _ = _load_user_context(user, db)
    if not history:
        return ExplainMovieResponse(movie_id=movie_id, reasons=[])

    raw_reasons = recommender_service.explain_movie_for_user(
        movie_id=movie_id,
        user_id=uid,
        user_history=history,
        user_timestamps=timestamps,
    )
    return ExplainMovieResponse(
        movie_id=movie_id,
        reasons=[RecommendationReason(**r) for r in raw_reasons],
    )


@router.get("/similar/{movie_id}", response_model=RecommendationsResponse)
def recommend_similar(
    movie_id: int,
    k: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    _require_model()
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")

    recs = recommender_service.similar_movies(movie_id=movie_id, k=k)
    return RecommendationsResponse(
        strategy="item_and_content_similarity",
        model_version=recommender_service.version or "unknown",
        items=_hydrate_recommendations(recs, db),
    )


@router.get("/superheroes", response_model=RecommendationsResponse)
def recommend_superheroes(
    k: int = Query(default=100, ge=1, le=150),
    industry: str | None = Query(default=None, max_length=32),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    _require_model()
    uid, history, timestamps, pref_genres, pref_industries = _load_user_context(user, db)
    recs = recommender_service.recommend_superheroes(
        k=k,
        industry=industry,
        user_id=uid,
        user_history=history,
        user_timestamps=timestamps,
        preferred_genres=pref_genres,
        preferred_industries=pref_industries,
    )
    if history:
        strategy = "personalized_superheroes"
    elif pref_genres or pref_industries:
        strategy = "onboarding_cold_start"
    else:
        strategy = "superhero_collection"
    return RecommendationsResponse(
        strategy=strategy,
        model_version=recommender_service.version or "unknown",
        items=_hydrate_recommendations(recs, db),
    )


@router.get("/genre/{genre}", response_model=RecommendationsResponse)
def recommend_by_genre(
    genre: str,
    k: int = Query(default=20, ge=1, le=40),
    industry: str | None = Query(default=None, max_length=32),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    _require_model()
    uid, history, timestamps, pref_genres, pref_industries = _load_user_context(user, db)
    recs = recommender_service.recommend_by_genre(
        genre=genre,
        k=k,
        industry=industry,
        user_id=uid,
        user_history=history,
        user_timestamps=timestamps,
        preferred_genres=pref_genres,
        preferred_industries=pref_industries,
    )
    if history:
        strategy = "personalized_genre_cf"
    elif pref_genres or pref_industries:
        strategy = "onboarding_cold_start"
    else:
        strategy = "genre_bayesian_ranking"
    return RecommendationsResponse(
        strategy=strategy,
        model_version=recommender_service.version or "unknown",
        items=_hydrate_recommendations(recs, db),
    )


@router.get("/industry/{industry}", response_model=RecommendationsResponse)
def recommend_by_industry(
    industry: str = Path(..., pattern=r"^(hollywood|bollywood|tollywood)$"),
    k: int = Query(default=20, ge=1, le=40),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    _require_model()
    uid, history, timestamps, pref_genres, pref_industries = _load_user_context(user, db)
    recs = recommender_service.recommend_by_industry(
        industry=industry,
        k=k,
        user_id=uid,
        user_history=history,
        user_timestamps=timestamps,
        preferred_genres=pref_genres,
        preferred_industries=pref_industries,
    )
    if history:
        strategy = "personalized_industry_cf"
    elif pref_genres or pref_industries:
        strategy = "onboarding_cold_start"
    else:
        strategy = "industry_bayesian_ranking"
    return RecommendationsResponse(
        strategy=strategy,
        model_version=recommender_service.version or "unknown",
        items=_hydrate_recommendations(recs, db),
    )
