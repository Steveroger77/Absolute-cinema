"""Metadata enrichment via TMDB API (primary when TMDB_API_KEY set) and Wikidata/Wikipedia fallback."""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT_DIR / "data" / "processed" / "enrichment_cache.json"
USER_AGENT = "AbsoluteCinemaBuilder/1.0 (https://github.com/absolute-cinema)"

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG_BASE = "https://image.tmdb.org/t/p"

# Infer clean genre labels from Wikipedia summary sentence keywords when Wikidata genre is empty
SUMMARY_GENRE_HINTS: list[tuple[str, str]] = [
    (r"\bsci-fi\b|\bscience fiction\b|\bspacecraft\b|\bdystopian\b|\btime travel\b", "Sci-Fi"),
    (r"\bhorror\b|\bsupernatural\b|\bghost\b|\bhaunted\b|\bdemon\b", "Horror"),
    (r"\bthriller\b|\bsuspense\b|\bconspiracy\b|\bmurder mystery\b", "Thriller"),
    (r"\bcrime\b|\bgangster\b|\bmafia\b|\bmob\b|\bheist\b|\bdetective\b", "Crime"),
    (r"\bmystery\b|\bwhodunit\b|\binvestigat", "Mystery"),
    (r"\bcomedy\b|\bhumorous\b|\bsatire\b|\brom-com\b|\bfarce\b", "Comedy"),
    (r"\bromantic\b|\bromance\b|\blove story\b", "Romance"),
    (r"\bfantasy\b|\bmythological\b|\bfolklore\b|\bmagical\b", "Fantasy"),
    (r"\baction\b|\bmartial arts\b|\bvigilante\b|\bsuperhero\b", "Action"),
    (r"\badventure\b|\bexpedition\b|\bquest\b", "Adventure"),
    (r"\bmusical\b|\bsongs\b|\bdance\b", "Musical"),
    (r"\bwar\b|\bbattle\b|\bmilitary\b|\bsoldier\b", "War"),
    (r"\banimated\b|\banimation\b", "Animation"),
    (r"\bfamily\b|\bchildren\b", "Family"),
    (r"\bdrama\b|\bbiographical\b|\bcoming-of-age\b", "Drama"),
]


def _load_cache() -> dict[str, dict[str, Any]]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean_wikimedia_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.split("?", 1)[0]


def _batch_wikidata_by_imdb(imdb_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Query Wikidata SPARQL in chunks of 120 IMDb IDs for enwiki titles, duration, directors, cast."""
    out: dict[str, dict[str, Any]] = {}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    chunk_size = 120
    with httpx.Client(timeout=35, headers=headers) as client:
        for idx in range(0, len(imdb_ids), chunk_size):
            chunk = [i for i in imdb_ids[idx : idx + chunk_size] if i]
            if not chunk:
                continue
            values = " ".join(f'"{i}"' for i in chunk)
            query = f"""
            SELECT ?imdb ?articleTitle (SAMPLE(?dur) AS ?duration)
                   (GROUP_CONCAT(DISTINCT ?dirLabel; separator=", ") AS ?directors)
                   (GROUP_CONCAT(DISTINCT ?castLabel; separator=", ") AS ?cast)
            WHERE {{
              VALUES ?imdb {{ {values} }}
              ?item wdt:P345 ?imdb .
              OPTIONAL {{
                ?article schema:about ?item ;
                         schema:isPartOf <https://en.wikipedia.org/> ;
                         schema:name ?articleTitle .
              }}
              OPTIONAL {{ ?item wdt:P2047 ?dur . }}
              OPTIONAL {{ ?item wdt:P57 ?d . ?d rdfs:label ?dirLabel . FILTER(LANG(?dirLabel) = "en") }}
              OPTIONAL {{ ?item wdt:P161 ?c . ?c rdfs:label ?castLabel . FILTER(LANG(?castLabel) = "en") }}
            }}
            GROUP BY ?imdb ?articleTitle
            """
            try:
                resp = client.get(WIKIDATA_SPARQL, params={"query": query})
                resp.raise_for_status()
                for row in resp.json().get("results", {}).get("bindings", []):
                    imdb = row["imdb"]["value"]
                    dur = row.get("duration", {}).get("value")
                    cast_str = row.get("cast", {}).get("value", "")
                    cast_list = [c.strip() for c in cast_str.split(",") if c.strip()][:5]
                    out[imdb] = {
                        "wikipedia_title": row.get("articleTitle", {}).get("value"),
                        "runtime": int(float(dur)) if dur and float(dur) > 25 else None,
                        "director": row.get("directors", {}).get("value", "")[:120] or None,
                        "cast": ", ".join(cast_list) or None,
                    }
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Wikidata IMDb chunk failed (%s): %s", idx, exc)
    return out


def _batch_wikidata_by_qid(qids: list[str]) -> dict[str, dict[str, Any]]:
    """Query Wikidata SPARQL in chunks of 100 QIDs for genres, directors, and cast of Indian films."""
    out: dict[str, dict[str, Any]] = {}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
    chunk_size = 100
    with httpx.Client(timeout=35, headers=headers) as client:
        for idx in range(0, len(qids), chunk_size):
            chunk = [q for q in qids[idx : idx + chunk_size] if q]
            if not chunk:
                continue
            values = " ".join(f"wd:{q}" for q in chunk)
            query = f"""
            SELECT ?item (GROUP_CONCAT(DISTINCT ?gLabel; separator="|") AS ?genres)
                   (GROUP_CONCAT(DISTINCT ?dirLabel; separator=", ") AS ?directors)
                   (GROUP_CONCAT(DISTINCT ?castLabel; separator=", ") AS ?cast)
            WHERE {{
              VALUES ?item {{ {values} }}
              OPTIONAL {{ ?item wdt:P136 ?g . ?g rdfs:label ?gLabel . FILTER(LANG(?gLabel) = "en") }}
              OPTIONAL {{ ?item wdt:P57 ?d . ?d rdfs:label ?dirLabel . FILTER(LANG(?dirLabel) = "en") }}
              OPTIONAL {{ ?item wdt:P161 ?c . ?c rdfs:label ?castLabel . FILTER(LANG(?castLabel) = "en") }}
            }}
            GROUP BY ?item
            """
            try:
                resp = client.get(WIKIDATA_SPARQL, params={"query": query})
                resp.raise_for_status()
                for row in resp.json().get("results", {}).get("bindings", []):
                    qid = row["item"]["value"].rsplit("/", 1)[-1]
                    cast_str = row.get("cast", {}).get("value", "")
                    cast_list = [c.strip() for c in cast_str.split(",") if c.strip()][:5]
                    out[qid] = {
                        "genres": row.get("genres", {}).get("value", ""),
                        "director": row.get("directors", {}).get("value", "")[:120] or None,
                        "cast": ", ".join(cast_list) or None,
                    }
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Wikidata QID chunk failed (%s): %s", idx, exc)
    return out


def _batch_wikipedia_media(titles: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch poster thumbnails (`pilicense=any`) and plot summaries in batches of 50 Wikipedia pages."""
    out: dict[str, dict[str, Any]] = {}
    headers = {"User-Agent": USER_AGENT}
    unique_titles = list(dict.fromkeys(t for t in titles if t))
    with httpx.Client(timeout=25, headers=headers) as client:
        for idx in range(0, len(unique_titles), 50):
            batch = unique_titles[idx : idx + 50]
            try:
                resp = client.get(
                    WIKIPEDIA_API,
                    params={
                        "action": "query",
                        "prop": "pageimages|extracts",
                        "pilicense": "any",
                        "pithumbsize": 500,
                        "exintro": 1,
                        "explaintext": 1,
                        "exsentences": 3,
                        "titles": "|".join(batch),
                        "format": "json",
                        "redirects": 1,
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("query", {})
                norm_map = {n["from"]: n["to"] for n in data.get("normalized", [])}
                redir_map = {r["from"]: r["to"] for r in data.get("redirects", [])}
                by_title: dict[str, dict[str, Any]] = {}
                for page in data.get("pages", {}).values():
                    ptitle = page.get("title")
                    if not ptitle or "missing" in page:
                        continue
                    thumb = _clean_wikimedia_url((page.get("thumbnail") or {}).get("source"))
                    ext = (page.get("extract") or "").strip()
                    by_title[ptitle] = {"poster_url": thumb, "overview": ext[:600] if ext else None}
                for orig in batch:
                    cur = norm_map.get(orig, orig)
                    cur = redir_map.get(cur, cur)
                    if cur in by_title:
                        out[orig] = by_title[cur]
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Wikipedia batch failed (%s): %s", idx, exc)
    return out


def _enrich_via_tmdb(df: pd.DataFrame, api_key: str, cache: dict[str, dict[str, Any]]) -> None:
    """Populate enrichment cache using official TMDB API for rows having tmdb_id."""
    todo = [
        (str(int(row["movie_id"])), int(row["tmdb_id"]))
        for _, row in df.iterrows()
        if pd.notna(row["tmdb_id"]) and str(int(row["movie_id"])) not in cache
    ]
    if not todo:
        return

    def fetch_one(movie_key: str, tmdb_id: int) -> tuple[str, dict[str, Any] | None]:
        try:
            r = httpx.get(
                f"{TMDB_BASE}/movie/{tmdb_id}",
                params={"api_key": api_key, "append_to_response": "credits"},
                timeout=12,
            )
            if r.status_code != 200:
                return movie_key, None
            d = r.json()
            credits = d.get("credits", {})
            directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"][:2]
            cast = [c["name"] for c in credits.get("cast", [])][:5]
            genres = "|".join(g["name"] for g in d.get("genres", []) if g.get("name"))
            poster_path = d.get("poster_path")
            backdrop_path = d.get("backdrop_path")
            return movie_key, {
                "poster_url": f"{TMDB_IMG_BASE}/w500{poster_path}" if poster_path else None,
                "backdrop_url": f"{TMDB_IMG_BASE}/w1280{backdrop_path}" if backdrop_path else None,
                "overview": (d.get("overview") or "")[:600] or None,
                "runtime": d.get("runtime") or None,
                "language": d.get("original_language") or None,
                "release_date": d.get("release_date") or None,
                "tmdb_rating": d.get("vote_average") or None,
                "director": ", ".join(directors) or None,
                "cast": ", ".join(cast) or None,
                "genres": genres or None,
                "poster_source": "tmdb",
            }
        except (httpx.HTTPError, ValueError):
            return movie_key, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_one, mk, tid) for mk, tid in todo]
        for fut in as_completed(futures):
            mk, data = fut.result()
            if data:
                cache[mk] = data


def _infer_genres_from_text(text: str | None) -> str:
    if not text:
        return "Drama"
    low = text.lower()
    found: list[str] = []
    for pattern, label in SUMMARY_GENRE_HINTS:
        if re.search(pattern, low) and label not in found:
            found.append(label)
        if len(found) >= 3:
            break
    return "|".join(found) if found else "Drama"


def enrich_catalogue(
    catalogue: pd.DataFrame,
    tmdb_api_key: str | None = None,
) -> pd.DataFrame:
    """Enrich catalogue with poster URLs, overview, runtime, director, cast, and metadata."""
    cache = _load_cache()
    api_key = tmdb_api_key if tmdb_api_key is not None else os.getenv("TMDB_API_KEY", "").strip()

    if api_key:
        logger.info("Enriching catalogue via TMDB API...")
        _enrich_via_tmdb(catalogue, api_key, cache)

    # Identify rows not yet richly populated in cache
    missing_mask = ~catalogue["movie_id"].astype(str).isin(cache.keys())
    todo_df = catalogue[missing_mask]

    if not todo_df.empty:
        logger.info("Enriching %d titles via Wikidata + Wikipedia open APIs...", len(todo_df))
        hollywood_imdbs = (
            todo_df[todo_df["imdb_id"].notna() & todo_df["wikipedia_title"].isna()]["imdb_id"]
            .astype(str)
            .tolist()
        )
        wd_imdb_info = _batch_wikidata_by_imdb(hollywood_imdbs) if hollywood_imdbs else {}

        indian_qids = todo_df[todo_df["wikidata_qid"].notna()]["wikidata_qid"].astype(str).tolist()
        wd_qid_info = _batch_wikidata_by_qid(indian_qids) if indian_qids else {}

        wiki_titles: list[str] = []
        row_wiki_title: dict[int, str] = {}
        for _, row in todo_df.iterrows():
            mid = int(row["movie_id"])
            wtitle = row.get("wikipedia_title")
            if pd.isna(wtitle) or not wtitle:
                imdb = row.get("imdb_id")
                if pd.notna(imdb) and imdb in wd_imdb_info:
                    wtitle = wd_imdb_info[imdb].get("wikipedia_title")
            if not wtitle and pd.notna(row.get("title")):
                yr = row.get("year")
                wtitle = f"{row['title']} ({int(yr)} film)" if pd.notna(yr) else str(row["title"])
            if wtitle:
                row_wiki_title[mid] = str(wtitle)
                wiki_titles.append(str(wtitle))

        wp_media = _batch_wikipedia_media(wiki_titles)

        for _, row in todo_df.iterrows():
            mid = int(row["movie_id"])
            imdb = row.get("imdb_id")
            qid = row.get("wikidata_qid")
            wd = wd_imdb_info.get(str(imdb), {}) if pd.notna(imdb) else {}
            wd_q = wd_qid_info.get(str(qid), {}) if pd.notna(qid) else {}
            wtitle = row_wiki_title.get(mid, "")
            wp = wp_media.get(wtitle, {})

            overview = wp.get("overview")
            if not overview:
                yr_str = f"{int(row['year'])} " if pd.notna(row.get("year")) else ""
                ind_str = str(row.get("industry", "cinema")).title()
                overview = f"A {yr_str}{ind_str} feature film titled {row['title']}."

            raw_genres = str(row.get("genres") or "").strip()
            if not raw_genres:
                raw_genres = str(wd_q.get("genres") or "").strip()
            if not raw_genres:
                raw_genres = _infer_genres_from_text(overview)

            runtime = row.get("runtime")
            if pd.isna(runtime) or not runtime:
                runtime = wd.get("runtime")
            if not runtime:
                runtime = 142 if row.get("industry") in ("bollywood", "tollywood") else 112

            ml_mean = float(row.get("ml_mean") or 0.0)
            est_tmdb_rating = round(min(9.2, max(5.6, ml_mean * 1.85)), 1) if ml_mean > 0 else None

            cache[str(mid)] = {
                "poster_url": wp.get("poster_url"),
                "backdrop_url": None,
                "overview": overview,
                "runtime": int(runtime),
                "language": str(row.get("language") or "en"),
                "release_date": f"{int(row['year'])}-01-01" if pd.notna(row.get("year")) else None,
                "tmdb_rating": est_tmdb_rating,
                "director": wd.get("director") or wd_q.get("director"),
                "cast": wd.get("cast") or wd_q.get("cast"),
                "genres": raw_genres,
                "poster_source": "wikimedia" if wp.get("poster_url") else "typographic",
            }
        _save_cache(cache)

    enriched = catalogue.copy()
    for col in [
        "poster_url",
        "backdrop_url",
        "overview",
        "director",
        "cast",
        "release_date",
        "poster_source",
    ]:
        enriched[col] = enriched["movie_id"].astype(str).map(lambda k, c=col: cache.get(k, {}).get(c))

    enriched["runtime"] = enriched.apply(
        lambda r: cache.get(str(int(r["movie_id"])), {}).get("runtime") or r.get("runtime") or 115,
        axis=1,
    ).astype(int)
    enriched["tmdb_rating"] = (
        enriched["movie_id"].astype(str).map(lambda k: cache.get(k, {}).get("tmdb_rating"))
    )
    enriched["genres"] = enriched.apply(
        lambda r: (
            str(r["genres"]).strip()
            if pd.notna(r["genres"]) and str(r["genres"]).strip()
            else (cache.get(str(int(r["movie_id"])), {}).get("genres") or "Drama")
        ),
        axis=1,
    )
    logger.info(
        "Enrichment complete: %d/%d titles have external poster URLs",
        enriched["poster_url"].notna().sum(),
        len(enriched),
    )
    return enriched
