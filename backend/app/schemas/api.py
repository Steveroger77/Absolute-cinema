"""Pydantic v2 request and response contracts for ABSOLUTE CINEMA."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GoogleAuthRequest(BaseModel):
    credential: str = Field(min_length=20, max_length=4096)


class OnboardingRequest(BaseModel):
    preferred_genres: list[str] = Field(default_factory=list, max_length=10)
    preferred_industries: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("preferred_industries")
    @classmethod
    def check_industries(cls, vals: list[str]) -> list[str]:
        allowed = {"hollywood", "bollywood", "tollywood"}
        cleaned: list[str] = []
        for v in vals:
            low = v.strip().lower()
            if low not in allowed:
                raise ValueError(f"Unsupported industry: {v}")
            if low not in cleaned:
                cleaned.append(low)
        return cleaned


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    role: str
    avatar_url: str | None = None
    auth_provider: str = "local"
    preferred_genres: list[str]
    preferred_industries: list[str]
    onboarding_completed: bool
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


class MovieSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    year: int | None = None
    industry: str
    language: str
    poster_url: str | None = None
    backdrop_url: str | None = None
    runtime: int | None = None
    tmdb_rating: float | None = None
    genres: list[str]
    dominant_color: str
    accent_color: str
    shadow_color: str
    color_luminance: str
    rating_avg: float
    rating_count: int


class MovieDetail(MovieSummary):
    imdb_id: str | None = None
    tmdb_id: int | None = None
    overview: str | None = None
    release_date: str | None = None
    director: str | None = None
    cast: str | None = None
    user_rating: float | None = None
    in_watchlist: bool = False


class MoviePageResponse(BaseModel):
    items: list[MovieSummary]
    total: int
    page: int
    page_size: int
    total_pages: int


class GenreOut(BaseModel):
    id: int
    name: str
    slug: str
    movie_count: int = 0


class RatingUpsertRequest(BaseModel):
    rating: float = Field(ge=0.5, le=5.0)

    @field_validator("rating")
    @classmethod
    def validate_half_star(cls, v: float) -> float:
        if abs(v * 2.0 - round(v * 2.0)) > 1e-6:
            raise ValueError("Rating must be in 0.5 increments between 0.5 and 5.0")
        return float(round(v * 2.0) / 2.0)


class RatingOut(BaseModel):
    movie_id: int
    rating: float
    source: str
    rated_at: datetime
    movie: MovieSummary | None = None


class WatchlistItemOut(BaseModel):
    movie_id: int
    added_at: datetime
    movie: MovieSummary


class RecommendationReason(BaseModel):
    type: str
    movie_id: int | None = None
    title: str | None = None
    user_rating: float | None = None
    weight: float | None = None
    label: str | None = None


class RecommendedMovieOut(BaseModel):
    movie: MovieSummary
    score: float
    source: str
    reasons: list[RecommendationReason]


class RecommendationsResponse(BaseModel):
    strategy: str
    model_version: str
    items: list[RecommendedMovieOut]


class TasteProfileResponse(BaseModel):
    genre_order: list[str]
    industry_order: list[str]
    genre_scores: dict[str, float]
    industry_scores: dict[str, float]


class BecauseRatedRowOut(BaseModel):
    anchor: MovieSummary
    user_rating: float
    items: list[RecommendedMovieOut]


class BecauseRatedResponse(BaseModel):
    model_version: str
    genre_order: list[str]
    industry_order: list[str]
    rows: list[BecauseRatedRowOut]


class ExplainMovieResponse(BaseModel):
    movie_id: int
    reasons: list[RecommendationReason]


class ModelInfoResponse(BaseModel):
    loaded: bool
    version: str | None = None
    sha256: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    database: str
    model_loaded: bool
    model_version: str | None = None
