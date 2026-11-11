"""Idempotent database seed loader: `python -m app.services.seed`."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import SessionLocal
from app.models import Genre, Movie, MovieGenre, Rating, User
from app.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def seed_database(db: Session, load_historical_ratings: bool = True) -> dict[str, int]:
    """Load processed catalogue, genres, and ratings idempotently into PostgreSQL/SQLite."""
    settings = get_settings()
    data_dir = Path(settings.processed_data_dir)
    movies_path = data_dir / "movies_catalogue.csv"
    ratings_path = data_dir / "ratings_clean.csv"

    if not movies_path.exists():
        raise FileNotFoundError(f"Processed catalogue not found at {movies_path}. Run ml.src.train first.")

    existing_movies = db.scalar(select(func.count(Movie.id))) or 0
    added_movies = 0
    added_ratings = 0

    if existing_movies == 0:
        movies_df = pd.read_csv(movies_path)

        # 1. Seed genres idempotently
        all_genre_names: set[str] = set()
        for raw in movies_df["genres"].dropna().astype(str):
            for g in raw.split("|"):
                g_clean = g.strip()
                if g_clean:
                    all_genre_names.add(g_clean)

        genre_map: dict[str, Genre] = {g.name: g for g in db.scalars(select(Genre)).all()}
        for gname in sorted(all_genre_names):
            if gname not in genre_map:
                genre_obj = Genre(name=gname, slug=_slugify(gname))
                db.add(genre_obj)
                genre_map[gname] = genre_obj
        db.flush()

        # 2. Seed movies + movie_genres
        existing_movie_ids = set(db.scalars(select(Movie.id)).all())
        for _, row in movies_df.iterrows():
            mid = int(row["movie_id"])
            if mid in existing_movie_ids:
                continue
            genres_csv = str(row.get("genres") or "Drama")
            movie = Movie(
                id=mid,
                title=str(row["title"])[:255],
                year=int(row["year"]) if pd.notna(row.get("year")) else None,
                industry=str(row.get("industry") or "hollywood"),
                language=str(row.get("language") or "en"),
                imdb_id=str(row["imdb_id"]) if pd.notna(row.get("imdb_id")) else None,
                tmdb_id=int(row["tmdb_id"]) if pd.notna(row.get("tmdb_id")) else None,
                poster_url=str(row["poster_url"]) if pd.notna(row.get("poster_url")) else None,
                backdrop_url=str(row["backdrop_url"]) if pd.notna(row.get("backdrop_url")) else None,
                overview=str(row["overview"]) if pd.notna(row.get("overview")) else None,
                runtime=int(row["runtime"]) if pd.notna(row.get("runtime")) else None,
                release_date=str(row["release_date"]) if pd.notna(row.get("release_date")) else None,
                tmdb_rating=float(row["tmdb_rating"]) if pd.notna(row.get("tmdb_rating")) else None,
                director=str(row["director"])[:255] if pd.notna(row.get("director")) else None,
                cast=str(row["cast"]) if pd.notna(row.get("cast")) else None,
                genres_csv=genres_csv,
                dominant_color=str(row.get("dominant_color") or "#C35A1A"),
                accent_color=str(row.get("accent_color") or "#FFB45C"),
                shadow_color=str(row.get("shadow_color") or "#291207"),
                color_luminance=str(row.get("color_luminance") or "dark"),
                rating_avg=float(row.get("rating_avg") or 0.0),
                rating_count=int(row.get("rating_count") or 0),
            )
            db.add(movie)
            added_movies += 1
            for gname in dict.fromkeys(g.strip() for g in genres_csv.split("|") if g.strip()):
                if gname in genre_map:
                    db.add(MovieGenre(movie_id=mid, genre_id=genre_map[gname].id))
        db.commit()

        # 3. Seed historical CF users + historical ratings (only if ratings table is empty)
        if load_historical_ratings and ratings_path.exists():
            existing_ratings = db.scalar(select(func.count(Rating.id))) or 0
            if existing_ratings == 0:
                ratings_df = pd.read_csv(ratings_path)
                existing_uids = set(db.scalars(select(User.id)).all())
                unique_uids = sorted(int(u) for u in ratings_df["user_id"].unique())
                # Historical CF profiles have no password and cannot authenticate
                user_rows = [
                    {
                        "id": uid,
                        "email": f"archive_{uid}@historical.local",
                        "username": f"archive_viewer_{uid}",
                        "password_hash": None,
                        "role": "historical",
                        "is_active": False,
                        "preferred_genres": "",
                        "preferred_industries": "",
                        "onboarding_completed": True,
                    }
                    for uid in unique_uids
                    if uid not in existing_uids
                ]
                if user_rows:
                    db.bulk_insert_mappings(User.__mapper__, user_rows)
                    db.flush()

                valid_movie_ids = set(db.scalars(select(Movie.id)).all())
                rating_rows = []
                for _, r in ratings_df.iterrows():
                    mid = int(r["movie_id"])
                    if mid not in valid_movie_ids:
                        continue
                    rating_rows.append(
                        {
                            "user_id": int(r["user_id"]),
                            "movie_id": mid,
                            "rating": float(r["rating"]),
                            "source": str(r["source"]),
                            "rated_at": datetime.fromtimestamp(int(r["timestamp"]), tz=timezone.utc),
                        }
                    )
                for start in range(0, len(rating_rows), 10_000):
                    db.bulk_insert_mappings(Rating.__mapper__, rating_rows[start : start + 10_000])
                    added_ratings += len(rating_rows[start : start + 10_000])
                db.commit()

    # 4. Seed bootstrap admin account ONLY if ADMIN_PASSWORD is provided in env and missing
    if settings.admin_password and len(settings.admin_password) >= 8:
        admin_exists = db.scalar(select(User).where(User.email == settings.admin_email))
        if not admin_exists:
            # Ensure autoincrement sequences stay above historical user IDs
            max_uid = db.scalar(select(func.max(User.id))) or 0
            next_uid = max(max_uid + 1, 20_001)
            db.add(
                User(
                    id=next_uid,
                    email=settings.admin_email,
                    username="curator",
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                    is_active=True,
                    preferred_genres="Drama|Sci-Fi|Thriller",
                    preferred_industries="hollywood,bollywood,tollywood",
                    onboarding_completed=True,
                )
            )
            db.commit()

    # Sync PostgreSQL sequences when explicit IDs were inserted
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), "
                "GREATEST(COALESCE((SELECT MAX(id) FROM users), 20000), 20000))"
            )
        )
        db.commit()

    logger.info(
        "Seed complete: existing_movies=%d, added_movies=%d, added_ratings=%d",
        existing_movies,
        added_movies,
        added_ratings,
    )
    return {"added_movies": added_movies, "added_ratings": added_ratings}


def main() -> None:
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
