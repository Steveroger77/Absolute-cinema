"""Evaluation metrics: RMSE, MAE, Precision@K, Recall@K, catalogue coverage, and popularity bias."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from ml.src.matrix import SparseMatrixBundle


def compute_rmse_mae(
    y_true: list[float] | np.ndarray, y_pred: list[float] | np.ndarray
) -> tuple[float, float]:
    """Compute exact Root Mean Squared Error and Mean Absolute Error."""
    t = np.asarray(y_true, dtype=np.float64)
    p = np.asarray(y_pred, dtype=np.float64)
    if len(t) == 0:
        return 0.0, 0.0
    err = p - t
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    return rmse, mae


def compute_precision_recall_at_k(
    recommended_ids: list[int],
    relevant_ids: set[int],
    k: int,
) -> tuple[float, float]:
    """Compute Precision@K and Recall@K for a single user."""
    if k <= 0:
        return 0.0, 0.0
    top_k = recommended_ids[:k]
    hits = sum(1 for mid in top_k if mid in relevant_ids)
    precision = hits / float(k)
    recall = (hits / float(len(relevant_ids))) if relevant_ids else 0.0
    return precision, recall


def _gini(counts: np.ndarray) -> float:
    """Compute Gini concentration coefficient (0 = perfectly uniform, 1 = winner-take-all)."""
    arr = np.sort(counts.astype(np.float64))
    if len(arr) == 0 or arr.sum() == 0:
        return 0.0
    n = len(arr)
    idx = np.arange(1, n + 1, dtype=np.float64)
    return float((2.0 * np.sum(idx * arr)) / (n * np.sum(arr)) - (n + 1.0) / n)


def evaluate_model_on_split(
    model: Any,
    train_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    catalogue_df: pd.DataFrame,
    bundle: SparseMatrixBundle,
    k: int = 10,
    relevance_threshold: float = 3.5,
    max_ranking_users: int | None = None,
) -> dict[str, Any]:
    """Evaluate rating accuracy (RMSE/MAE) and top-K ranking quality + coverage + popularity bias."""
    if eval_df.empty:
        return {
            "n_eval_ratings": 0,
            "n_eval_users": 0,
            "rmse": 0.0,
            "mae": 0.0,
            f"precision_at_{k}": 0.0,
            f"recall_at_{k}": 0.0,
            f"catalogue_coverage_at_{k}": 0.0,
            "popularity_bias_mean_log_pop": 0.0,
            "popularity_gini": 0.0,
        }

    # Build user training history map to exclude seen items from top-K ranking
    train_seen: dict[int, set[int]] = (
        train_df.groupby("user_id")["movie_id"].apply(lambda s: {int(x) for x in s}).to_dict()
    )

    # 1. Rating prediction metrics (RMSE, MAE)
    y_true: list[float] = []
    y_pred: list[float] = []
    for uid, mid, r in zip(eval_df["user_id"], eval_df["movie_id"], eval_df["rating"], strict=False):
        y_true.append(float(r))
        y_pred.append(float(model.predict_score(int(uid), int(mid))))
    rmse, mae = compute_rmse_mae(y_true, y_pred)

    # 2. Top-K ranking metrics, coverage & popularity bias
    all_movie_ids = bundle.idx_to_movie
    # Item popularity in training set
    pop_counts = train_df.groupby("movie_id")["rating"].count().to_dict()
    max_log_pop = max([math.log1p(c) for c in pop_counts.values()] + [1.0])

    eval_users = sorted(eval_df["user_id"].unique().astype(int).tolist())
    if max_ranking_users is not None and len(eval_users) > max_ranking_users:
        eval_users = eval_users[:max_ranking_users]

    precisions: list[float] = []
    recalls: list[float] = []
    rec_item_counts: dict[int, int] = {int(m): 0 for m in catalogue_df["movie_id"]}
    rec_pop_norms: list[float] = []

    rel_by_user: dict[int, set[int]] = (
        eval_df[eval_df["rating"] >= relevance_threshold]
        .groupby("user_id")["movie_id"]
        .apply(lambda s: {int(x) for x in s})
        .to_dict()
    )

    for uid in eval_users:
        rel_set = rel_by_user.get(uid, set())
        if not rel_set:
            continue
        scored = model.score_all_for_user(uid)
        scores = scored[0] if isinstance(scored, tuple) else scored
        seen = train_seen.get(uid, set())

        # Mask already rated training movies
        masked = scores.copy()
        for s_mid in seen:
            j_idx = bundle.movie_to_idx.get(s_mid)
            if j_idx is not None:
                masked[j_idx] = -1e9

        top_idx = np.argpartition(masked, -k)[-k:]
        top_idx = top_idx[np.argsort(-masked[top_idx])]
        rec_ids = [int(all_movie_ids[i]) for i in top_idx]

        p, r = compute_precision_recall_at_k(rec_ids, rel_set, k)
        precisions.append(p)
        recalls.append(r)

        for mid in rec_ids:
            rec_item_counts[mid] = rec_item_counts.get(mid, 0) + 1
            rec_pop_norms.append(math.log1p(pop_counts.get(mid, 0)) / max_log_pop)

    unique_rec = sum(1 for c in rec_item_counts.values() if c > 0)
    coverage = unique_rec / float(max(1, len(catalogue_df)))
    gini = _gini(np.array(list(rec_item_counts.values()), dtype=np.float64))

    return {
        "n_eval_ratings": len(y_true),
        "n_eval_users": len(precisions),
        "rmse": round(rmse, 4),
        "mae": round(mae, 4),
        f"precision_at_{k}": round(float(np.mean(precisions)) if precisions else 0.0, 4),
        f"recall_at_{k}": round(float(np.mean(recalls)) if recalls else 0.0, 4),
        f"catalogue_coverage_at_{k}": round(coverage, 4),
        "popularity_bias_mean_log_pop": round(float(np.mean(rec_pop_norms)) if rec_pop_norms else 0.0, 4),
        "popularity_gini": round(gini, 4),
    }
