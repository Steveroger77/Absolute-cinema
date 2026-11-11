"""Genre taxonomy normalization and deterministic synthetic Indian cinema interaction generation."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

CANONICAL_GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Family",
    "Fantasy",
    "Film-Noir",
    "Horror",
    "Musical",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
]

GENRE_MAP: dict[str, str] = {
    "action": "Action",
    "action film": "Action",
    "martial arts film": "Action",
    "superhero film": "Action",
    "adventure": "Adventure",
    "adventure film": "Adventure",
    "animation": "Animation",
    "animated film": "Animation",
    "comedy": "Comedy",
    "comedy film": "Comedy",
    "romantic comedy": "Comedy",
    "comedy drama": "Comedy",
    "comedy-drama": "Comedy",
    "crime": "Crime",
    "crime film": "Crime",
    "gangster film": "Crime",
    "documentary": "Documentary",
    "documentary film": "Documentary",
    "drama": "Drama",
    "drama film": "Drama",
    "biographical film": "Drama",
    "sports film": "Drama",
    "social drama": "Drama",
    "children": "Family",
    "family": "Family",
    "family film": "Family",
    "fantasy": "Fantasy",
    "fantasy film": "Fantasy",
    "mythological film": "Fantasy",
    "film-noir": "Film-Noir",
    "horror": "Horror",
    "horror film": "Horror",
    "supernatural horror": "Horror",
    "musical": "Musical",
    "musical film": "Musical",
    "music": "Musical",
    "mystery": "Mystery",
    "mystery film": "Mystery",
    "romance": "Romance",
    "romance film": "Romance",
    "sci-fi": "Sci-Fi",
    "science fiction": "Sci-Fi",
    "science fiction film": "Sci-Fi",
    "thriller": "Thriller",
    "thriller film": "Thriller",
    "psychological thriller": "Thriller",
    "crime thriller": "Thriller",
    "suspense": "Thriller",
    "war": "War",
    "war film": "War",
    "western": "Western",
}


def normalize_genres(raw: str | None) -> list[str]:
    """Map raw pipe/comma-separated genres to unified canonical taxonomy."""
    if not raw or pd.isna(raw):
        return ["Drama"]
    tokens = [t.strip().lower() for t in str(raw).replace(",", "|").split("|") if t.strip()]
    out: list[str] = []
    for tok in tokens:
        if tok in ("(no genres listed)", "imax"):
            continue
        mapped = GENRE_MAP.get(tok)
        if not mapped:
            for k, v in GENRE_MAP.items():
                if k in tok:
                    mapped = v
                    break
        if mapped and mapped not in out:
            out.append(mapped)
    return out if out else ["Drama"]


def generate_synthetic_indian_ratings(
    catalogue: pd.DataFrame,
    movielens_ratings: pd.DataFrame,
    num_virtual_users: int = 320,
    random_state: int = 42,
) -> pd.DataFrame:
    """
    Generate clearly labelled (`source='synthetic'`) ratings for Indian titles + bridge MovieLens titles.

    Virtual users belong to 12 genre/industry taste clusters with Zipfian item popularity skew and
    ~10% low-count titles (<5 ratings) preserved so content-based fallback remains genuinely exercised.
    """
    rng = np.random.default_rng(random_state)
    indian_df = catalogue[catalogue["industry"].isin(["bollywood", "tollywood"])].copy()
    if indian_df.empty:
        return pd.DataFrame(columns=["user_id", "movie_id", "rating", "timestamp", "source"])

    holly_df = catalogue[catalogue["industry"] == "hollywood"].copy()

    # Reserve ~10% of Indian titles as sparse/cold-start (<5 ratings)
    n_cold = max(10, int(len(indian_df) * 0.10))
    indian_shuffled = indian_df.sample(frac=1.0, random_state=random_state).reset_index(drop=True)
    cold_indian_ids = set(indian_shuffled.iloc[:n_cold]["movie_id"].tolist())

    # Popularity weights (power-law Zipf skew; seed hits slightly boosted)
    pop_rank = np.arange(1, len(indian_df) + 1, dtype=np.float64)
    rng.shuffle(pop_rank)
    base_pop = 1.0 / (pop_rank**0.72)
    base_pop = np.where(indian_df["movie_id"].isin(cold_indian_ids), base_pop * 0.04, base_pop)
    indian_ids = indian_df["movie_id"].to_numpy()
    indian_ind = indian_df["industry"].to_numpy()
    indian_genres = indian_df["genres_list"].tolist()

    # 12 taste archetypes spanning Tollywood, Bollywood, and cross-industry cinema fans
    archetypes: list[tuple[list[str], list[str]]] = [
        (["tollywood"], ["Action", "Fantasy", "Adventure"]),
        (["tollywood"], ["Drama", "Romance", "Family"]),
        (["tollywood"], ["Thriller", "Mystery", "Crime"]),
        (["tollywood", "bollywood"], ["Action", "Crime", "Thriller"]),
        (["bollywood"], ["Drama", "Musical", "Romance"]),
        (["bollywood"], ["Comedy", "Drama", "Family"]),
        (["bollywood"], ["Crime", "Thriller", "Mystery"]),
        (["bollywood"], ["Horror", "Fantasy", "Mystery"]),
        (["bollywood", "tollywood"], ["Comedy", "Romance", "Musical"]),
        (["bollywood", "tollywood"], ["Sci-Fi", "Action", "Adventure"]),
        (["bollywood", "tollywood"], ["War", "Action", "Drama"]),
        (["bollywood", "tollywood"], ["Drama", "Comedy", "Romance"]),
    ]

    max_ml_uid = int(movielens_ratings["user_id"].max()) if not movielens_ratings.empty else 610
    start_uid = max(10_001, max_ml_uid + 1000)

    # Also bridge each synthetic user with 6-10 Hollywood titles matching their genre affinity
    holly_records = list(zip(holly_df["movie_id"].tolist(), holly_df["genres_list"].tolist(), strict=False))

    # Inherent movie quality bias calibrated cleanly around MovieLens ~3.48 baseline
    movie_quality: dict[int, float] = {
        int(mid): float(np.clip(rng.normal(3.48, 0.42), 2.3, 4.35)) for mid in catalogue["movie_id"]
    }

    rows: list[dict[str, object]] = []
    base_ts = 1_514_764_800  # 2018-01-01 UTC
    end_ts = 1_735_689_600  # 2025-01-01 UTC

    for idx in range(num_virtual_users):
        uid = start_uid + idx
        pref_industries, pref_genres = archetypes[idx % len(archetypes)]
        pref_genre_set = set(pref_genres)
        user_bias = float(rng.normal(0.0, 0.25))

        # Compute affinity score for every Indian film
        weights = np.zeros(len(indian_df), dtype=np.float64)
        for j in range(len(indian_df)):
            ind_match = 3.2 if indian_ind[j] in pref_industries else 0.45
            g_overlap = len(pref_genre_set.intersection(indian_genres[j]))
            g_boost = 1.0 + 1.8 * g_overlap
            weights[j] = base_pop[j] * ind_match * g_boost

        weights = weights / weights.sum()
        n_indian_rate = int(rng.integers(24, 58))
        chosen_idx = rng.choice(
            len(indian_df), size=min(n_indian_rate, len(indian_df)), replace=False, p=weights
        )

        # Select 6-10 Hollywood crossover movies sharing preferred genres
        matching_holly = [mid for mid, glist in holly_records if pref_genre_set.intersection(glist)]
        if not matching_holly:
            matching_holly = [mid for mid, _ in holly_records]
        n_holly = min(len(matching_holly), int(rng.integers(6, 12)))
        chosen_holly = rng.choice(matching_holly, size=n_holly, replace=False).tolist() if n_holly > 0 else []

        total_items = [(int(indian_ids[j]), indian_genres[j], indian_ind[j]) for j in chosen_idx]
        holly_map = dict(holly_records)
        for mid in chosen_holly:
            total_items.append((int(mid), holly_map[int(mid)], "hollywood"))

        timestamps = np.sort(rng.integers(base_ts, end_ts, size=len(total_items)))
        for k, (mid, glist, ind) in enumerate(total_items):
            if mid in cold_indian_ids and sum(1 for r in rows if r["movie_id"] == mid) >= 3:
                continue
            g_match = len(pref_genre_set.intersection(glist))
            ind_bonus = 0.15 if ind in pref_industries else -0.22
            raw_score = (
                movie_quality[mid]
                + user_bias
                + 0.28 * (min(2, g_match) - 0.85)
                + ind_bonus
                + rng.normal(0.0, 0.52)
            )
            half_star = float(np.clip(np.round(raw_score * 2.0) / 2.0, 0.5, 5.0))
            rows.append(
                {
                    "user_id": uid,
                    "movie_id": mid,
                    "rating": half_star,
                    "timestamp": int(timestamps[k]),
                    "source": "synthetic",
                }
            )

    syn_df = pd.DataFrame(rows)
    logger.info(
        "Generated %d synthetic ratings across %d virtual users (%d cold Indian titles <=3 ratings)",
        len(syn_df),
        num_virtual_users,
        len(cold_indian_ids),
    )
    return syn_df


def preprocess_and_save(
    catalogue: pd.DataFrame,
    movielens_ratings: pd.DataFrame,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize genres, attach synthetic ratings for Indian cinema, and save processed outputs."""
    df = catalogue.copy()
    df["genres_list"] = df["genres"].apply(normalize_genres)
    df["genres"] = df["genres_list"].apply(lambda gs: "|".join(gs))

    syn_ratings = generate_synthetic_indian_ratings(
        df, movielens_ratings, num_virtual_users=320, random_state=random_state
    )
    all_ratings = pd.concat(
        [
            movielens_ratings[["user_id", "movie_id", "rating", "timestamp", "source"]],
            syn_ratings[["user_id", "movie_id", "rating", "timestamp", "source"]],
        ],
        ignore_index=True,
    )
    all_ratings["user_id"] = all_ratings["user_id"].astype(int)
    all_ratings["movie_id"] = all_ratings["movie_id"].astype(int)
    all_ratings["rating"] = all_ratings["rating"].astype(float)
    all_ratings["timestamp"] = all_ratings["timestamp"].astype(int)
    all_ratings = all_ratings.drop_duplicates(subset=["user_id", "movie_id"], keep="last")

    # Recompute exact aggregate stats across combined ratings
    df = df.drop(columns=["rating_avg", "rating_count"], errors="ignore")
    agg = all_ratings.groupby("movie_id")["rating"].agg(["mean", "count"]).reset_index()
    agg.columns = ["movie_id", "rating_avg", "rating_count"]
    df = df.merge(agg, on="movie_id", how="left")
    df["rating_avg"] = df["rating_avg"].fillna(0.0).round(3)
    df["rating_count"] = df["rating_count"].fillna(0).astype(int)

    # Save cleanly (without non-serializable list column if needed, keep pipe-joined string)
    df_save = df.drop(columns=["genres_list"])
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_save.to_csv(PROCESSED_DIR / "movies_catalogue.csv", index=False)
    all_ratings.to_csv(PROCESSED_DIR / "ratings_clean.csv", index=False)
    logger.info(
        "Saved processed dataset: %d movies, %d ratings (%d movielens, %d synthetic)",
        len(df_save),
        len(all_ratings),
        (all_ratings["source"] == "movielens").sum(),
        (all_ratings["source"] == "synthetic").sum(),
    )
    return df_save, all_ratings
