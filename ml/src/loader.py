"""Inference-only recommender loader used by the API serving layer (never refits models)."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

DEFAULT_GENRE_ORDER = [
    "Action",
    "Sci-Fi",
    "Drama",
    "Thriller",
    "Romance",
    "Comedy",
    "Mystery",
    "Horror",
    "Adventure",
    "Crime",
    "Fantasy",
    "Animation",
    "Family",
    "Musical",
    "War",
    "Western",
    "Documentary",
    "Film-Noir",
]

DEFAULT_INDUSTRY_ORDER = ["hollywood", "bollywood", "tollywood"]


@dataclass
class RecommendationItem:
    movie_id: int
    score: float
    source: str  # "hybrid_cf" | "content_fallback" | "popular_cold_start"
    reasons: list[dict[str, Any]]


@dataclass
class UserTasteProfile:
    genre_order: list[str]
    industry_order: list[str]
    genre_scores: dict[str, float]
    industry_scores: dict[str, float]
    language_scores: dict[str, float]
    anchor_movie_ids: list[int]
    rating_weights: dict[int, float]
    baseline: float


class RecommenderEngine:
    """Thread-safe in-memory inference wrapper around a trained model_vX.joblib artifact."""

    def __init__(self, artifact: dict[str, Any], version: str, sha256: str) -> None:
        self.version = version
        self.sha256 = sha256
        self.hybrid = artifact["hybrid"]
        self.item_cf = artifact["item_cf"]
        self.user_cf = artifact["user_cf"]
        self.content = artifact["content"]
        self.popular = artifact["popular"]
        self.alpha: float = float(artifact["alpha"])
        self.content_weight: float = float(artifact.get("content_weight", 0.22))
        self.cf_weight: float = float(artifact.get("cf_weight", max(0.5, 1.0 - self.content_weight)))
        self.taste_weight: float = float(artifact.get("taste_weight", 0.42))
        self.min_rating_count: int = int(artifact.get("min_rating_count", 5))
        self.catalogue: pd.DataFrame = artifact["catalogue"].copy()

        self.metadata_by_id: dict[int, dict[str, Any]] = {}
        self.genres_by_id: dict[int, tuple[str, ...]] = {}
        self.industry_by_id: dict[int, str] = {}
        self.language_by_id: dict[int, str] = {}
        catalogue_genres: set[str] = set()

        for _, row in self.catalogue.iterrows():
            mid = int(row["movie_id"])
            rec = row.to_dict()
            self.metadata_by_id[mid] = rec
            g_tuple = tuple(g.strip() for g in str(rec.get("genres") or "").split("|") if g.strip())
            self.genres_by_id[mid] = g_tuple
            for g in g_tuple:
                catalogue_genres.add(g)
            self.industry_by_id[mid] = str(rec.get("industry") or "").strip().lower()
            self.language_by_id[mid] = str(rec.get("language") or "").strip().lower()

        ordered_base = [g for g in DEFAULT_GENRE_ORDER if g in catalogue_genres]
        extras = sorted(g for g in catalogue_genres if g not in DEFAULT_GENRE_ORDER)
        self.available_genres: list[str] = ordered_base + extras
        self.bundle = self.item_cf.bundle

    @classmethod
    def load(cls, artifact_path: Path, version: str | None = None) -> RecommenderEngine:
        raw_bytes = artifact_path.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        artifact = joblib.load(artifact_path)
        ver = version or str(artifact.get("version", artifact_path.stem))
        return cls(artifact=artifact, version=ver, sha256=sha)

    @classmethod
    def load_latest(cls, artifacts_dir: Path) -> RecommenderEngine:
        manifest_path = artifacts_dir / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            model_file = artifacts_dir / manifest["artifact_filename"]
            return cls.load(model_file, version=manifest.get("version"))
        candidates = sorted(artifacts_dir.glob("model_v*.joblib"))
        if not candidates:
            raise FileNotFoundError(f"No model artifacts found in {artifacts_dir}")
        return cls.load(candidates[-1])

    def compute_recency_weights(
        self,
        user_history: dict[int, float],
        user_timestamps: dict[int, float] | None = None,
    ) -> dict[int, float]:
        """Assign mildly higher weight to more recent ratings using rank decay."""
        if not user_history:
            return {}
        if not user_timestamps:
            return {mid: 1.0 for mid in user_history}
        ordered = sorted(
            user_history.keys(),
            key=lambda mid: float(user_timestamps.get(mid, 0.0)),
            reverse=True,
        )
        return {mid: round(0.68 + 0.32 * math.exp(-rank / 8.0), 4) for rank, mid in enumerate(ordered)}

    def compute_taste_profile(
        self,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
    ) -> UserTasteProfile:
        """Build mean-centered, recency-weighted genre/industry/language affinity profile."""
        history = user_history or {}
        rw = self.compute_recency_weights(history, user_timestamps)
        pref_g = [g.strip() for g in (preferred_genres or []) if g.strip()]
        pref_i = [i.strip().lower() for i in (preferred_industries or []) if i.strip()]

        if history:
            vals = list(history.values())
            w_sum = sum(rw.get(mid, 1.0) for mid in history)
            u_mean = sum(float(r) * rw.get(mid, 1.0) for mid, r in history.items()) / max(1e-6, w_sum)
            spread = max(vals) - min(vals)
            baseline = 0.65 * u_mean + 0.35 * 3.0 if spread >= 0.4 else 3.0
        else:
            baseline = 3.0

        g_sum: dict[str, float] = {}
        g_cnt: dict[str, float] = {}
        i_sum: dict[str, float] = {}
        i_cnt: dict[str, float] = {}
        l_sum: dict[str, float] = {}
        l_cnt: dict[str, float] = {}

        for mid, rating in history.items():
            w = rw.get(mid, 1.0)
            delta = float(rating) - baseline
            genres = self.genres_by_id.get(mid, ())
            norm_g = 1.0 / max(1.0, math.sqrt(float(len(genres))))
            for g in genres:
                g_sum[g] = g_sum.get(g, 0.0) + w * delta * norm_g
                g_cnt[g] = g_cnt.get(g, 0.0) + w
            ind = self.industry_by_id.get(mid, "")
            if ind:
                i_sum[ind] = i_sum.get(ind, 0.0) + w * delta
                i_cnt[ind] = i_cnt.get(ind, 0.0) + w
            lang = self.language_by_id.get(mid, "")
            if lang:
                l_sum[lang] = l_sum.get(lang, 0.0) + w * delta
                l_cnt[lang] = l_cnt.get(lang, 0.0) + w

        cold_scale = max(0.0, 1.0 - (len(history) / 5.0))
        genre_scores: dict[str, float] = {}
        for g in self.available_genres:
            raw_g = g_sum.get(g, 0.0) / (g_cnt.get(g, 0.0) + 1.5)
            onb = 0.45 * cold_scale if g in pref_g else 0.0
            genre_scores[g] = float(np.clip(raw_g + onb, -1.5, 1.5))

        industry_scores: dict[str, float] = {}
        for ind in DEFAULT_INDUSTRY_ORDER:
            raw_i = i_sum.get(ind, 0.0) / (i_cnt.get(ind, 0.0) + 2.0)
            onb = 0.45 * cold_scale if ind in pref_i else 0.0
            industry_scores[ind] = float(np.clip(raw_i + onb, -1.5, 1.5))

        language_scores: dict[str, float] = {
            lang: float(np.clip(l_sum[lang] / (l_cnt[lang] + 2.0), -1.5, 1.5)) for lang in l_sum
        }

        default_g_idx = {g: idx for idx, g in enumerate(self.available_genres)}
        genre_order = sorted(
            self.available_genres,
            key=lambda g: (-round(genre_scores.get(g, 0.0), 4), default_g_idx.get(g, 999)),
        )
        default_i_idx = {ind: idx for idx, ind in enumerate(DEFAULT_INDUSTRY_ORDER)}
        industry_order = sorted(
            DEFAULT_INDUSTRY_ORDER,
            key=lambda ind: (-round(industry_scores.get(ind, 0.0), 4), default_i_idx.get(ind, 99)),
        )

        # Anchor films for "Because you rated X" (top 1..3 recent liked titles relative to baseline)
        like_cutoff = max(3.5, baseline - 0.1) if history else 3.5
        liked = [
            (mid, (float(r) - 2.5) * rw.get(mid, 1.0))
            for mid, r in history.items()
            if float(r) >= like_cutoff and mid in self.metadata_by_id
        ]
        liked.sort(
            key=lambda item: (item[1], float(user_timestamps.get(item[0], 0.0) if user_timestamps else 0.0)),
            reverse=True,
        )
        anchor_movie_ids = [mid for mid, _ in liked[:3]]

        return UserTasteProfile(
            genre_order=genre_order,
            industry_order=industry_order,
            genre_scores=genre_scores,
            industry_scores=industry_scores,
            language_scores=language_scores,
            anchor_movie_ids=anchor_movie_ids,
            rating_weights=rw,
            baseline=baseline,
        )

    def _taste_boost_for_movie(self, mid: int, profile: UserTasteProfile) -> float:
        genres = self.genres_by_id.get(mid, ())
        if genres:
            # Amplify strongly disliked genres so explicitly hated genres drop cleanly
            weighted_g = [
                profile.genre_scores.get(g, 0.0) * (1.45 if profile.genre_scores.get(g, 0.0) < -0.15 else 1.0)
                for g in genres
            ]
            g_score = sum(weighted_g) / float(len(genres))
        else:
            g_score = 0.0
        i_score = profile.industry_scores.get(self.industry_by_id.get(mid, ""), 0.0)
        l_score = profile.language_scores.get(self.language_by_id.get(mid, ""), 0.0)
        combined = 0.62 * g_score + 0.26 * i_score + 0.12 * l_score
        return float(np.clip(self.taste_weight * combined, -0.85, 0.75))

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
        """Generate top-K personalized (or cold-start) recommendations with item-based explanations."""
        history = user_history if user_history is not None else {}
        rated_ids = set(history.keys())

        # Zero-rating cold-start path: Bayesian popularity steered by onboarding choices
        if len(history) == 0:
            filtered_df = self._filter_catalogue(genre=genre, industry=industry, language=language)
            pop_recs = self.popular.recommend(
                filtered_df,
                k=k,
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
                exclude_ids=rated_ids,
            )
            reason_label = (
                "Matches your selected genres and industries"
                if (preferred_genres or preferred_industries)
                else "Critically acclaimed audience favorites"
            )
            return [
                RecommendationItem(
                    movie_id=mid,
                    score=float(sc),
                    source="popular_cold_start",
                    reasons=[{"type": "cold_start", "label": reason_label}],
                )
                for mid, sc in pop_recs
            ]

        profile = self.compute_taste_profile(
            user_history=history,
            user_timestamps=user_timestamps,
            preferred_genres=preferred_genres,
            preferred_industries=preferred_industries,
        )
        cf_scores, item_explanations = self.hybrid.score_all_for_user(
            user_id, user_history=history, rating_weights=profile.rating_weights
        )
        content_scores = self.content.score_all_for_history(history, rating_weights=profile.rating_weights)

        pop_scores: dict[int, float] = {}
        in_cold_transition = len(history) < 5
        if in_cold_transition:
            pop_list = self.popular.recommend(
                self.catalogue,
                k=len(self.catalogue),
                preferred_genres=preferred_genres,
                preferred_industries=preferred_industries,
                exclude_ids=rated_ids,
            )
            pop_scores = dict(pop_list)
            cf_transition = 0.45 + 0.55 * (len(history) / 5.0)
        else:
            cf_transition = 1.0

        movie_ids = self.bundle.idx_to_movie
        item_counts = self.bundle.item_counts

        genre_low = genre.strip().lower() if genre else None
        ind_low = industry.strip().lower() if industry else None
        lang_low = language.strip().lower() if language else None

        scored_entries: list[tuple[float, int, str]] = []
        for idx, mid_np in enumerate(movie_ids):
            mid = int(mid_np)
            if mid in rated_ids:
                continue
            meta = self.metadata_by_id.get(mid)
            if meta is None:
                continue
            if genre_low and genre_low not in str(meta.get("genres") or "").lower():
                continue
            if ind_low and self.industry_by_id.get(mid, "") != ind_low:
                continue
            if lang_low and self.language_by_id.get(mid, "") != lang_low:
                continue

            train_cnt = int(item_counts[idx])
            cf_val = float(cf_scores[idx])
            c_idx = self.content.movie_to_idx.get(mid)
            cont_val = float(content_scores[c_idx]) if c_idx is not None else 3.2
            taste_adj = self._taste_boost_for_movie(mid, profile)

            if train_cnt < self.min_rating_count:
                # Sparse/new movie: content affinity + taste alignment keeps cold titles discoverable
                personal = 0.72 * cont_val + 0.28 * cf_val + 0.85 * taste_adj
                src = "content_fallback"
            else:
                personal = (self.cf_weight * cf_val) + (self.content_weight * cont_val) + taste_adj
                src = "hybrid_cf"

            if in_cold_transition and mid in pop_scores:
                blended = cf_transition * personal + (1.0 - cf_transition) * pop_scores[mid]
            else:
                blended = personal

            scored_entries.append((float(np.clip(blended, 0.5, 5.0)), mid, src))

        scored_entries.sort(key=lambda c: c[0], reverse=True)
        top_entries = scored_entries[:k]

        results: list[RecommendationItem] = []
        for final_sc, mid, src in top_entries:
            if src == "content_fallback":
                reasons = self._content_reasons(mid, history, profile.baseline)
            else:
                exps = item_explanations.get(mid, [])
                if exps:
                    reasons = [
                        {
                            "type": "because_you_rated",
                            "movie_id": r_mid,
                            "title": self.metadata_by_id.get(r_mid, {}).get("title", f"Movie {r_mid}"),
                            "user_rating": history.get(r_mid),
                            "weight": round(float(w), 3),
                        }
                        for r_mid, w in exps[:3]
                    ]
                else:
                    reasons = self._content_reasons(mid, history, profile.baseline)

            results.append(
                RecommendationItem(
                    movie_id=mid,
                    score=round(final_sc, 4),
                    source=src,
                    reasons=reasons,
                )
            )
        return results

    def because_you_rated_rows(
        self,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
        industry: str | None = None,
        limit_rows: int = 3,
        k: int = 16,
    ) -> list[tuple[int, float, list[RecommendationItem]]]:
        """Return top 1..3 recently liked movies mapped to personalized nearest-neighbor picks."""
        history = user_history or {}
        if not history:
            return []

        profile = self.compute_taste_profile(user_history=history, user_timestamps=user_timestamps)
        rated_ids = set(history.keys())
        ind_low = industry.strip().lower() if industry else None

        rows: list[tuple[int, float, list[RecommendationItem]]] = []
        used_picks: set[int] = set()

        for anchor_mid in profile.anchor_movie_ids:
            if len(rows) >= limit_rows:
                break
            if ind_low and self.industry_by_id.get(anchor_mid, "") != ind_low:
                # Still include cross-industry anchor only if it yields valid matches in selected industry
                pass
            nbrs = self.similar_movies(anchor_mid, k=k * 3)
            anchor_title = self.metadata_by_id.get(anchor_mid, {}).get("title", f"Movie {anchor_mid}")
            anchor_rating = float(history[anchor_mid])

            filtered: list[RecommendationItem] = []
            for item in nbrs:
                if item.movie_id in rated_ids:
                    continue
                if ind_low and self.industry_by_id.get(item.movie_id, "") != ind_low:
                    continue
                taste_adj = self._taste_boost_for_movie(item.movie_id, profile) * 0.25
                repeat_penalty = 0.25 if item.movie_id in used_picks else 0.0
                rank_score = max(0.05, float(item.score) + taste_adj - repeat_penalty)
                filtered.append(
                    RecommendationItem(
                        movie_id=item.movie_id,
                        score=round(rank_score, 4),
                        source=item.source,
                        reasons=[
                            {
                                "type": "because_you_rated",
                                "movie_id": anchor_mid,
                                "title": anchor_title,
                                "user_rating": anchor_rating,
                                "weight": round(float(item.score), 3),
                            }
                        ],
                    )
                )

            filtered.sort(key=lambda x: x.score, reverse=True)
            picked = filtered[:k]
            if picked:
                for p in picked[:6]:
                    used_picks.add(p.movie_id)
                rows.append((anchor_mid, anchor_rating, picked))

        return rows

    def explain_movie_for_user(
        self,
        movie_id: int,
        user_history: dict[int, float] | None = None,
        user_timestamps: dict[int, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Return 1-line explanation of which 2-3 rated movies most drove this film's score."""
        history = user_history or {}
        if not history:
            return []
        profile = self.compute_taste_profile(user_history=history, user_timestamps=user_timestamps)
        like_cutoff = max(3.5, profile.baseline - 0.15)
        liked = {mid: r for mid, r in history.items() if mid != movie_id and float(r) >= like_cutoff}
        if not liked:
            return []

        sims = {it.movie_id: it.score for it in self.similar_movies(movie_id, k=60)}
        scored: list[tuple[int, float, float]] = []
        for r_mid, r_val in liked.items():
            sim_val = sims.get(r_mid, 0.0)
            if sim_val > 0.0:
                rw = profile.rating_weights.get(r_mid, 1.0)
                scored.append((r_mid, r_val, sim_val * rw * max(0.25, float(r_val) - 2.5)))

        if not scored:
            return self._content_reasons(movie_id, history, profile.baseline)

        scored.sort(key=lambda x: x[2], reverse=True)
        return [
            {
                "type": "because_you_rated",
                "movie_id": r_mid,
                "title": self.metadata_by_id.get(r_mid, {}).get("title", f"Movie {r_mid}"),
                "user_rating": r_val,
                "weight": round(float(sc), 3),
            }
            for r_mid, r_val, sc in scored[:3]
        ]

    def similar_movies(self, movie_id: int, k: int = 12) -> list[RecommendationItem]:
        """Blend item-CF similarity (when sufficient co-ratings exist) with TF-IDF content similarity."""
        content_sims = dict(self.content.similar_movies(movie_id, k=k * 3))
        cf_sims: dict[int, float] = {}
        i_idx = self.bundle.movie_to_idx.get(movie_id)
        if i_idx is not None and self.bundle.item_counts[i_idx] >= self.min_rating_count:
            s, e = self.item_cf.sim_matrix.indptr[i_idx], self.item_cf.sim_matrix.indptr[i_idx + 1]
            for j_idx, sim in zip(
                self.item_cf.sim_matrix.indices[s:e], self.item_cf.sim_matrix.data[s:e], strict=False
            ):
                cf_sims[int(self.bundle.idx_to_movie[j_idx])] = float(sim)

        all_cands = set(content_sims.keys()) | set(cf_sims.keys())
        all_cands.discard(movie_id)
        anchor_title = self.metadata_by_id.get(movie_id, {}).get("title", "this film")

        scored: list[RecommendationItem] = []
        for cand_mid in all_cands:
            c_sc = content_sims.get(cand_mid, 0.0)
            cf_sc = cf_sims.get(cand_mid, 0.0)
            blended = 0.65 * cf_sc + 0.35 * c_sc if cf_sims else c_sc
            scored.append(
                RecommendationItem(
                    movie_id=cand_mid,
                    score=round(float(blended), 4),
                    source="item_similarity" if cf_sc > 0 else "content_similarity",
                    reasons=[{"type": "similar_to", "movie_id": movie_id, "title": anchor_title}],
                )
            )
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:k]

    def recommend_by_genre(
        self, genre: str, k: int = 24, industry: str | None = None
    ) -> list[RecommendationItem]:
        """Return top-rated Bayesian-weighted titles for a genre (optionally narrowed by industry)."""
        filtered = self._filter_catalogue(genre=genre, industry=industry)
        recs = self.popular.recommend(filtered, k=k)
        return [
            RecommendationItem(
                movie_id=mid,
                score=float(sc),
                source="genre_popular",
                reasons=[{"type": "genre_highlight", "label": f"Top ranked in {genre}"}],
            )
            for mid, sc in recs
        ]

    def recommend_by_industry(self, industry: str, k: int = 24) -> list[RecommendationItem]:
        """Return top-rated Bayesian-weighted titles for an industry for guests."""
        filtered = self._filter_catalogue(industry=industry)
        recs = self.popular.recommend(filtered, k=k)
        return [
            RecommendationItem(
                movie_id=mid,
                score=float(sc),
                source="industry_popular",
                reasons=[{"type": "industry_highlight", "label": f"Top ranked in {industry.capitalize()}"}],
            )
            for mid, sc in recs
        ]

    def _filter_catalogue(
        self,
        genre: str | None = None,
        industry: str | None = None,
        language: str | None = None,
    ) -> pd.DataFrame:
        df = self.catalogue
        if genre:
            g = genre.strip().lower()
            df = df[df["genres"].fillna("").str.lower().str.contains(g, regex=False)]
        if industry:
            ind = industry.strip().lower()
            df = df[df["industry"].fillna("").str.lower() == ind]
        if language:
            lang = language.strip().lower()
            df = df[df["language"].fillna("").str.lower() == lang]
        return df

    def _content_reasons(
        self, target_mid: int, history: dict[int, float], baseline: float = 3.2
    ) -> list[dict[str, Any]]:
        like_cutoff = max(3.5, baseline - 0.1)
        liked = sorted(
            [(mid, r) for mid, r in history.items() if float(r) >= like_cutoff and mid != target_mid],
            key=lambda x: x[1],
            reverse=True,
        )[:15]
        if not liked:
            return [{"type": "content_match", "label": "Matches your taste profile"}]
        sims = self.content.similar_movies(target_mid, k=50)
        sim_map = dict(sims)
        best = [(mid, r, sim_map[mid]) for mid, r in liked if mid in sim_map]
        best.sort(key=lambda x: x[2] * x[1], reverse=True)
        if best:
            return [
                {
                    "type": "because_you_rated",
                    "movie_id": mid,
                    "title": self.metadata_by_id.get(mid, {}).get("title", f"Movie {mid}"),
                    "user_rating": r,
                    "weight": round(float(sc), 3),
                }
                for mid, r, sc in best[:3]
            ]
        return [{"type": "content_match", "label": "Shares genre and tone with your top films"}]
