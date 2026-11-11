"""Unit tests for the ABSOLUTE CINEMA ML pipeline (Phase 2)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image
from scipy import sparse

from ml.src import enrich, ingest, preprocess, train
from ml.src.colors import (
    extract_catalogue_colors,
    extract_palette_from_image,
    genre_fallback_palette,
)
from ml.src.content_fallback import ContentFallbackModel
from ml.src.evaluate import (
    compute_precision_recall_at_k,
    compute_rmse_mae,
    evaluate_model_on_split,
)
from ml.src.ingest import _stable_indian_id, clean_movielens_title
from ml.src.item_cf import ItemBasedCF
from ml.src.loader import RecommenderEngine
from ml.src.matrix import build_sparse_matrix
from ml.src.popular import BayesianPopularityModel
from ml.src.preprocess import generate_synthetic_indian_ratings, normalize_genres
from ml.src.split import assert_no_leakage, temporal_user_split
from ml.src.user_cf import HybridCF, UserBasedCF


def _sample_catalogue_and_ratings() -> tuple[pd.DataFrame, pd.DataFrame]:
    movies = pd.DataFrame(
        [
            {
                "movie_id": 1,
                "title": "Toy Story",
                "year": 1995,
                "genres": "Animation|Comedy|Family",
                "industry": "hollywood",
                "language": "en",
                "director": "John Lasseter",
                "cast": "Tom Hanks",
                "overview": "Toys come alive.",
            },
            {
                "movie_id": 2,
                "title": "Matrix",
                "year": 1999,
                "genres": "Action|Sci-Fi",
                "industry": "hollywood",
                "language": "en",
                "director": "Wachowskis",
                "cast": "Keanu Reeves",
                "overview": "Virtual reality hacker rebellion.",
            },
            {
                "movie_id": 3,
                "title": "Inception",
                "year": 2010,
                "genres": "Action|Sci-Fi|Thriller",
                "industry": "hollywood",
                "language": "en",
                "director": "Christopher Nolan",
                "cast": "Leonardo DiCaprio",
                "overview": "Dream heist thriller.",
            },
            {
                "movie_id": 4,
                "title": "Interstellar",
                "year": 2014,
                "genres": "Sci-Fi|Drama|Adventure",
                "industry": "hollywood",
                "language": "en",
                "director": "Christopher Nolan",
                "cast": "Matthew McConaughey",
                "overview": "Space voyage across wormholes.",
            },
            {
                "movie_id": 5,
                "title": "RRR",
                "year": 2022,
                "genres": "Action|Drama|Adventure",
                "industry": "tollywood",
                "language": "te",
                "director": "S. S. Rajamouli",
                "cast": "N. T. Rama Rao Jr., Ram Charan",
                "overview": "Revolutionary action epic.",
            },
            {
                "movie_id": 6,
                "title": "3 Idiots",
                "year": 2009,
                "genres": "Comedy|Drama",
                "industry": "bollywood",
                "language": "hi",
                "director": "Rajkumar Hirani",
                "cast": "Aamir Khan",
                "overview": "Engineering college friends.",
            },
            {
                "movie_id": 7,
                "title": "Cold Indie Film",
                "year": 2024,
                "genres": "Action|Sci-Fi",
                "industry": "tollywood",
                "language": "te",
                "director": "New Director",
                "cast": "Actor A",
                "overview": "Futuristic cyber thriller.",
            },
        ]
    )
    rows = []
    ts = 1_600_000_000
    # 6 active users rating movies 1..6 (movie 7 has 0 ratings -> cold-start item)
    patterns = {
        10: [(1, 3.0), (2, 5.0), (3, 5.0), (4, 4.5), (5, 4.5), (6, 3.5)],
        11: [(1, 2.5), (2, 4.5), (3, 5.0), (4, 4.5), (5, 4.0), (6, 3.0)],
        12: [(1, 4.5), (2, 2.5), (3, 3.0), (4, 3.0), (5, 3.5), (6, 5.0)],
        13: [(1, 4.5), (2, 2.0), (3, 2.5), (4, 3.0), (5, 3.5), (6, 4.5)],
        14: [(1, 3.5), (2, 4.5), (3, 4.5), (4, 5.0), (5, 4.0), (6, 4.0)],
        15: [(1, 4.0), (2, 3.0), (3, 3.5), (4, 3.5), (5, 4.5), (6, 4.5)],
    }
    for uid, pairs in patterns.items():
        for idx, (mid, r) in enumerate(pairs):
            rows.append(
                {
                    "user_id": uid,
                    "movie_id": mid,
                    "rating": r,
                    "timestamp": ts + idx * 100,
                    "source": "movielens",
                }
            )
    return movies, pd.DataFrame(rows)


def test_clean_title_and_genre_normalization() -> None:
    assert clean_movielens_title("Matrix, The (1999)") == ("The Matrix", 1999)
    assert clean_movielens_title("Dark Knight, The (2008)") == ("The Dark Knight", 2008)
    assert normalize_genres("Children|Sci-Fi|IMAX|(no genres listed)") == ["Family", "Sci-Fi"]
    assert normalize_genres("Science Fiction film, Psychological thriller") == ["Sci-Fi", "Thriller"]


def test_sparse_matrix_shape_and_sparsity() -> None:
    movies, ratings = _sample_catalogue_and_ratings()
    bundle = build_sparse_matrix(ratings, movie_ids=movies["movie_id"].tolist())
    assert sparse.issparse(bundle.matrix)
    assert isinstance(bundle.matrix, sparse.csr_matrix)
    assert bundle.matrix.shape == (6, 7)
    assert bundle.matrix.nnz == len(ratings)
    assert bundle.item_counts[bundle.movie_to_idx[7]] == 0


def test_temporal_split_zero_leakage() -> None:
    _, ratings = _sample_catalogue_and_ratings()
    train_df, val_df, test_df = temporal_user_split(ratings, test_ratio=0.2, val_ratio=0.1)
    assert not test_df.empty
    assert_no_leakage(train_df, test_df)
    assert_no_leakage(train_df, val_df)

    # Deliberately inject leakage and verify assertion fails
    leaked = pd.concat([train_df, test_df.iloc[:1]], ignore_index=True)
    with pytest.raises(AssertionError, match="leakage"):
        assert_no_leakage(leaked, test_df)


def test_similarity_symmetry_and_hybrid_scoring() -> None:
    movies, ratings = _sample_catalogue_and_ratings()
    bundle = build_sparse_matrix(ratings, movie_ids=movies["movie_id"].tolist())
    icf = ItemBasedCF(top_n=10, shrinkage=0.0).fit(bundle)
    ucf = UserBasedCF(top_m=10, shrinkage=0.0).fit(bundle)
    assert sparse.issparse(icf.sim_matrix)
    assert sparse.issparse(ucf.sim_matrix)

    # Full top_n=10 covers all 7 items -> sim_matrix must be symmetric
    diff = np.abs((icf.sim_matrix - icf.sim_matrix.T).toarray()).max()
    assert diff < 1e-5

    hyb = HybridCF(item_cf=icf, user_cf=ucf, alpha=0.6)
    pred = hyb.predict_score(10, 4)
    assert 0.5 <= pred <= 5.0


def test_cold_start_user_and_cold_start_movie_paths() -> None:
    movies, ratings = _sample_catalogue_and_ratings()
    bundle = build_sparse_matrix(ratings, movie_ids=movies["movie_id"].tolist())
    icf = ItemBasedCF(top_n=10, shrinkage=5.0).fit(bundle)
    ucf = UserBasedCF(top_m=10, shrinkage=5.0).fit(bundle)
    hyb = HybridCF(item_cf=icf, user_cf=ucf, alpha=0.65)
    content = ContentFallbackModel().fit(movies)
    popular = BayesianPopularityModel().fit(movies, ratings)

    engine = RecommenderEngine(
        artifact={
            "version": "test",
            "alpha": 0.65,
            "min_rating_count": 5,
            "hybrid": hyb,
            "item_cf": icf,
            "user_cf": ucf,
            "content": content,
            "popular": popular,
            "catalogue": movies,
        },
        version="test",
        sha256="deadbeef",
    )

    # Cold-start user (no ratings) steered toward tollywood + Action
    cold_user_recs = engine.recommend_for_user(
        user_id=9999,
        user_history={},
        k=5,
        preferred_genres=["Action"],
        preferred_industries=["tollywood"],
    )
    assert len(cold_user_recs) == 5
    assert all(r.source == "popular_cold_start" for r in cold_user_recs)
    assert cold_user_recs[0].movie_id == 5  # RRR matches Action + tollywood

    # Active user should still receive cold-start movie #7 via content fallback
    user_recs = engine.recommend_for_user(
        user_id=10,
        user_history={2: 5.0, 3: 5.0},
        k=5,
    )
    rec_ids = {r.movie_id for r in user_recs}
    assert 7 in rec_ids
    cold_item_rec = next(r for r in user_recs if r.movie_id == 7)
    assert cold_item_rec.source == "content_fallback"
    assert len(cold_item_rec.reasons) >= 1


def test_metrics_against_hand_computed_examples() -> None:
    # Hand-computed RMSE & MAE: errors = [1.0, -1.0, 0.0, 2.0] -> sq = [1,1,0,4] -> mean=1.5 -> sqrt(1.5)
    rmse, mae = compute_rmse_mae([3.0, 4.0, 5.0, 2.0], [4.0, 3.0, 5.0, 4.0])
    assert math.isclose(rmse, math.sqrt(1.5), rel_tol=1e-6)
    assert math.isclose(mae, 1.0, rel_tol=1e-6)

    # Hand-computed Precision@4 & Recall@4: recs=[10,20,30,40], rel={20,40,50} -> 2 hits -> P=0.5, R=2/3
    p, r = compute_precision_recall_at_k([10, 20, 30, 40, 50], {20, 40, 50}, k=4)
    assert math.isclose(p, 0.5, rel_tol=1e-6)
    assert math.isclose(r, 2.0 / 3.0, rel_tol=1e-6)


def test_poster_color_extraction_and_fallback() -> None:
    # Synthetic rich amber + deep crimson poster image
    img = Image.new("RGB", (64, 96), color=(210, 95, 25))
    pal = extract_palette_from_image(img)
    assert pal is not None
    assert pal["dominant_color"].startswith("#")
    assert pal["color_luminance"] in {"dark", "mid", "light"}

    # Monochrome white image should return None and fall back cleanly
    mono = Image.new("RGB", (64, 96), color=(250, 250, 250))
    assert extract_palette_from_image(mono) is None
    fb = genre_fallback_palette("Horror|Thriller")
    assert fb["dominant_color"] == "#7A2E0B"

    # Extract catalogue colors with no network calls using genre fallback
    movies, _ = _sample_catalogue_and_ratings()
    movies["poster_url"] = None
    movies["ml_count"] = 10
    colored = extract_catalogue_colors(movies, max_downloads=0)
    assert "dominant_color" in colored.columns
    assert len(colored) == len(movies)


def test_evaluate_split_similar_genre_and_synthetic_generation() -> None:
    movies, ratings = _sample_catalogue_and_ratings()
    train_df, _, test_df = temporal_user_split(ratings, test_ratio=0.2, val_ratio=0.0)
    bundle = build_sparse_matrix(train_df, movie_ids=movies["movie_id"].tolist())
    icf = ItemBasedCF(top_n=10, shrinkage=2.0).fit(bundle)
    ucf = UserBasedCF(top_m=10, shrinkage=2.0).fit(bundle)
    hyb = HybridCF(item_cf=icf, user_cf=ucf, alpha=0.65)
    content = ContentFallbackModel().fit(movies)
    popular = BayesianPopularityModel().fit(movies, train_df)

    metrics = evaluate_model_on_split(hyb, train_df, test_df, movies, bundle, k=3)
    assert metrics["n_eval_ratings"] == len(test_df)
    assert 0.0 <= metrics["rmse"] <= 5.0
    assert 0.0 <= metrics["catalogue_coverage_at_3"] <= 1.0

    engine = RecommenderEngine(
        artifact={
            "version": "test",
            "alpha": 0.65,
            "min_rating_count": 5,
            "hybrid": hyb,
            "item_cf": icf,
            "user_cf": ucf,
            "content": content,
            "popular": popular,
            "catalogue": movies,
        },
        version="test",
        sha256="deadbeef",
    )
    sims = engine.similar_movies(2, k=3)
    assert len(sims) >= 1
    assert all(s.movie_id != 2 for s in sims)
    g_recs = engine.recommend_by_genre("Action", k=3)
    assert len(g_recs) >= 1

    movies_with_list = movies.copy()
    movies_with_list["genres_list"] = movies_with_list["genres"].apply(normalize_genres)
    syn = generate_synthetic_indian_ratings(movies_with_list, ratings, num_virtual_users=15, random_state=42)
    assert not syn.empty
    assert (syn["source"] == "synthetic").all()
    assert (
        enrich._infer_genres_from_text("A space expedition science fiction thriller")
        == "Sci-Fi|Thriller|Adventure"
    )
    assert _stable_indian_id("tollywood", "RRR", 2022) >= 900_000


def test_offline_ingest_preprocess_enrich_and_train_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exercise clean MovieLens loader on existing raw files (or synthetic temp raw)
    raw_ml = tmp_path / "ml_raw"
    raw_ml.mkdir()
    pd.DataFrame(
        [
            {"movieId": 1, "title": "Matrix, The (1999)", "genres": "Action|Sci-Fi"},
            {"movieId": 2, "title": "Toy Story (1995)", "genres": "Animation|Comedy|Children"},
            {"movieId": 3, "title": "Inception (2010)", "genres": "Action|Thriller"},
            {"movieId": 4, "title": "Interstellar (2014)", "genres": "Sci-Fi|Drama"},
            {"movieId": 5, "title": "Parasite (2019)", "genres": "Drama|Thriller"},
            {"movieId": 6, "title": "Niche Film (2020)", "genres": "Drama"},
        ]
    ).to_csv(raw_ml / "movies.csv", index=False)
    pd.DataFrame([{"movieId": i, "imdbId": 100000 + i, "tmdbId": 2000 + i} for i in range(1, 7)]).to_csv(
        raw_ml / "links.csv", index=False
    )
    r_rows = []
    for u in range(1, 8):
        for m in range(1, 6):
            r_rows.append(
                {
                    "userId": u,
                    "movieId": m,
                    "rating": 3.5 + ((u + m) % 3) * 0.5,
                    "timestamp": 1_600_000_000 + m * 100 + u,
                }
            )
    r_rows.append({"userId": 1, "movieId": 6, "rating": 4.0, "timestamp": 1_600_000_999})
    pd.DataFrame(r_rows).to_csv(raw_ml / "ratings.csv", index=False)

    monkeypatch.setattr(ingest, "ML_DIR", raw_ml)
    monkeypatch.setattr(ingest, "PROCESSED_DIR", tmp_path / "proc")
    monkeypatch.setattr(preprocess, "PROCESSED_DIR", tmp_path / "proc")
    monkeypatch.setattr(enrich, "CACHE_PATH", tmp_path / "proc" / "enrich_cache.json")
    monkeypatch.setattr(train, "PROCESSED_DIR", tmp_path / "proc")
    monkeypatch.setattr(train, "ARTIFACTS_DIR", tmp_path / "artifacts")

    # Mock remote Wikidata/Wikipedia calls so test stays 100% offline & fast
    monkeypatch.setattr(ingest, "fetch_wikidata_indian_films", lambda *a, **kw: [])
    monkeypatch.setattr(
        enrich,
        "_batch_wikidata_by_imdb",
        lambda ids: {
            i: {"wikipedia_title": f"Wiki {i}", "runtime": 122, "director": "Dir", "cast": "Actor"}
            for i in ids
        },
    )
    monkeypatch.setattr(enrich, "_batch_wikidata_by_qid", lambda qids: {})
    monkeypatch.setattr(
        enrich,
        "_batch_wikipedia_media",
        lambda titles: {t: {"poster_url": None, "overview": "A dramatic thriller."} for t in titles},
    )

    cat, ml_r = ingest.build_balanced_catalogue(hollywood_target=6, bollywood_target=4, tollywood_target=4)
    assert len(cat) >= 10
    enriched = enrich.enrich_catalogue(cat, tmdb_api_key="")
    assert "overview" in enriched.columns
    _saved_cat, saved_r = preprocess.preprocess_and_save(enriched, ml_r, random_state=42)
    assert (tmp_path / "proc" / "movies_catalogue.csv").exists()
    assert len(saved_r) >= len(ml_r)

    # Exercise run_training end-to-end on the temporary processed directory
    metrics = train.run_training(version="vtest", reuse_processed=True, k_eval=3)
    assert (tmp_path / "artifacts" / "model_vtest.joblib").exists()
    assert (tmp_path / "artifacts" / "manifest.json").exists()
    assert "movielens" in metrics["metrics"]
    assert "all" in metrics["metrics"]

    loaded = RecommenderEngine.load_latest(tmp_path / "artifacts")
    assert loaded.version == "vtest"
    assert len(loaded.recommend_for_user(1, {1: 5.0, 2: 4.5}, k=3)) == 3


def test_real_model_personalization_scenarios() -> None:
    """Exercise full seeded model_v1 against Part 1 personalization & taste-profile scenarios."""
    artifacts_dir = Path(__file__).resolve().parents[1] / "artifacts"
    if not (artifacts_dir / "model_v1.joblib").exists():
        pytest.skip("model_v1.joblib not present")

    eng = RecommenderEngine.load_latest(artifacts_dir)
    cat = eng.catalogue

    scifi_ids = (
        cat[cat["genres"].str.contains("Sci-Fi", na=False) & (cat["industry"] == "hollywood")]
        .sort_values("rating_count", ascending=False)["movie_id"]
        .head(10)
        .astype(int)
        .tolist()
    )
    rom_ids = (
        cat[
            cat["genres"].str.contains("Romance", na=False)
            & (~cat["genres"].str.contains("Sci-Fi", na=False))
            & (cat["industry"] == "hollywood")
        ]
        .sort_values("rating_count", ascending=False)["movie_id"]
        .head(3)
        .astype(int)
        .tolist()
    )
    bolly_rom_ids = (
        cat[cat["genres"].str.contains("Romance", na=False) & (cat["industry"] == "bollywood")]
        .sort_values("rating_count", ascending=False)["movie_id"]
        .head(10)
        .astype(int)
        .tolist()
    )
    tolly_act_ids = (
        cat[cat["genres"].str.contains("Action", na=False) & (cat["industry"] == "tollywood")]
        .sort_values("rating_count", ascending=False)["movie_id"]
        .head(5)
        .astype(int)
        .tolist()
    )

    # 1. User A: 10 Sci-Fi 5★ + 3 Romances 1★ -> Sci-Fi/Action top picks, no romance-only titles
    hist_a = {m: 5.0 for m in scifi_ids}
    hist_a = {m: 5.0 for m in scifi_ids}
    for m in rom_ids:
        hist_a[m] = 1.0
    ts_a = {m: 1_000.0 + idx for idx, m in enumerate(hist_a)}

    recs_a = eng.recommend_for_user(90_001, hist_a, k=20, user_timestamps=ts_a)
    assert len(recs_a) == 20
    rec_ids_a = {r.movie_id for r in recs_a}
    assert rec_ids_a.isdisjoint(set(hist_a.keys()))

    scifi_act_hits = sum(
        1 for r in recs_a if any(g in eng.genres_by_id[r.movie_id] for g in ("Sci-Fi", "Action"))
    )
    assert scifi_act_hits >= 14
    romance_heavy_in_a = [
        r.movie_id
        for r in recs_a
        if "Romance" in eng.genres_by_id[r.movie_id]
        and not any(g in eng.genres_by_id[r.movie_id] for g in ("Sci-Fi", "Action"))
    ]
    assert len(romance_heavy_in_a) == 0

    prof_a = eng.compute_taste_profile(hist_a, ts_a)
    assert prof_a.genre_order[0] in ("Sci-Fi", "Action")
    assert prof_a.genre_order.index("Romance") > prof_a.genre_order.index("Sci-Fi")

    # 2. User B: 10 Bollywood Romance 5★ -> dominated by Bollywood & minimal overlap with User A
    hist_b = {m: 5.0 for m in bolly_rom_ids}
    recs_b = eng.recommend_for_user(90_002, hist_b, k=20)
    assert len(recs_b) == 20
    assert {r.movie_id for r in recs_b}.isdisjoint(set(hist_b.keys()))
    bolly_hits = sum(1 for r in recs_b if eng.industry_by_id[r.movie_id] == "bollywood")
    assert bolly_hits >= 14
    overlap = len(rec_ids_a & {r.movie_id for r in recs_b})
    assert overlap <= 2

    prof_b = eng.compute_taste_profile(hist_b)
    assert prof_b.industry_order[0] == "bollywood"
    assert prof_b.genre_order.index("Romance") < prof_b.genre_order.index("Sci-Fi")

    # 3. Shift User A with 5 newer Tollywood Action 5★ -> Tollywood enters picks & rises in order
    hist_a_tolly = {**hist_a, **{m: 5.0 for m in tolly_act_ids}}
    ts_a_tolly = {**ts_a, **{m: 5_000.0 + idx for idx, m in enumerate(tolly_act_ids)}}
    recs_tolly = eng.recommend_for_user(90_001, hist_a_tolly, k=20, user_timestamps=ts_a_tolly)
    assert any(eng.industry_by_id[r.movie_id] == "tollywood" for r in recs_tolly)
    prof_t = eng.compute_taste_profile(hist_a_tolly, ts_a_tolly)
    assert prof_t.industry_order.index("tollywood") < prof_t.industry_order.index("bollywood")

    # 4. Lowering a rating from 5★ -> 1★ lowers its collaborative neighbors
    anchor = scifi_ids[0]
    top_nbr = eng.similar_movies(anchor, k=1)[0].movie_id
    r_high = [r.movie_id for r in eng.recommend_for_user(90_003, {anchor: 5.0, scifi_ids[1]: 5.0}, k=500)]
    r_low = [r.movie_id for r in eng.recommend_for_user(90_003, {anchor: 1.0, scifi_ids[1]: 5.0}, k=500)]
    pos_high = r_high.index(top_nbr) if top_nbr in r_high else 999
    pos_low = r_low.index(top_nbr) if top_nbr in r_low else 999
    assert pos_low > pos_high

    # 5. Harsh & generous raters both get relevant Sci-Fi/Action recommendations
    hist_harsh = {m: 3.5 for m in scifi_ids}
    for m in rom_ids:
        hist_harsh[m] = 1.0
    recs_harsh = eng.recommend_for_user(90_004, hist_harsh, k=10)
    assert any(any(g in eng.genres_by_id[r.movie_id] for g in ("Sci-Fi", "Action")) for r in recs_harsh[:5])

    # 6. Because-you-rated rows work & cold-start onboarding + 0-rating user return populated lists
    b_rows = eng.because_you_rated_rows(hist_a_tolly, ts_a_tolly, limit_rows=3, k=12)
    assert 1 <= len(b_rows) <= 3
    assert all(len(items) >= 4 for _, _, items in b_rows)

    cold = eng.recommend_for_user(
        90_005, {}, k=10, preferred_genres=["Sci-Fi"], preferred_industries=["tollywood"]
    )
    assert len(cold) == 10
    assert any(
        "Sci-Fi" in eng.genres_by_id[r.movie_id] or eng.industry_by_id[r.movie_id] == "tollywood"
        for r in cold
    )
