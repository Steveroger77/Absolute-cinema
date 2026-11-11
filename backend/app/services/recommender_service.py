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

from sqlalchemy.orm import Session

# Ensure project root is importable for `ml.src.loader` without importing training logic
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.src.loader import RecommendationItem, RecommenderEngine, UserTasteProfile  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import ModelVersion  # noqa: E402

logger = logging.getLogger(__name__)

_MAX_USER_CACHE_ENTRIES = 512


class RecommenderService:
    """Thread-safe singleton holding the loaded RecommenderEngine artifact and isolated caches."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engine: RecommenderEngine | None = None
        self._metrics: dict[str, Any] = {}
        self._trending_cache: dict[str, tuple[float, list[int]]] = {}
        self._cache_ttl_seconds = 60.0
        # Per-user monotonically bumped version + bounded LRU cache strictly keyed by (user_id, version, ...)
        self._user_versions: dict[int, int] = {}
        self._user_rec_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()

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
            None,
            lambda _ver: None,
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

    def invalidate_cache(self) -> None:
        with self._lock:
            self._trending_cache.clear()
            self._user_rec_cache.clear()


recommender_service = RecommenderService()
