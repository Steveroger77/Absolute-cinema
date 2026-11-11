"""User-Based Collaborative Filtering + Hybrid Item/User CF blender."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.metrics.pairwise import cosine_similarity

from ml.src.item_cf import ItemBasedCF, _top_k_per_row_csr
from ml.src.matrix import SparseMatrixBundle


@dataclass
class UserBasedCF:
    """Sparse User-Based Collaborative Filtering model with co-rating shrinkage."""

    top_m: int = 40
    shrinkage: float = 12.0
    sim_matrix: sparse.csr_matrix | None = None
    bundle: SparseMatrixBundle | None = None

    def fit(self, bundle: SparseMatrixBundle) -> UserBasedCF:
        """Compute shrunk user-user cosine similarity on sparse user-centered ratings."""
        self.bundle = bundle
        raw_sim = cosine_similarity(bundle.user_centered, dense_output=False).tocsr().astype(np.float32)

        binary = bundle.matrix.copy()
        binary.data = np.ones_like(binary.data, dtype=np.float32)
        co_counts = (binary @ binary.T).tocsr()

        shrunk = raw_sim.copy()
        if shrunk.nnz > 0:
            rows, cols = shrunk.nonzero()
            co_vals = np.asarray(co_counts[rows, cols]).ravel()
            weights = co_vals / (co_vals + self.shrinkage)
            shrunk.data = (shrunk.data * weights).astype(np.float32)

        self.sim_matrix = _top_k_per_row_csr(shrunk, self.top_m)
        return self

    def predict_score(
        self,
        user_id: int,
        movie_id: int,
        user_history: dict[int, float] | None = None,
    ) -> float:
        """Predict rating for (user_id, movie_id) from top similar training users."""
        assert self.bundle is not None and self.sim_matrix is not None
        i_idx = self.bundle.movie_to_idx.get(movie_id)
        if i_idx is None:
            return self.bundle.global_mean

        u_idx = self.bundle.user_to_idx.get(user_id)
        if u_idx is not None and user_history is None:
            u_mean = float(self.bundle.user_means[u_idx])
            s, e = self.sim_matrix.indptr[u_idx], self.sim_matrix.indptr[u_idx + 1]
            nbr_users = self.sim_matrix.indices[s:e]
            nbr_sims = self.sim_matrix.data[s:e]
        else:
            # Dynamic new/updated user cosine similarity against training users
            rated_map = user_history or {}
            if not rated_map:
                return float(self.bundle.item_means[i_idx])
            u_mean = float(np.mean(list(rated_map.values())))
            nbr_users, nbr_sims = self._dynamic_similar_users(rated_map, u_mean)

        num = 0.0
        den = 0.0
        R = self.bundle.user_centered
        for v_idx, sim in zip(nbr_users, nbr_sims, strict=False):
            # Look up user v's centered rating on item i
            row_start, row_end = R.indptr[v_idx], R.indptr[v_idx + 1]
            cols = R.indices[row_start:row_end]
            pos = np.searchsorted(cols, i_idx)
            if pos < len(cols) and cols[pos] == i_idx:
                dev = float(R.data[row_start + pos])
                num += float(sim) * dev
                den += abs(float(sim))

        if den <= 1e-8:
            return float(np.clip(0.5 * u_mean + 0.5 * float(self.bundle.item_means[i_idx]), 0.5, 5.0))
        return float(np.clip(u_mean + num / den, 0.5, 5.0))

    def score_all_for_user(
        self,
        user_id: int,
        user_history: dict[int, float] | None = None,
        rating_weights: dict[int, float] | None = None,
    ) -> np.ndarray:
        """Score all items for a user using sparse neighbor matrix multiplication."""
        assert self.bundle is not None and self.sim_matrix is not None
        u_idx = self.bundle.user_to_idx.get(user_id)

        if u_idx is not None and user_history is None:
            u_mean = float(self.bundle.user_means[u_idx])
            s, e = self.sim_matrix.indptr[u_idx], self.sim_matrix.indptr[u_idx + 1]
            nbr_users = self.sim_matrix.indices[s:e]
            nbr_sims = self.sim_matrix.data[s:e]
        else:
            rated_map = user_history or {}
            if not rated_map:
                return self.bundle.item_means.copy()
            w_map = rating_weights or {}
            if w_map:
                w_sum = sum(float(w_map.get(mid, 1.0)) for mid in rated_map)
                u_mean = sum(float(r) * float(w_map.get(mid, 1.0)) for mid, r in rated_map.items()) / max(
                    1e-6, w_sum
                )
            else:
                u_mean = float(np.mean(list(rated_map.values())))
            nbr_users, nbr_sims = self._dynamic_similar_users(
                rated_map, u_mean, rating_weights=rating_weights
            )

        if len(nbr_users) == 0:
            return np.clip(
                0.55 * self.bundle.item_bayesian_means + 0.45 * float(self.bundle.global_mean) - 0.35,
                0.5,
                5.0,
            )

        sim_row = sparse.csr_matrix(
            (
                nbr_sims.astype(np.float32),
                (np.zeros(len(nbr_users), dtype=np.int32), nbr_users.astype(np.int32)),
            ),
            shape=(1, len(self.bundle.idx_to_user)),
        )
        binary_R = self.bundle.matrix.copy()
        binary_R.data = np.ones_like(binary_R.data, dtype=np.float32)

        num = (sim_row @ self.bundle.user_centered).toarray().ravel()
        den = (sim_row @ binary_R).toarray().ravel()

        scores = np.clip(
            0.55 * self.bundle.item_bayesian_means + 0.45 * float(self.bundle.global_mean) - 0.35,
            0.5,
            5.0,
        ).astype(np.float32)
        valid = den > 1e-8
        conf = den[valid] / (den[valid] + 0.5)
        # Anchor live user_history on item_bayesian_means + neighbor dev for harsh/generous raters
        anchor = self.bundle.item_bayesian_means[valid] if user_history is not None else u_mean
        raw_pred = anchor + (num[valid] / den[valid])
        scores[valid] = np.clip(
            conf * raw_pred + (1.0 - conf) * self.bundle.item_bayesian_means[valid],
            0.5,
            5.0,
        )
        pop_lift = 0.08 * (
            np.log1p(self.bundle.item_counts) / max(1.0, float(np.log1p(self.bundle.item_counts.max())))
        )
        return np.clip(scores + pop_lift, 0.5, 5.0)

    def _dynamic_similar_users(
        self,
        rated_map: dict[int, float],
        u_mean: float,
        rating_weights: dict[int, float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        assert self.bundle is not None
        r_vals = list(rated_map.values())
        spread = (max(r_vals) - min(r_vals)) if r_vals else 0.0
        w_map = rating_weights or {}

        cols: list[int] = []
        vals: list[float] = []
        for mid, rating in rated_map.items():
            j_idx = self.bundle.movie_to_idx.get(mid)
            if j_idx is not None:
                rw = max(0.25, float(w_map.get(mid, 1.0)))
                # When all user ratings are equal (e.g., all 5.0), center against global/item baseline
                center = (
                    u_mean
                    if spread >= 0.25
                    else 0.5 * (float(self.bundle.item_means[j_idx]) + float(self.bundle.global_mean))
                )
                cols.append(j_idx)
                vals.append(rw * (float(rating) - center))
        if not cols:
            return np.array([], dtype=np.int32), np.array([], dtype=np.float32)

        n_items = len(self.bundle.idx_to_movie)
        u_vec = sparse.csr_matrix(
            (
                np.array(vals, dtype=np.float32),
                (np.zeros(len(cols), dtype=np.int32), np.array(cols, dtype=np.int32)),
            ),
            shape=(1, n_items),
        )
        sims = cosine_similarity(u_vec, self.bundle.user_centered, dense_output=True).ravel()
        bin_u = sparse.csr_matrix(
            (
                np.ones(len(cols), dtype=np.float32),
                (np.zeros(len(cols), dtype=np.int32), np.array(cols, dtype=np.int32)),
            ),
            shape=(1, n_items),
        )
        bin_R = self.bundle.matrix.copy()
        bin_R.data = np.ones_like(bin_R.data, dtype=np.float32)
        co = (bin_u @ bin_R.T).toarray().ravel()
        shrunk = sims * (co / (co + self.shrinkage))
        pos_idx = np.where(shrunk > 0.0)[0]
        if len(pos_idx) == 0:
            return np.array([], dtype=np.int32), np.array([], dtype=np.float32)
        if len(pos_idx) > self.top_m:
            keep = np.argpartition(shrunk[pos_idx], -self.top_m)[-self.top_m :]
            pos_idx = pos_idx[keep]
        order = np.argsort(-shrunk[pos_idx])
        pos_idx = pos_idx[order]
        return pos_idx.astype(np.int32), shrunk[pos_idx].astype(np.float32)


@dataclass
class HybridCF:
    """Blended Item-CF + User-CF scorer: hybrid = alpha * item + (1 - alpha) * user."""

    item_cf: ItemBasedCF
    user_cf: UserBasedCF
    alpha: float = 0.65

    def predict_score(
        self,
        user_id: int,
        movie_id: int,
        user_history: dict[int, float] | None = None,
    ) -> float:
        i_score = self.item_cf.predict_score(user_id, movie_id, user_history=user_history)
        u_score = self.user_cf.predict_score(user_id, movie_id, user_history=user_history)
        return float(np.clip(self.alpha * i_score + (1.0 - self.alpha) * u_score, 0.5, 5.0))

    def score_all_for_user(
        self,
        user_id: int,
        user_history: dict[int, float] | None = None,
        rating_weights: dict[int, float] | None = None,
    ) -> tuple[np.ndarray, dict[int, list[tuple[int, float]]]]:
        i_scores, explanations = self.item_cf.score_all_for_user(
            user_id, user_history=user_history, rating_weights=rating_weights
        )
        u_scores = self.user_cf.score_all_for_user(
            user_id, user_history=user_history, rating_weights=rating_weights
        )
        blended = np.clip(self.alpha * i_scores + (1.0 - self.alpha) * u_scores, 0.5, 5.0)
        return blended, explanations
