"""Initial relational schema for ABSOLUTE CINEMA.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preferred_genres", sa.Text(), nullable=False, server_default=""),
        sa.Column("preferred_industries", sa.Text(), nullable=False, server_default=""),
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)

    op.create_table(
        "genres",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_genres_name", "genres", ["name"], unique=True)
    op.create_index("ix_genres_slug", "genres", ["slug"], unique=True)

    op.create_table(
        "movies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("industry", sa.String(length=32), nullable=False, server_default="hollywood"),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
        sa.Column("imdb_id", sa.String(length=24), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("poster_url", sa.Text(), nullable=True),
        sa.Column("backdrop_url", sa.Text(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("release_date", sa.String(length=32), nullable=True),
        sa.Column("tmdb_rating", sa.Float(), nullable=True),
        sa.Column("director", sa.String(length=255), nullable=True),
        sa.Column("cast", sa.Text(), nullable=True),
        sa.Column("genres_csv", sa.String(length=255), nullable=False, server_default="Drama"),
        sa.Column("dominant_color", sa.String(length=16), nullable=False, server_default="#C35A1A"),
        sa.Column("accent_color", sa.String(length=16), nullable=False, server_default="#FFB45C"),
        sa.Column("shadow_color", sa.String(length=16), nullable=False, server_default="#291207"),
        sa.Column("color_luminance", sa.String(length=16), nullable=False, server_default="dark"),
        sa.Column("rating_avg", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movies_title", "movies", ["title"])
    op.create_index("ix_movies_year", "movies", ["year"])
    op.create_index("ix_movies_industry", "movies", ["industry"])
    op.create_index("ix_movies_language", "movies", ["language"])
    op.create_index("ix_movies_industry_year", "movies", ["industry", "year"])
    op.create_index("ix_movies_rating_avg_count", "movies", ["rating_avg", "rating_count"])

    op.create_table(
        "movie_genres",
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("genre_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["genre_id"], ["genres.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("movie_id", "genre_id"),
    )
    op.create_index("ix_movie_genres_genre_id", "movie_genres", ["genre_id"])

    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="user"),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating >= 0.5 AND rating <= 5.0", name="ck_ratings_range"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "movie_id", name="uq_ratings_user_movie"),
    )
    op.create_index("ix_ratings_user_id", "ratings", ["user_id"])
    op.create_index("ix_ratings_movie_id", "ratings", ["movie_id"])

    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "movie_id", name="uq_watchlist_user_movie"),
    )
    op.create_index("ix_watchlist_user_id", "watchlist", ["user_id"])
    op.create_index("ix_watchlist_movie_id", "watchlist", ["movie_id"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=128), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_versions_version", "model_versions", ["version"], unique=True)

    # PostgreSQL trigram GIN index for typo-tolerant fast title search
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute("CREATE INDEX ix_movies_title_trgm ON movies USING gin (title gin_trgm_ops)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_movies_title_trgm")

    op.drop_index("ix_model_versions_version", table_name="model_versions")
    op.drop_table("model_versions")
    op.drop_index("ix_watchlist_movie_id", table_name="watchlist")
    op.drop_index("ix_watchlist_user_id", table_name="watchlist")
    op.drop_table("watchlist")
    op.drop_index("ix_ratings_movie_id", table_name="ratings")
    op.drop_index("ix_ratings_user_id", table_name="ratings")
    op.drop_table("ratings")
    op.drop_index("ix_movie_genres_genre_id", table_name="movie_genres")
    op.drop_table("movie_genres")
    op.drop_index("ix_movies_rating_avg_count", table_name="movies")
    op.drop_index("ix_movies_industry_year", table_name="movies")
    op.drop_index("ix_movies_language", table_name="movies")
    op.drop_index("ix_movies_industry", table_name="movies")
    op.drop_index("ix_movies_year", table_name="movies")
    op.drop_index("ix_movies_title", table_name="movies")
    op.drop_table("movies")
    op.drop_index("ix_genres_slug", table_name="genres")
    op.drop_index("ix_genres_name", table_name="genres")
    op.drop_table("genres")
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
