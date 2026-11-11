"""In-memory RecommenderService wrapper with hot-swap reload and per-user versioned caching."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, load_only

# Ensure project root is importable for `ml.src.loader` without importing training logic
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.src.loader import RecommendationItem, RecommenderEngine, UserTasteProfile  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import Genre, ModelVersion, Movie, MovieGenre  # noqa: E402
from app.schemas.api import GenreOut, MovieSummary  # noqa: E402

logger = logging.getLogger(__name__)

_MAX_USER_CACHE_ENTRIES = 512
_MAX_BIND_CACHES = 8

SUMMARY_COLUMNS = (
    Movie.id,
    Movie.title,
    Movie.year,
    Movie.industry,
    Movie.language,
    Movie.poster_url,
    Movie.backdrop_url,
    Movie.runtime,
    Movie.tmdb_rating,
    Movie.genres_csv,
    Movie.dominant_color,
    Movie.accent_color,
    Movie.shadow_color,
    Movie.color_luminance,
    Movie.rating_avg,
    Movie.rating_count,
)
SUMMARY_LOAD_OPTIONS = (load_only(*SUMMARY_COLUMNS),)


def build_movie_summary(row: Any) -> MovieSummary:
    genres = [g.strip() for g in (row.genres_csv or "").split("|") if g.strip()]
    return MovieSummary(
        id=int(row.id),
        title=str(row.title),
        year=row.year,
        industry=str(row.industry),
        language=str(row.language),
        poster_url=row.poster_url,
        backdrop_url=row.backdrop_url,
        runtime=row.runtime,
        tmdb_rating=row.tmdb_rating,
        genres=genres,
        dominant_color=str(row.dominant_color),
        accent_color=str(row.accent_color),
        shadow_color=str(row.shadow_color),
        color_luminance=str(row.color_luminance),
        rating_avg=round(float(row.rating_avg or 0.0), 2),
        rating_count=int(row.rating_count or 0),
    )


class RecommenderService:
    """Thread-safe singleton holding the loaded RecommenderEngine artifact and isolated caches."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engine: RecommenderEngine | None = None
        self._metrics: dict[str, Any] = {}
        self._trending_cache: dict[str, tuple[float, list[int]]] = {}
        self._cache_ttl_seconds = 300.0
        # Per-user monotonically bumped version + bounded LRU cache strictly keyed by (user_id, version, ...)
        self._user_versions: dict[int, int] = {}
        self._user_rec_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        # Bind-keyed read-through caches so Postgres summary lookups stay 0-query on warm hits
        self._movie_caches: OrderedDict[int, dict[int, MovieSummary]] = OrderedDict()
        self._movie_full_loaded: set[int] = set()
        self._genre_caches: OrderedDict[int, list[GenreOut]] = OrderedDict()

    @property
    def is_loaded(self) -> bool:
        return self._engine is not None

    @property
    def version(self) -> str | None:
        return self._engine.version if self._engine else None

    @property
    def sha256(self) -> str | None:
        return self._engine.sha256 if self._engine else None

    @property
    def metrics(self) -> dict[str, Any]:
        return self._metrics

    def get_user_version(self, user_id: int) -> int:
        with self._lock:
            return self._user_versions.get(user_id, 0)

    def _cache_get(self, key: tuple[Any, ...]) -> Any:
        if key in self._user_rec_cache:
            self._user_rec_cache.move_to_end(key)
            return self._user_rec_cache[key]
        return None

    def _cache_set(self, key: tuple[Any, ...], value: Any) -> None:
        self._user_rec_cache[key] = value
        self._user_rec_cache.move_to_end(key)
        while len(self._user_rec_cache) > _MAX_USER_CACHE_ENTRIES:
            self._user_rec_cache.popitem(last=False)

    def load_model(self, version: str | None = None, db: Session | None = None) -> str:
        settings = get_settings()
        artifacts_dir = Path(settings.model_artifacts_dir).resolve()
        with self._lock:
            if version:
                artifact_path = (artifacts_dir / f"model_{version}.joblib").resolve()
                if not artifact_path.is_relative_to(artifacts_dir) or not artifact_path.exists():
                    raise FileNotFoundError(f"Model artifact not found: {artifact_path.name}")
                engine = RecommenderEngine.load(artifact_path, version=version)
            else:
                engine = RecommenderEngine.load_latest(artifacts_dir)

            metrics_path = artifacts_dir / "metrics.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}

            self._engine = engine
            self._metrics = metrics
            self._trending_cache.clear()
            self._user_rec_cache.clear()
            self._user_versions.clear()
            logger.info("Loaded recommender model version=%s sha256=%s", engine.version, engine.sha256[:12])

            if db is not None:
                self.register_model_version(db, artifacts_dir)
            return engine.version

    def register_model_version(self, db: Session, artifacts_dir: Path) -> None:
        if self._engine is None:
            return
        db.query(ModelVersion).update({"is_active": False})
        existing = db.query(ModelVersion).filter(ModelVersion.version == self._engine.version).first()
        metrics_str = json.dumps(self._metrics.get("metrics", {}))
        artifact_path = str(artifacts_dir / f"model_{self._engine.version}.joblib")
        if existing:
            existing.sha256 = self._engine.sha256
            existing.artifact_path = artifact_path
            existing.metrics_json = metrics_str
            existing.is_active = True
        else:
            db.add(
                ModelVersion(
                    version=self._engine.version,
                    artifact_path=artifact_path,
                    sha256=self._engine.sha256,
                    metrics_json=metrics_str,
                    is_active=True,
                )
            )
        db.commit()

    def _run_with_cache(
        self,
        user_id: int | None,
        build_key: Any,
        compute: Any,
    ) -> Any:
        with self._lock:
            engine = self._engine
            if engine is None:
                raise RuntimeError("Recommender model is not loaded")
            ver = self._user_versions.get(user_id, 0) if user_id is not None else 0
            cache_key = build_key(ver)
            if cache_key is not None:
                cached = self._cache_get(cache_key)
                if cached is not None:
                    return cached

        result = compute(engine)

        if cache_key is not None:
            with self._lock:
                ver_ok = user_id is None or self._user_versions.get(user_id, 0) == ver
                if self._engine is engine and ver_ok:
                    self._cache_set(cache_key, result)
        return result

    def recommend_for_user(
        self,
        user_id: int,
        user_history: dict[int, float] | None = None,
        k: int = 20,
        genre: str | None = None,
        industry: str | None = None,
        language: str | None = None,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
        user_timestamps: dict[int, float] | None = None,
    ) -> list[RecommendationItem]:
        use_cache = user_id > 0 or not (user_history or preferred_genres or preferred_industries)
        return self._run_with_cache(
            user_id if use_cache else None,
            lambda ver: (
                (
                    user_id,
                    ver,
                    "me",
                    k,
                    genre or "",
                    industry or "",
                    language or "",
                    tuple(preferred_genres or ()),
                    tuple(preferred_industries or ()),
                )
                if use_cache
                else None
            ),
            lambda engine: engine.recommend_for_user(
                user_id=user_id,
                user_history=user_history,
                k=k,
                genre=genre,
                industry=industry,
                language=language,
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
                user_timestamps=user_timestamps,
            ),
        )

    def taste_profile(
        self,
        user_id: int = 0,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
    ) -> UserTasteProfile:
        use_cache = user_id > 0 or not (user_history or preferred_genres or preferred_industries)
        return self._run_with_cache(
            user_id if use_cache else None,
            lambda ver: (
                (
                    user_id,
                    ver,
                    "profile",
                    tuple(preferred_genres or ()),
                    tuple(preferred_industries or ()),
                )
                if use_cache
                else None
            ),
            lambda engine: engine.compute_taste_profile(
                user_history=user_history,
                user_timestamps=user_timestamps,
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
            ),
        )

    def because_you_rated_rows(
        self,
        user_id: int = 0,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        industry: str | None = None,
        limit_rows: int = 3,
        k: int = 16,
    ) -> list[tuple[int, float, list[RecommendationItem]]]:
        return self._run_with_cache(
            user_id if user_id > 0 else None,
            lambda ver: (user_id, ver, "because", industry or "", limit_rows, k) if user_id > 0 else None,
            lambda engine: engine.because_you_rated_rows(
                user_history=user_history,
                user_timestamps=user_timestamps,
                industry=industry,
                limit_rows=limit_rows,
                k=k,
            ),
        )

    def explain_movie_for_user(
        self,
        movie_id: int,
        user_id: int = 0,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
    ) -> list[dict[str, Any]]:
        if not user_history:
            return []
        return self._run_with_cache(
            user_id if user_id > 0 else None,
            lambda ver: (user_id, ver, "explain", movie_id) if user_id > 0 else None,
            lambda engine: engine.explain_movie_for_user(
                movie_id=movie_id,
                user_history=user_history,
                user_timestamps=user_timestamps,
            ),
        )

    def similar_movies(self, movie_id: int, k: int = 12) -> list[RecommendationItem]:
        return self._run_with_cache(
            0,
            lambda ver: (0, ver, "similar", movie_id, k),
            lambda engine: engine.similar_movies(movie_id=movie_id, k=k),
        )

    def recommend_by_genre(
        self,
        genre: str,
        k: int = 24,
        industry: str | None = None,
        user_id: int = 0,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
    ) -> list[RecommendationItem]:
        if user_id > 0 and (user_history or preferred_genres or preferred_industries):
            return self.recommend_for_user(
                user_id=user_id,
                user_history=user_history,
                k=k,
                genre=genre,
                industry=industry,
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
                user_timestamps=user_timestamps,
            )
        return self._run_with_cache(
            0,
            lambda ver: (0, ver, "genre_pop", genre.lower(), k, industry or ""),
            lambda engine: engine.recommend_by_genre(genre=genre, k=k, industry=industry),
        )

    def recommend_by_industry(
        self,
        industry: str,
        k: int = 24,
        user_id: int = 0,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
    ) -> list[RecommendationItem]:
        if user_id > 0 and (user_history or preferred_genres or preferred_industries):
            return self.recommend_for_user(
                user_id=user_id,
                user_history=user_history,
                k=k,
                industry=industry,
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
                user_timestamps=user_timestamps,
            )
        return self._run_with_cache(
            0,
            lambda ver: (0, ver, "ind_pop", industry.lower(), k),
            lambda engine: engine.recommend_by_industry(industry=industry, k=k),
        )

    def recommend_superheroes(
        self,
        k: int = 100,
        industry: str | None = None,
        user_id: int = 0,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
    ) -> list[RecommendationItem]:
        use_cache = user_id > 0 or not (user_history or preferred_genres or preferred_industries)
        return self._run_with_cache(
            user_id if use_cache else None,
            lambda ver: (
                (
                    user_id,
                    ver,
                    "superheroes",
                    k,
                    industry or "",
                    tuple(preferred_genres or ()),
                    tuple(preferred_industries or ()),
                )
                if use_cache
                else None
            ),
            lambda engine: engine.recommend_superheroes(
                user_id=user_id,
                user_history=user_history,
                k=k,
                industry=industry,
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
                user_timestamps=user_timestamps,
            ),
        )

    def get_cached_trending_ids(self, key: str) -> list[int] | None:
        entry = self._trending_cache.get(key)
        if not entry:
            return None
        ts, ids = entry
        if time.monotonic() - ts > self._cache_ttl_seconds:
            return None
        return ids

    def set_cached_trending_ids(self, key: str, ids: list[int]) -> None:
        self._trending_cache[key] = (time.monotonic(), ids)

    def invalidate_user_cache(self, user_id: int) -> None:
        """Bump this user's ratings version, drop their stale entries, and clear trending cache."""
        with self._lock:
            self._user_versions[user_id] = self._user_versions.get(user_id, 0) + 1
            stale = [k for k in self._user_rec_cache if k and k[0] == user_id]
            for k in stale:
                self._user_rec_cache.pop(k, None)
            self._trending_cache.clear()

    def _bind_summary_map(self, db: Session) -> tuple[int, dict[int, MovieSummary]]:
        bind_key = id(db.get_bind())
        bind_map = self._movie_caches.get(bind_key)
        if bind_map is None:
            bind_map = {}
            self._movie_caches[bind_key] = bind_map
            while len(self._movie_caches) > _MAX_BIND_CACHES:
                old_key, _ = self._movie_caches.popitem(last=False)
                self._movie_full_loaded.discard(old_key)
                self._genre_caches.pop(old_key, None)
        else:
            self._movie_caches.move_to_end(bind_key)
        return bind_key, bind_map

    def get_movie_summaries(self, movie_ids: list[int], db: Session) -> dict[int, MovieSummary]:
        unique_ids = list(dict.fromkeys(int(m) for m in movie_ids))
        if not unique_ids:
            return {}
        with self._lock:
            _bind_key, bind_map = self._bind_summary_map(db)
            missing = [mid for mid in unique_ids if mid not in bind_map]
            cached = {mid: bind_map[mid] for mid in unique_ids if mid in bind_map}

        if missing:
            rows = db.execute(select(*SUMMARY_COLUMNS).where(Movie.id.in_(missing))).all()
            fetched = {int(r.id): build_movie_summary(r) for r in rows}
            if fetched:
                with self._lock:
                    _bk, current_map = self._bind_summary_map(db)
                    current_map.update(fetched)
            cached.update(fetched)
        return cached

    def update_movie_summary(self, db: Session, movie: Movie) -> None:
        summary = build_movie_summary(movie)
        with self._lock:
            _bk, bind_map = self._bind_summary_map(db)
            bind_map[summary.id] = summary

    def get_title_index(self, db: Session) -> list[tuple[int, str, int]]:
        bind_key = id(db.get_bind())
        with self._lock:
            if bind_key in self._movie_full_loaded and bind_key in self._movie_caches:
                return [(m.id, m.title, m.rating_count) for m in self._movie_caches[bind_key].values()]
        rows = db.execute(select(Movie.id, Movie.title, Movie.rating_count)).all()
        return [(int(mid), str(title), int(rcount or 0)) for mid, title, rcount in rows]

    def get_cached_genres(self, db: Session) -> list[GenreOut]:
        bind_key = id(db.get_bind())
        with self._lock:
            cached = self._genre_caches.get(bind_key)
            if cached is not None:
                self._genre_caches.move_to_end(bind_key)
                return cached
        rows = db.execute(
            select(Genre.id, Genre.name, Genre.slug, func.count(MovieGenre.movie_id))
            .outerjoin(MovieGenre, Genre.id == MovieGenre.genre_id)
            .group_by(Genre.id)
            .order_by(desc(func.count(MovieGenre.movie_id)), Genre.name)
        ).all()
        genres = [GenreOut(id=int(r[0]), name=str(r[1]), slug=str(r[2]), movie_count=int(r[3])) for r in rows]
        if genres:
            with self._lock:
                self._genre_caches[bind_key] = genres
                while len(self._genre_caches) > _MAX_BIND_CACHES:
                    self._genre_caches.popitem(last=False)
        return genres

    def warm_catalogue_cache(self, db: Session) -> None:
        """Preload compact MovieSummary rows, genres, and public shelves at server startup."""
        rows = db.execute(select(*SUMMARY_COLUMNS)).all()
        if not rows:
            return
        summaries = {int(r.id): build_movie_summary(r) for r in rows}
        with self._lock:
            bind_key, bind_map = self._bind_summary_map(db)
            bind_map.update(summaries)
            self._movie_full_loaded.add(bind_key)
        self.get_cached_genres(db)
        if self._engine is not None:
            for ind in ("hollywood", "bollywood", "tollywood"):
                self.recommend_by_industry(ind, k=16)
            self.recommend_by_genre("Sci-Fi", k=16)
            self.recommend_superheroes(k=100)
        logger.info("Warmed in-memory catalogue cache (%d movies)", len(summaries))

    def invalidate_cache(self) -> None:
        with self._lock:
            self._trending_cache.clear()
            self._user_rec_cache.clear()
            self._movie_caches.clear()
            self._movie_full_loaded.clear()
            self._genre_caches.clear()


recommender_service = RecommenderService()
