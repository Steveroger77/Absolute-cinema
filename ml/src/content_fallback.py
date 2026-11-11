"""TF-IDF content-based fallback for cold-start items (<5 ratings) and similar-movie queries."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class ContentFallbackModel:
    """TF-IDF cosine model over genres, industry, language, director, cast, and overview."""

    vectorizer: TfidfVectorizer | None = None
    tfidf_matrix: sparse.csr_matrix | None = None
    movie_to_idx: dict[int, int] | None = None
    idx_to_movie: np.ndarray | None = None

    def fit(self, movies_df: pd.DataFrame) -> ContentFallbackModel:
        """Fit TF-IDF representation strictly on catalogue metadata."""
        df = movies_df.sort_values("movie_id").reset_index(drop=True)
        movie_ids = df["movie_id"].to_numpy(dtype=np.int64)
        self.idx_to_movie = movie_ids
        self.movie_to_idx = {int(m): i for i, m in enumerate(movie_ids)}

        docs: list[str] = []
        for _, row in df.iterrows():
            genres = str(row.get("genres") or "").replace("|", " ")
            # Repeat structured genre/industry/language tokens to anchor content signal
            industry = str(row.get("industry") or "")
            lang = str(row.get("language") or "")
            director = str(row.get("director") or "")
            cast = str(row.get("cast") or "")
            overview = str(row.get("overview") or "")
            doc = f"{genres} {genres} {industry} {industry} lang_{lang} {director} {cast} {overview}"
            docs.append(doc)

        self.vectorizer = TfidfVectorizer(
            max_features=8000,
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
        )
        self.tfidf_matrix = self.vectorizer.fit_transform(docs).tocsr().astype(np.float32)
        return self

    def similar_movies(
        self,
        movie_id: int,
        k: int = 15,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Return top-k content-similar (movie_id, similarity_score) pairs."""
        assert (
            self.tfidf_matrix is not None and self.movie_to_idx is not None and self.idx_to_movie is not None
        )
        idx = self.movie_to_idx.get(movie_id)
        if idx is None:
            return []
        sims = cosine_similarity(self.tfidf_matrix[idx], self.tfidf_matrix, dense_output=True).ravel()
        sims[idx] = -1.0
        if exclude_ids:
            for ex_mid in exclude_ids:
                ex_idx = self.movie_to_idx.get(ex_mid)
                if ex_idx is not None:
                    sims[ex_idx] = -1.0

        top_k = min(k, len(sims) - 1)
        if top_k <= 0:
            return []
        cand = np.argpartition(sims, -top_k)[-top_k:]
        cand = cand[np.argsort(-sims[cand])]
        return [(int(self.idx_to_movie[i]), float(sims[i])) for i in cand if sims[i] > 0.0]

    def score_all_for_history(
        self,
        user_history: dict[int, float],
        rating_weights: dict[int, float] | None = None,
    ) -> np.ndarray:
        """Compute signed content affinity scores (mapped to [0.5, 5.0]) centered on user mean."""
        assert (
            self.tfidf_matrix is not None and self.movie_to_idx is not None and self.idx_to_movie is not None
        )
        n_items = len(self.idx_to_movie)
        if not user_history:
            return np.full(n_items, 3.2, dtype=np.float32)

        r_vals = list(user_history.values())
        w_map = rating_weights or {}
        if w_map:
            w_sum = sum(float(w_map.get(mid, 1.0)) for mid in user_history)
            u_mean = sum(float(r) * float(w_map.get(mid, 1.0)) for mid, r in user_history.items()) / max(
                1e-6, w_sum
            )
        else:
            u_mean = float(np.mean(r_vals))
        spread = (max(r_vals) - min(r_vals)) if r_vals else 0.0
        center = 0.65 * u_mean + 0.35 * 3.0 if spread >= 0.4 else 3.0

        indices: list[int] = []
        weights: list[float] = []
        for mid, rating in user_history.items():
            idx = self.movie_to_idx.get(mid)
            if idx is not None:
                rw = max(0.25, float(w_map.get(mid, 1.0)))
                # Negative centered weights actively push down disliked genres/themes
                w = rw * (float(rating) - center)
                indices.append(idx)
                weights.append(w)

        if not indices or all(abs(x) < 1e-6 for x in weights):
            return np.full(n_items, 3.2, dtype=np.float32)

        w_arr = np.array(weights, dtype=np.float32).reshape(1, -1)
        profile = w_arr @ self.tfidf_matrix[indices]
        if float(np.sum(np.asarray(profile) ** 2)) <= 1e-10:
            return np.full(n_items, 3.2, dtype=np.float32)
        sims = cosine_similarity(profile, self.tfidf_matrix, dense_output=True).ravel()
        return np.clip(3.0 + 1.9 * sims, 0.5, 5.0).astype(np.float32)
