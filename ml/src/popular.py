"""Bayesian-weighted popularity recommender for cold-start users and trending shelves."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BayesianPopularityModel:
    """IMDB-style Bayesian weighted average: (v/(v+m))*R + (m/(v+m))*C."""

    global_mean: float = 3.5
    min_votes_m: float = 15.0
    scores_by_movie: dict[int, float] | None = None
    ranked_movie_ids: list[int] | None = None

    def fit(self, movies_df: pd.DataFrame, train_ratings_df: pd.DataFrame) -> BayesianPopularityModel:
        """Fit popularity scores strictly on training interactions."""
        agg = train_ratings_df.groupby("movie_id")["rating"].agg(["count", "mean"]).reset_index()
        if agg.empty:
            self.global_mean = 3.5
            self.min_votes_m = 10.0
            self.scores_by_movie = {int(m): 3.5 for m in movies_df["movie_id"]}
            self.ranked_movie_ids = [int(m) for m in movies_df["movie_id"]]
            return self

        self.global_mean = float(train_ratings_df["rating"].mean())
        self.min_votes_m = float(max(8.0, np.percentile(agg["count"].to_numpy(), 65)))

        count_map = dict(zip(agg["movie_id"].astype(int), agg["count"].astype(float), strict=False))
        mean_map = dict(zip(agg["movie_id"].astype(int), agg["mean"].astype(float), strict=False))

        scores: dict[int, float] = {}
        for mid in movies_df["movie_id"].astype(int):
            v = count_map.get(mid, 0.0)
            R = mean_map.get(mid, self.global_mean)
            m = self.min_votes_m
            C = self.global_mean
            # Small log-popularity tie-breaker while keeping bounded [0.5, 5.0]
            bayesian = (v / (v + m)) * R + (m / (v + m)) * C
            scores[mid] = float(np.clip(bayesian + 0.04 * np.log1p(v), 0.5, 5.0))

        self.scores_by_movie = scores
        self.ranked_movie_ids = [mid for mid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]
        return self

    def recommend(
        self,
        movies_df: pd.DataFrame,
        k: int = 20,
        preferred_genres: list[str] | None = None,
        preferred_industries: list[str] | None = None,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Return top-k popular items optionally steered by onboarding genres/industries."""
        assert self.scores_by_movie is not None
        exclude = exclude_ids or set()
        pref_g = {g.lower() for g in (preferred_genres or [])}
        pref_i = {i.lower() for i in (preferred_industries or [])}

        scored: list[tuple[int, float]] = []
        for _, row in movies_df.iterrows():
            mid = int(row["movie_id"])
            if mid in exclude:
                continue
            base = self.scores_by_movie.get(mid, self.global_mean)
            boost = 0.0
            if pref_g:
                row_g = {g.strip().lower() for g in str(row.get("genres") or "").split("|") if g.strip()}
                overlap = len(pref_g.intersection(row_g))
                boost += 0.28 * min(3, overlap)
            if pref_i and str(row.get("industry") or "").lower() in pref_i:
                boost += 0.35
            scored.append((mid, round(base + boost, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
