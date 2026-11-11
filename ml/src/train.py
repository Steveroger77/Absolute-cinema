"""End-to-end offline ML training entrypoint: `python -m ml.src.train`."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ml.src.colors import extract_catalogue_colors
from ml.src.content_fallback import ContentFallbackModel
from ml.src.enrich import enrich_catalogue
from ml.src.evaluate import evaluate_model_on_split
from ml.src.ingest import build_balanced_catalogue
from ml.src.item_cf import ItemBasedCF
from ml.src.matrix import build_sparse_matrix
from ml.src.popular import BayesianPopularityModel
from ml.src.preprocess import preprocess_and_save
from ml.src.split import assert_no_leakage, temporal_user_split
from ml.src.user_cf import HybridCF, UserBasedCF

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"


def run_training(
    version: str = "v1",
    reuse_processed: bool = True,
    k_eval: int = 10,
) -> dict[str, Any]:
    """
    Execute ingestion/enrichment (or load processed), tune on validation, train on train-only,
    and evaluate on test.
    """
    movies_csv = PROCESSED_DIR / "movies_catalogue.csv"
    ratings_csv = PROCESSED_DIR / "ratings_clean.csv"

    if reuse_processed and movies_csv.exists() and ratings_csv.exists():
        logger.info("Loading existing processed dataset from %s", PROCESSED_DIR)
        catalogue = pd.read_csv(movies_csv)
        ratings = pd.read_csv(ratings_csv)
    else:
        raw_cat, ml_ratings = build_balanced_catalogue()
        enriched = enrich_catalogue(raw_cat)
        colored = extract_catalogue_colors(enriched)
        catalogue, ratings = preprocess_and_save(colored, ml_ratings, random_state=42)

    movie_ids = catalogue["movie_id"].astype(int).tolist()
    train_df, val_df, test_df = temporal_user_split(ratings, test_ratio=0.20, val_ratio=0.10)
    assert_no_leakage(train_df, test_df)

    # 1. Hyperparameter tuning on validation split ONLY (using train_df matrix)
    logger.info(
        "Splitting ratings -> train=%d, val=%d, test=%d",
        len(train_df),
        len(val_df),
        len(test_df),
    )
    train_bundle = build_sparse_matrix(train_df, movie_ids=movie_ids)

    best_alpha = 0.65
    best_item_shrink = 15.0
    best_user_shrink = 12.0
    best_content_weight = 0.22
    best_taste_weight = 0.32
    best_val_rmse = float("inf")

    for item_shrink in (10.0, 20.0):
        icf = ItemBasedCF(top_n=50, shrinkage=item_shrink).fit(train_bundle)
        ucf = UserBasedCF(top_m=45, shrinkage=best_user_shrink).fit(train_bundle)
        for alpha in (0.45, 0.65, 0.80):
            hyb = HybridCF(item_cf=icf, user_cf=ucf, alpha=alpha)
            val_metrics = evaluate_model_on_split(
                hyb,
                train_df,
                val_df,
                catalogue,
                train_bundle,
                k=k_eval,
                max_ranking_users=150,
            )
            if val_metrics["rmse"] < best_val_rmse:
                best_val_rmse = val_metrics["rmse"]
                best_alpha = alpha
                best_item_shrink = item_shrink

    logger.info(
        "Validation tuning winner: alpha=%.2f, item_shrink=%.1f (val_rmse=%.4f)",
        best_alpha,
        best_item_shrink,
        best_val_rmse,
    )

    # 2. Fit final models on train + val (strictly excluding test_df!)
    fit_df = pd.concat([train_df, val_df], ignore_index=True)
    assert_no_leakage(fit_df, test_df)
    fit_bundle = build_sparse_matrix(fit_df, movie_ids=movie_ids)

    item_cf = ItemBasedCF(top_n=55, shrinkage=best_item_shrink).fit(fit_bundle)
    user_cf = UserBasedCF(top_m=45, shrinkage=best_user_shrink).fit(fit_bundle)
    hybrid = HybridCF(item_cf=item_cf, user_cf=user_cf, alpha=best_alpha)
    content = ContentFallbackModel().fit(catalogue)
    popular = BayesianPopularityModel().fit(catalogue, fit_df)

    # Tune content blend weight cleanly on validation slice against cold/seen items
    val_sample_users = val_df["user_id"].unique().astype(int)[:80]
    train_hist_by_user: dict[int, dict[int, float]] = (
        train_df.groupby("user_id")
        .apply(
            lambda g: {int(m): float(r) for m, r in zip(g["movie_id"], g["rating"], strict=False)},
            include_groups=False,
        )
        .to_dict()
        if "user_id" in train_df.columns
        else {}
    )
    best_val_p = -1.0
    if len(val_sample_users) > 0:
        for cw in (0.14, 0.22, 0.30):
            hits = 0
            denom = 0
            for uid in val_sample_users:
                uh = train_hist_by_user.get(int(uid))
                if not uh:
                    continue
                rel = set(
                    val_df[(val_df["user_id"] == uid) & (val_df["rating"] >= 3.5)]["movie_id"]
                    .astype(int)
                    .tolist()
                )
                if not rel:
                    continue
                cf_sc, _ = hybrid.score_all_for_user(int(uid), user_history=uh)
                cont_sc = content.score_all_for_history(uh)
                comb = (1.0 - cw) * cf_sc + cw * cont_sc
                for r_mid in uh:
                    j_i = fit_bundle.movie_to_idx.get(r_mid)
                    if j_i is not None:
                        comb[j_i] = -1e9
                top_i = comb.argsort()[-k_eval:][::-1]
                rec_mids = {int(fit_bundle.idx_to_movie[i]) for i in top_i}
                hits += len(rec_mids & rel)
                denom += k_eval
            if denom > 0 and (hits / denom) > best_val_p:
                best_val_p = hits / denom
                best_content_weight = cw

    # 3. Evaluate on held-out test set separately for `movielens` and `all`
    test_ml = test_df[test_df["source"] == "movielens"]
    fit_ml = fit_df[fit_df["source"] == "movielens"]

    metrics_all = {
        "hybrid_cf": evaluate_model_on_split(hybrid, fit_df, test_df, catalogue, fit_bundle, k=k_eval),
        "item_cf_baseline": evaluate_model_on_split(
            item_cf, fit_df, test_df, catalogue, fit_bundle, k=k_eval
        ),
        "user_cf_baseline": evaluate_model_on_split(
            user_cf, fit_df, test_df, catalogue, fit_bundle, k=k_eval
        ),
    }
    metrics_movielens = {
        "hybrid_cf": evaluate_model_on_split(hybrid, fit_ml, test_ml, catalogue, fit_bundle, k=k_eval),
        "item_cf_baseline": evaluate_model_on_split(
            item_cf, fit_ml, test_ml, catalogue, fit_bundle, k=k_eval
        ),
        "user_cf_baseline": evaluate_model_on_split(
            user_cf, fit_ml, test_ml, catalogue, fit_bundle, k=k_eval
        ),
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_filename = f"model_{version}.joblib"
    artifact_path = ARTIFACTS_DIR / artifact_filename

    artifact_payload = {
        "version": version,
        "alpha": best_alpha,
        "item_shrinkage": best_item_shrink,
        "user_shrinkage": best_user_shrink,
        "cf_weight": round(1.0 - best_content_weight, 4),
        "content_weight": round(best_content_weight, 4),
        "taste_weight": best_taste_weight,
        "min_rating_count": 5,
        "hybrid": hybrid,
        "item_cf": item_cf,
        "user_cf": user_cf,
        "content": content,
        "popular": popular,
        "catalogue": catalogue,
    }
    joblib.dump(artifact_payload, artifact_path, compress=3)
    sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    trained_at = datetime.now(timezone.utc).isoformat()
    industry_counts = {str(k): int(v) for k, v in catalogue["industry"].value_counts().items()}

    metrics_doc = {
        "version": version,
        "trained_at": trained_at,
        "hyperparameters": {
            "alpha": best_alpha,
            "item_shrinkage": best_item_shrink,
            "user_shrinkage": best_user_shrink,
            "cf_weight": round(1.0 - best_content_weight, 4),
            "content_weight": round(best_content_weight, 4),
            "taste_weight": best_taste_weight,
            "item_top_n": 55,
            "user_top_m": 45,
            "k_eval": k_eval,
        },
        "dataset": {
            "total_movies": len(catalogue),
            "industries": industry_counts,
            "total_ratings": len(ratings),
            "movielens_ratings": int((ratings["source"] == "movielens").sum()),
            "synthetic_ratings": int((ratings["source"] == "synthetic").sum()),
            "synthetic_disclosure": (
                "Non-MovieLens Indian cinema titles (Bollywood/Tollywood) include deterministically "
                "seeded (random_state=42) synthetic user-item ratings flagged source='synthetic'. "
                "Metrics are reported separately for real MovieLens interactions and all interactions."
            ),
            "train_val_ratings": len(fit_df),
            "test_ratings": len(test_df),
            "matrix_nnz": int(fit_bundle.matrix.nnz),
            "matrix_density": round(
                float(fit_bundle.matrix.nnz) / float(fit_bundle.matrix.shape[0] * fit_bundle.matrix.shape[1]),
                6,
            ),
        },
        "metrics": {
            "movielens": metrics_movielens,
            "all": metrics_all,
        },
    }

    manifest_doc = {
        "version": version,
        "artifact_filename": artifact_filename,
        "sha256": sha256,
        "trained_at": trained_at,
        "total_movies": len(catalogue),
        "total_ratings": len(ratings),
        "weights": {
            "alpha": best_alpha,
            "cf_weight": round(1.0 - best_content_weight, 4),
            "content_weight": round(best_content_weight, 4),
            "taste_weight": best_taste_weight,
            "item_shrinkage": best_item_shrink,
            "user_shrinkage": best_user_shrink,
        },
    }

    (ARTIFACTS_DIR / "metrics.json").write_text(json.dumps(metrics_doc, indent=2), encoding="utf-8")
    (ARTIFACTS_DIR / "manifest.json").write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")
    logger.info("Saved artifact %s (sha256=%s...)", artifact_path, sha256[:12])
    return metrics_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ABSOLUTE CINEMA recommender model.")
    parser.add_argument("--version", default="v1", help="Model artifact version label.")
    parser.add_argument("--rebuild-data", action="store_true", help="Re-run ingest, enrich, and colors.")
    args = parser.parse_args()
    metrics = run_training(version=args.version, reuse_processed=not args.rebuild_data)
    print(json.dumps(metrics["metrics"], indent=2))


if __name__ == "__main__":
    main()
