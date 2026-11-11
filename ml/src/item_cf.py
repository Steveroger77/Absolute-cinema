"""Item-Based Collaborative Filtering on sparse mean-centered CSR ratings with co-rating shrinkage."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.metrics.pairwise import cosine_similarity

from ml.src.matrix import SparseMatrixBundle


def _top_k_per_row_csr(mat: sparse.csr_matrix, top_k: int) -> sparse.csr_matrix:
    """Keep only top_k positive entries per row (excluding diagonal) in a sparse CSR matrix."""
    n_rows, n_cols = mat.shape
    rows_out: list[np.ndarray] = []
    cols_out: list[np.ndarray] = []
    data_out: list[np.ndarray] = []

    for r in range(n_rows):
        start, end = mat.indptr[r], mat.indptr[r + 1]
        c_idx = mat.indices[start:end]
        vals = mat.data[start:end]
        mask = (c_idx != r) & (vals > 0.0)
        c_idx = c_idx[mask]
        vals = vals[mask]
        if len(vals) == 0:
            continue
        if len(vals) > top_k:
            keep = np.argpartition(vals, -top_k)[-top_k:]
            c_idx = c_idx[keep]
            vals = vals[keep]
        order = np.argsort(-vals)
        rows_out.append(np.full(len(vals), r, dtype=np.int32))
        cols_out.append(c_idx[order].astype(np.int32))
        data_out.append(vals[order].astype(np.float32))

    if not rows_out:
        return sparse.csr_matrix((n_rows, n_cols), dtype=np.float32)

    return sparse.csr_matrix(
        (np.concatenate(data_out), (np.concatenate(rows_out), np.concatenate(cols_out))),
        shape=(n_rows, n_cols),
        dtype=np.float32,
    )


@dataclass
class ItemBasedCF:
    """Sparse Item-Based Collaborative Filtering model."""

    top_n: int = 50
    shrinkage: float = 15.0
    min_item_ratings: int = 5
    sim_matrix: sparse.csr_matrix | None = None
    bundle: SparseMatrixBundle | None = None

    def fit(self, bundle: SparseMatrixBundle) -> ItemBasedCF:
        """Compute shrunk item-item cosine similarity from training CSR matrix."""
        self.bundle = bundle
        # Adjusted cosine: item vectors in user-centered space -> (n_items x n_users)
        item_vecs = bundle.user_centered.T.tocsr()
        raw_sim = cosine_similarity(item_vecs, dense_output=False).tocsr().astype(np.float32)

        # Sparse co-rating counts: B^T * B over observed entries
        binary = bundle.matrix.copy()
        binary.data = np.ones_like(binary.data, dtype=np.float32)
        co_counts = (binary.T @ binary).tocsr()

        # Apply shrinkage n_ij / (n_ij + beta) only at nonzero similarity positions
        shrunk = raw_sim.copy()
        if shrunk.nnz > 0:
            rows, cols = shrunk.nonzero()
            co_vals = np.asarray(co_counts[rows, cols]).ravel()
            weights = co_vals / (co_vals + self.shrinkage)
            shrunk.data = (shrunk.data * weights).astype(np.float32)

        # Symmetrize before top-k truncation? Keep raw symmetric shrunk similarity, then prune per row
        self.sim_matrix = _top_k_per_row_csr(shrunk, self.top_n)
        return self

    def predict_score(
        self,
        user_id: int,
        movie_id: int,
        user_history: dict[int, float] | None = None,
    ) -> float:
        """Predict rating for (user_id, movie_id) using weighted neighbor deviations."""
        assert self.bundle is not None and self.sim_matrix is not None
        if movie_id not in self.bundle.movie_to_idx:
            return self.bundle.global_mean
        i_idx = self.bundle.movie_to_idx[movie_id]
        item_baseline = float(self.bundle.item_means[i_idx])

        rated_map = self._resolve_user_history(user_id, user_history)
        if not rated_map:
            return item_baseline

        u_idx = self.bundle.user_to_idx.get(user_id)
        u_mean = (
            float(self.bundle.user_means[u_idx])
            if u_idx is not None
            else float(np.mean(list(rated_map.values())))
        )

        start, end = self.sim_matrix.indptr[i_idx], self.sim_matrix.indptr[i_idx + 1]
        nbr_indices = self.sim_matrix.indices[start:end]
        nbr_sims = self.sim_matrix.data[start:end]

        num = 0.0
        den = 0.0
        for j_idx, sim in zip(nbr_indices, nbr_sims, strict=False):
            j_mid = int(self.bundle.idx_to_movie[j_idx])
            if j_mid in rated_map:
                j_base = float(self.bundle.item_means[j_idx])
                num += float(sim) * (rated_map[j_mid] - j_base)
                den += abs(float(sim))

        if den <= 1e-8:
            # Blend user bias and item baseline when no similar neighbors rated
            return float(np.clip(0.5 * item_baseline + 0.5 * u_mean, 0.5, 5.0))
        pred = item_baseline + (num / den)
        return float(np.clip(pred, 0.5, 5.0))

    def score_all_for_user(
        self,
        user_id: int,
        user_history: dict[int, float] | None = None,
        rating_weights: dict[int, float] | None = None,
    ) -> tuple[np.ndarray, dict[int, list[tuple[int, float]]]]:
        """
        Vectorized scoring of ALL catalogue items for a user via sparse similarity lookup.

        Returns (scores_array_of_shape_n_items, top_explanations_by_movie_id).
        """
        assert self.bundle is not None and self.sim_matrix is not None
        rated_map = self._resolve_user_history(user_id, user_history)
        n_items = len(self.bundle.idx_to_movie)
        if not rated_map:
            return self.bundle.item_means.copy(), {}

        r_vals = list(rated_map.values())
        w_map = rating_weights or {}
        if w_map:
            w_sum = sum(float(w_map.get(mid, 1.0)) for mid in rated_map)
            u_mean = sum(float(r) * float(w_map.get(mid, 1.0)) for mid, r in rated_map.items()) / max(
                1e-6, w_sum
            )
        else:
            u_mean = float(np.mean(r_vals))
        spread = (max(r_vals) - min(r_vals)) if r_vals else 0.0
        # Center harsh/generous live raters softly around their own baseline when spread exists
        u_shift = (
            0.60 * (u_mean - float(self.bundle.global_mean))
            if user_history is not None and spread >= 0.35
            else 0.0
        )

        # Build sparse 1 x n_items weighted deviation vector for this user
        cols: list[int] = []
        devs: list[float] = []
        abs_weights: list[float] = []
        for mid, rating in rated_map.items():
            j_idx = self.bundle.movie_to_idx.get(mid)
            if j_idx is not None:
                rw = max(0.25, float(w_map.get(mid, 1.0)))
                cols.append(j_idx)
                devs.append(rw * ((float(rating) - u_shift) - float(self.bundle.item_means[j_idx])))
                abs_weights.append(rw)

        if not cols:
            return self.bundle.item_means.copy(), {}

        dev_vec = sparse.csr_matrix(
            (
                np.array(devs, dtype=np.float32),
                (np.zeros(len(cols), dtype=np.int32), np.array(cols, dtype=np.int32)),
            ),
            shape=(1, n_items),
        )
        ind_vec = sparse.csr_matrix(
            (
                np.array(abs_weights, dtype=np.float32),
                (np.zeros(len(cols), dtype=np.int32), np.array(cols, dtype=np.int32)),
            ),
            shape=(1, n_items),
        )

        # sim_matrix is (n_items, n_items) where row i has top neighbors j
        num = (self.sim_matrix @ dev_vec.T).toarray().ravel()
        den = (self.sim_matrix @ ind_vec.T).toarray().ravel()

        scores = self.bundle.item_bayesian_means.copy()
        valid = den > 1e-8
        # Blend neighbor deviation with Bayesian prior using shrinkage on similarity support
        # Keep raw_pred anchored on item_bayesian_means (do not demote harsh raters below ~valid)
        conf = den / (den + 0.35)
        raw_pred = self.bundle.item_bayesian_means[valid] + (num[valid] / np.maximum(den[valid], 1e-8))
        scores[valid] = np.clip(
            conf[valid] * raw_pred + (1.0 - conf[valid]) * self.bundle.item_bayesian_means[valid],
            0.5,
            5.0,
        )
        # Keep items with zero co-rated CF support cleanly below matched neighbor recommendations
        scores[~valid] = np.clip(
            0.55 * self.bundle.item_bayesian_means[~valid] + 0.45 * float(self.bundle.global_mean) - 0.35,
            0.5,
            5.0,
        )
        # Mild log-popularity tie-breaker while keeping long-tail discoverability
        pop_lift = 0.08 * (
            np.log1p(self.bundle.item_counts) / max(1.0, float(np.log1p(self.bundle.item_counts.max())))
        )
        scores = np.clip(scores + pop_lift, 0.5, 5.0)

        # Build fast explanation map favoring genuinely positively rated anchors
        like_floor = min(3.5, 0.5 * u_mean + 0.5 * 2.5)
        explanations: dict[int, list[tuple[int, float]]] = {}
        rated_idx_set = set(cols)
        for i_idx in np.where(valid)[0]:
            s, e = self.sim_matrix.indptr[i_idx], self.sim_matrix.indptr[i_idx + 1]
            nbrs = self.sim_matrix.indices[s:e]
            sims = self.sim_matrix.data[s:e]
            contribs: list[tuple[int, float]] = []
            for j_idx, sim in zip(nbrs, sims, strict=False):
                if int(j_idx) in rated_idx_set:
                    j_mid = int(self.bundle.idx_to_movie[j_idx])
                    r_val = rated_map[j_mid]
                    if r_val < like_floor:
                        continue
                    rw = max(0.25, float(w_map.get(j_mid, 1.0)))
                    weight = float(sim) * rw * max(0.2, r_val - (like_floor - 0.5))
                    contribs.append((j_mid, weight))
            if contribs:
                contribs.sort(key=lambda x: x[1], reverse=True)
                explanations[int(self.bundle.idx_to_movie[i_idx])] = contribs[:3]

        return scores, explanations

    def _resolve_user_history(self, user_id: int, user_history: dict[int, float] | None) -> dict[int, float]:
        if user_history is not None:
            return user_history
        assert self.bundle is not None
        u_idx = self.bundle.user_to_idx.get(user_id)
        if u_idx is None:
            return {}
        s, e = self.bundle.matrix.indptr[u_idx], self.bundle.matrix.indptr[u_idx + 1]
        return {
            int(self.bundle.idx_to_movie[j]): float(r)
            for j, r in zip(self.bundle.matrix.indices[s:e], self.bundle.matrix.data[s:e], strict=False)
        }
