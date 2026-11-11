"""Dataset ingestion for MovieLens Latest Small + Hollywood/Bollywood/Tollywood balancing."""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"
ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
ML_DIR = RAW_DIR / "ml-latest-small"
SEED_INDIAN_CSV = ROOT_DIR / "data" / "seed_indian_cinema.csv"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

YEAR_RE = re.compile(r"\s*\((\d{4})(?:[-–]\d{4})?\)\s*$")
LEADING_ARTICLE_RE = re.compile(r"^(.*),\s+(The|A|An)$", re.IGNORECASE)

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "AbsoluteCinemaBuilder/1.0 (https://github.com/absolute-cinema)"


def clean_movielens_title(raw_title: str) -> tuple[str, int | None]:
    """Extract release year and normalize 'Title, The (1999)' -> ('The Title', 1999)."""
    title = str(raw_title).strip()
    year: int | None = None
    match = YEAR_RE.search(title)
    if match:
        year = int(match.group(1))
        title = title[: match.start()].strip()
    # Strip trailing parenthetical alternate titles like '(a.k.a. ...)' only when restoring article
    art_match = LEADING_ARTICLE_RE.match(title)
    if art_match:
        title = f"{art_match.group(2)} {art_match.group(1).strip()}"
    return title, year


def download_movielens(force: bool = False) -> Path:
    """Download and extract MovieLens Latest Small if not already present."""
    if not force and (ML_DIR / "movies.csv").exists() and (ML_DIR / "ratings.csv").exists():
        logger.info("MovieLens dataset already present at %s", ML_DIR)
        return ML_DIR

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading MovieLens Latest Small from %s", MOVIELENS_URL)
    resp = httpx.get(MOVIELENS_URL, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(RAW_DIR)
    logger.info("Extracted MovieLens to %s", ML_DIR)
    return ML_DIR


def load_clean_movielens() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load, clean, deduplicate, and validate MovieLens CSVs."""
    download_movielens()
    movies = pd.read_csv(ML_DIR / "movies.csv")
    ratings = pd.read_csv(ML_DIR / "ratings.csv")
    links = pd.read_csv(ML_DIR / "links.csv")

    movies = movies.drop_duplicates(subset=["movieId"]).dropna(subset=["movieId", "title"])
    parsed = movies["title"].apply(clean_movielens_title)
    movies["clean_title"] = parsed.apply(lambda t: t[0])
    movies["year"] = parsed.apply(lambda t: t[1])
    movies["genres"] = movies["genres"].fillna("").astype(str)
    movies["industry"] = "hollywood"
    movies["language"] = "en"

    links = links.drop_duplicates(subset=["movieId"])
    links["imdb_id"] = links["imdbId"].apply(lambda x: f"tt{int(x):07d}" if pd.notna(x) else None)
    links["tmdb_id"] = links["tmdbId"].apply(lambda x: int(x) if pd.notna(x) else None)

    movies = movies.merge(links[["movieId", "imdb_id", "tmdb_id"]], on="movieId", how="left")

    ratings = ratings.dropna(subset=["userId", "movieId", "rating", "timestamp"]).copy()
    ratings["userId"] = ratings["userId"].astype(int)
    ratings["movieId"] = ratings["movieId"].astype(int)
    ratings["rating"] = ratings["rating"].astype(float)
    ratings["timestamp"] = ratings["timestamp"].astype(int)
    ratings = ratings[(ratings["rating"] >= 0.5) & (ratings["rating"] <= 5.0)]
    ratings = ratings.sort_values("timestamp").drop_duplicates(subset=["userId", "movieId"], keep="last")
    ratings["source"] = "movielens"
    return movies, ratings, links


def fetch_wikidata_indian_films(
    lang_qid: str,
    language_code: str,
    industry: str,
    limit: int = 550,
) -> list[dict[str, Any]]:
    """Fetch notable Hindi/Telugu films from Wikidata SPARQL with IMDb ID & enwiki sitelink."""
    query = f"""
    SELECT ?item ?itemLabel ?year ?duration ?imdb ?tmdb ?articleTitle WHERE {{
      {{
        SELECT DISTINCT ?item ?year ?duration ?imdb ?tmdb ?articleTitle WHERE {{
          ?item wdt:P31 wd:Q11424 ;
                wdt:P364 wd:{lang_qid} ;
                wdt:P345 ?imdb ;
                wdt:P577 ?pubdate .
          BIND(YEAR(?pubdate) AS ?year)
          FILTER(?year >= 1955 && ?year <= 2025)
          ?article schema:about ?item ;
                   schema:isPartOf <https://en.wikipedia.org/> ;
                   schema:name ?articleTitle .
          OPTIONAL {{ ?item wdt:P2047 ?duration . }}
          OPTIONAL {{ ?item wdt:P4947 ?tmdb . }}
        }}
        LIMIT {limit}
      }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    try:
        resp = httpx.get(WIKIDATA_SPARQL_URL, params={"query": query}, headers=headers, timeout=45)
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Wikidata query failed for %s: %s", industry, exc)
        return []

    records: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for row in bindings:
        title = row.get("itemLabel", {}).get("value", "").strip()
        if not title or title.startswith("Q") and title[1:].isdigit():
            continue
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        dur_val = row.get("duration", {}).get("value")
        runtime = int(float(dur_val)) if dur_val and float(dur_val) > 30 else None
        tmdb_val = row.get("tmdb", {}).get("value")
        tmdb_id = int(tmdb_val) if tmdb_val and str(tmdb_val).isdigit() else None
        records.append(
            {
                "title": title,
                "year": int(row["year"]["value"]) if "year" in row else None,
                "language": language_code,
                "genres": "",
                "industry": industry,
                "wikipedia_title": row.get("articleTitle", {}).get("value", title),
                "imdb_id": row.get("imdb", {}).get("value"),
                "tmdb_id": tmdb_id,
                "runtime": runtime,
                "wikidata_qid": row["item"]["value"].rsplit("/", 1)[-1],
            }
        )
    return records


def _stable_indian_id(industry: str, title: str, year: int | None) -> int:
    """Deterministic unique ID >= 900000 for non-MovieLens titles."""
    digest = hashlib.sha256(f"{industry}|{title.lower()}|{year}".encode()).hexdigest()
    return 900_000 + (int(digest[:8], 16) % 900_000)


def build_balanced_catalogue(
    hollywood_target: int = 1350,
    bollywood_target: int = 475,
    tollywood_target: int = 475,
    tmdb_api_key: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create balanced Hollywood + Bollywood + Tollywood catalogue and filter MovieLens ratings."""
    ml_movies, ml_ratings, _ = load_clean_movielens()
    counts = ml_ratings.groupby("movieId")["rating"].agg(["count", "mean"]).reset_index()
    ml_movies = ml_movies.merge(counts, on="movieId", how="left")
    ml_movies["ml_count"] = ml_movies["count"].fillna(0).astype(int)
    ml_movies["ml_mean"] = ml_movies["mean"].fillna(3.5).astype(float)
    ml_movies["_tkey"] = ml_movies["clean_title"].str.lower().str.strip()
    ml_movies = (
        ml_movies.sort_values("ml_count", ascending=False)
        .drop_duplicates(subset=["_tkey", "year"], keep="first")
        .drop(columns=["_tkey"])
    )

    # Top Hollywood titles by rating count, plus sparse titles (1-4 ratings) for content-fallback coverage
    sparse_quota = min(60, max(1, hollywood_target // 12))
    popular_ml = (
        ml_movies[ml_movies["ml_count"] >= 5]
        .sort_values(["ml_count", "ml_mean"], ascending=[False, False])
        .head(max(1, hollywood_target - sparse_quota))
    )
    sparse_ml = (
        ml_movies[(ml_movies["ml_count"] >= 1) & (ml_movies["ml_count"] <= 4) & ml_movies["imdb_id"].notna()]
        .sort_values("movieId")
        .head(sparse_quota)
    )
    selected_ml = (
        pd.concat([popular_ml, sparse_ml], ignore_index=True)
        .drop_duplicates("movieId")
        .drop(columns=["title"], errors="ignore")
        .rename(columns={"movieId": "movie_id", "clean_title": "title"})
    )
    selected_ml["wikipedia_title"] = None
    selected_ml["wikidata_qid"] = None
    selected_ml["runtime"] = None

    ml_ids = set(selected_ml["movie_id"].tolist())
    filtered_ml_ratings = ml_ratings[ml_ratings["movieId"].isin(ml_ids)].rename(
        columns={"userId": "user_id", "movieId": "movie_id"}
    )

    # Load curated Indian cinema seed CSV
    seed_df = pd.read_csv(SEED_INDIAN_CSV)
    seed_df["imdb_id"] = None
    seed_df["tmdb_id"] = None
    seed_df["runtime"] = None
    seed_df["wikidata_qid"] = None

    # Expand Bollywood and Tollywood via TMDB Discover (if key set) or Wikidata SPARQL
    extra_rows: list[dict[str, Any]] = []
    if tmdb_api_key:
        extra_rows.extend(_discover_tmdb_indian("hi", "bollywood", bollywood_target, tmdb_api_key))
        extra_rows.extend(_discover_tmdb_indian("te", "tollywood", tollywood_target, tmdb_api_key))

    if len([r for r in extra_rows if r["industry"] == "bollywood"]) < bollywood_target:
        extra_rows.extend(fetch_wikidata_indian_films("Q1568", "hi", "bollywood", limit=600))
    if len([r for r in extra_rows if r["industry"] == "tollywood"]) < tollywood_target:
        extra_rows.extend(fetch_wikidata_indian_films("Q8097", "te", "tollywood", limit=600))

    indian_df = pd.concat([seed_df, pd.DataFrame(extra_rows)], ignore_index=True)
    indian_df["title_key"] = indian_df["title"].str.lower().str.strip()
    indian_df = indian_df.drop_duplicates(subset=["industry", "title_key"], keep="first")

    bolly = indian_df[indian_df["industry"] == "bollywood"].head(bollywood_target)
    tolly = indian_df[indian_df["industry"] == "tollywood"].head(tollywood_target)
    indian_selected = pd.concat([bolly, tolly], ignore_index=True).drop(columns=["title_key"])

    # Assign collision-free deterministic IDs >= 900000
    used_ids = set(selected_ml["movie_id"].tolist())
    assigned_ids: list[int] = []
    for _, row in indian_selected.iterrows():
        yr = int(row["year"]) if pd.notna(row["year"]) else None
        cand = _stable_indian_id(str(row["industry"]), str(row["title"]), yr)
        while cand in used_ids:
            cand += 1
        used_ids.add(cand)
        assigned_ids.append(cand)
    indian_selected["movie_id"] = assigned_ids
    indian_selected["ml_count"] = 0
    indian_selected["ml_mean"] = 0.0

    cols = [
        "movie_id",
        "title",
        "year",
        "genres",
        "industry",
        "language",
        "imdb_id",
        "tmdb_id",
        "wikipedia_title",
        "wikidata_qid",
        "runtime",
        "ml_count",
        "ml_mean",
    ]
    catalogue = pd.concat(
        [selected_ml[cols], indian_selected[cols]],
        ignore_index=True,
    )
    catalogue["year"] = pd.to_numeric(catalogue["year"], errors="coerce").astype("Int64")
    catalogue["tmdb_id"] = pd.to_numeric(catalogue["tmdb_id"], errors="coerce").astype("Int64")
    catalogue["runtime"] = pd.to_numeric(catalogue["runtime"], errors="coerce").astype("Int64")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Built balanced catalogue: %d total (%s)",
        len(catalogue),
        catalogue["industry"].value_counts().to_dict(),
    )
    return catalogue, filtered_ml_ratings


def _discover_tmdb_indian(
    lang: str,
    industry: str,
    target: int,
    api_key: str,
) -> list[dict[str, Any]]:
    """Fetch popular Bollywood/Tollywood movies across genres via TMDB Discover API."""
    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    genres = [28, 12, 35, 80, 18, 14, 27, 9648, 10749, 878, 53, 10402]
    with httpx.Client(timeout=15) as client:
        for genre_id in genres:
            for page in (1, 2, 3):
                if len(results) >= target:
                    return results
                try:
                    resp = client.get(
                        "https://api.themoviedb.org/3/discover/movie",
                        params={
                            "api_key": api_key,
                            "with_original_language": lang,
                            "with_genres": genre_id,
                            "vote_count.gte": 15,
                            "sort_by": "popularity.desc",
                            "page": page,
                        },
                    )
                    resp.raise_for_status()
                    for item in resp.json().get("results", []):
                        tid = item.get("id")
                        if not tid or tid in seen_ids:
                            continue
                        seen_ids.add(tid)
                        rd = item.get("release_date") or ""
                        yr = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
                        results.append(
                            {
                                "title": item.get("title") or item.get("original_title"),
                                "year": yr,
                                "language": lang,
                                "genres": "",
                                "industry": industry,
                                "wikipedia_title": None,
                                "imdb_id": None,
                                "tmdb_id": tid,
                                "runtime": None,
                                "wikidata_qid": None,
                            }
                        )
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("TMDB discover error (%s, genre=%s): %s", lang, genre_id, exc)
                    break
    return results
