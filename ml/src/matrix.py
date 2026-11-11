"""Sparse CSR user-item rating matrix construction and mean-centering utilities."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse


@dataclass
class SparseMatrixBundle:
    """Container holding CSR interaction matrix, index maps, and train-only statistics."""

    matrix: sparse.csr_matrix
    user_to_idx: dict[int, int]
    idx_to_user: np.ndarray
    movie_to_idx: dict[int, int]
    idx_to_movie: np.ndarray
    user_means: np.ndarray
    item_means: np.ndarray
    item_bayesian_means: np.ndarray
    item_counts: np.ndarray
    global_mean: float
    user_centered: sparse.csr_matrix
    item_centered: sparse.csr_matrix


def build_sparse_matrix(
    ratings_df: pd.DataFrame,
    movie_ids: list[int] | np.ndarray,
    user_ids: list[int] | np.ndarray | None = None,
) -> SparseMatrixBundle:
    """
    Construct a SciPy CSR sparse user-item matrix (never densified) and compute mean-centered views.

    Only observed non-zero ratings are centered so sparsity structure is strictly preserved.
    """
    unique_movies = np.array(sorted({int(m) for m in movie_ids}), dtype=np.int64)
    if user_ids is None:
        unique_users = np.array(sorted(ratings_df["user_id"].unique().astype(int)), dtype=np.int64)
    else:
        unique_users = np.array(sorted({int(u) for u in user_ids}), dtype=np.int64)

    user_to_idx = {int(u): i for i, u in enumerate(unique_users)}
    movie_to_idx = {int(m): j for j, m in enumerate(unique_movies)}

    valid = ratings_df[ratings_df["user_id"].isin(user_to_idx) & ratings_df["movie_id"].isin(movie_to_idx)]
    rows = valid["user_id"].map(user_to_idx).to_numpy(dtype=np.int32)
    cols = valid["movie_id"].map(movie_to_idx).to_numpy(dtype=np.int32)
    vals = valid["rating"].to_numpy(dtype=np.float32)

    n_users = len(unique_users)
    n_items = len(unique_movies)
    R = sparse.csr_matrix((vals, (rows, cols)), shape=(n_users, n_items), dtype=np.float32)
    R.sum_duplicates()
    R.sort_indices()

    global_mean = float(vals.mean()) if len(vals) > 0 else 3.5

    # Per-user mean over observed ratings
    user_sums = np.asarray(R.sum(axis=1)).ravel()
    user_counts = np.diff(R.indptr)
    user_means = np.where(user_counts > 0, user_sums / np.maximum(user_counts, 1), global_mean).astype(
        np.float32
    )

    # Per-item mean over observed ratings
    R_csc = R.tocsc()
    item_sums = np.asarray(R_csc.sum(axis=0)).ravel()
    item_counts = np.diff(R_csc.indptr).astype(np.int32)
    item_means = np.where(item_counts > 0, item_sums / np.maximum(item_counts, 1), global_mean).astype(
        np.float32
    )
    # Bayesian-regularized baseline prevents 1-rating noise from dominating top-K ranking
    reg_m = 12.0
    item_bayesian_means = ((item_counts * item_means + reg_m * global_mean) / (item_counts + reg_m)).astype(
        np.float32
    )

    # User-mean-centered sparse matrix (preserving zeros at unobserved entries)
    R_user = R.copy()
    for u_idx in range(n_users):
        start, end = R_user.indptr[u_idx], R_user.indptr[u_idx + 1]
        if end > start:
            R_user.data[start:end] -= user_means[u_idx]

    # Item-mean-centered sparse matrix (preserving zeros at unobserved entries)
    R_item_csc = R_csc.copy()
    for i_idx in range(n_items):
        start, end = R_item_csc.indptr[i_idx], R_item_csc.indptr[i_idx + 1]
        if end > start:
            R_item_csc.data[start:end] -= item_means[i_idx]
    R_item = R_item_csc.tocsr()
    R_user.sort_indices()
    R_item.sort_indices()

    return SparseMatrixBundle(
        matrix=R,
        user_to_idx=user_to_idx,
        idx_to_user=unique_users,
        movie_to_idx=movie_to_idx,
        idx_to_movie=unique_movies,
        user_means=user_means,
        item_means=item_means,
        item_bayesian_means=item_bayesian_means,
        item_counts=item_counts,
        global_mean=global_mean,
        user_centered=R_user,
        item_centered=R_item,
    )
