"""Comprehensive integration and security tests for the ABSOLUTE CINEMA FastAPI backend."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Genre, Movie, MovieGenre, User
from app.security import hash_password
from app.services.recommender_service import recommender_service


@pytest.fixture(scope="module")
def test_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("db") / "test_cinema.db"


@pytest.fixture(scope="module")
def client(test_db_path: Path):
    engine = create_engine(
        f"sqlite:///{test_db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    # Seed minimal realistic multi-industry movies & genres matching trained model IDs
    db = TestingSessionLocal()
    try:
        # Load trained model if available; else use ML test fixture model
        artifacts_dir = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
        if list(artifacts_dir.glob("model_v*.joblib")):
            recommender_service.load_model()
        else:
            from ml.src.content_fallback import ContentFallbackModel
            from ml.src.item_cf import ItemBasedCF
            from ml.src.loader import RecommenderEngine
            from ml.src.matrix import build_sparse_matrix
            from ml.src.popular import BayesianPopularityModel
            from ml.src.user_cf import HybridCF, UserBasedCF
            from ml.tests.test_ml import _sample_catalogue_and_ratings

            cats, rats = _sample_catalogue_and_ratings()
            bundle = build_sparse_matrix(rats, movie_ids=cats["movie_id"].tolist())
            icf = ItemBasedCF(top_n=10, shrinkage=2.0).fit(bundle)
            ucf = UserBasedCF(top_m=10, shrinkage=2.0).fit(bundle)
            hyb = HybridCF(item_cf=icf, user_cf=ucf, alpha=0.65)
            recommender_service._engine = RecommenderEngine(
                artifact={
                    "version": "test",
                    "alpha": 0.65,
                    "min_rating_count": 5,
                    "hybrid": hyb,
                    "item_cf": icf,
                    "user_cf": ucf,
                    "content": ContentFallbackModel().fit(cats),
                    "popular": BayesianPopularityModel().fit(cats, rats),
                    "catalogue": cats,
                },
                version="test",
                sha256="testsha",
            )

        # Seed top 80 Hollywood + 40 Bollywood + 40 Tollywood movies from the loaded engine catalogue
        cat_df = recommender_service._engine.catalogue
        has_rc = "rating_count" in cat_df.columns
        holly = cat_df[cat_df["industry"] == "hollywood"]
        bolly = cat_df[cat_df["industry"] == "bollywood"]
        tolly = cat_df[cat_df["industry"] == "tollywood"]
        if has_rc:
            holly = holly.sort_values("rating_count", ascending=False)
            bolly = bolly.sort_values("rating_count", ascending=False)
            tolly = tolly.sort_values("rating_count", ascending=False)
        holly = holly.head(80)
        bolly = bolly.head(40)
        tolly = tolly.head(40)
        import pandas as pd

        sample_df = pd.concat([holly, bolly, tolly], ignore_index=True)

        genre_objs: dict[str, Genre] = {}
        for _, r in sample_df.iterrows():
            gcsv = str(r.get("genres") or "Drama")
            m = Movie(
                id=int(r["movie_id"]),
                title=str(r["title"]),
                year=int(r["year"]) if str(r.get("year", "")).isdigit() else 2020,
                industry=str(r["industry"]),
                language=str(r["language"]),
                genres_csv=gcsv,
                overview=str(r.get("overview") or "Cinema feature"),
                runtime=130,
                dominant_color="#C35A1A",
                accent_color="#FFB45C",
                shadow_color="#291207",
                color_luminance="dark",
                rating_avg=float(r.get("rating_avg") or 4.0),
                rating_count=int(r.get("rating_count") or 10),
            )
            db.add(m)
            for gname in dict.fromkeys(g.strip() for g in gcsv.split("|") if g.strip()):
                if gname not in genre_objs:
                    g = Genre(name=gname, slug=gname.lower().replace(" ", "-"))
                    db.add(g)
                    db.flush()
                    genre_objs[gname] = g
                db.add(MovieGenre(movie_id=m.id, genre_id=genre_objs[gname].id))

        admin = User(
            id=20001,
            email="admin@cinema-app.org",
            username="admin_curator",
            password_hash=hash_password("StrongAdminPass123!"),
            role="admin",
            is_active=True,
            onboarding_completed=True,
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()

    def override_get_db():
        s = TestingSessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_health_and_security_headers(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["database"] == "ok"
    assert body["model_loaded"] is True
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in res.headers


def test_auth_lifecycle_refresh_rotation_and_reuse_detection(client: TestClient) -> None:
    # Guest session check returns 200 without 401 console noise
    guest_sess = client.get("/api/auth/session")
    assert guest_sess.status_code == 200
    assert guest_sess.json() == {"has_session": False}

    # Register
    r = client.post(
        "/api/auth/register",
        json={"email": "viewer1@cinema-app.org", "username": "viewer1", "password": "CinemaPassword123!"},
    )
    assert r.status_code == 201
    assert client.get("/api/auth/session").json() == {"has_session": True}
    data = r.json()
    token1 = data["access_token"]
    assert data["user"]["role"] == "user"
    assert "ac_refresh_token" in r.cookies
    old_refresh = r.cookies["ac_refresh_token"]

    # Duplicate email conflict
    dup = client.post(
        "/api/auth/register",
        json={"email": "viewer1@cinema-app.org", "username": "viewer1b", "password": "CinemaPassword123!"},
    )
    assert dup.status_code == 409

    # Protected /me check
    assert client.get("/api/auth/me").status_code == 401
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token1}"})
    assert me.status_code == 200
    assert me.json()["email"] == "viewer1@cinema-app.org"

    # Generic error message on bad login
    bad_email = client.post("/api/auth/login", json={"email": "nobody@cinema-app.org", "password": "x"})
    bad_pw = client.post("/api/auth/login", json={"email": "viewer1@cinema-app.org", "password": "wrong"})
    assert bad_email.status_code == 401
    assert bad_pw.status_code == 401
    assert bad_email.json()["error"]["message"] == bad_pw.json()["error"]["message"]

    # Rotate refresh token
    ref = client.post("/api/auth/refresh")
    assert ref.status_code == 200
    assert "ac_refresh_token" in ref.cookies
    assert ref.cookies["ac_refresh_token"] != old_refresh

    # Replay the old revoked refresh token -> must reject & revoke session family
    client.cookies.set("ac_refresh_token", old_refresh)
    replay = client.post("/api/auth/refresh")
    assert replay.status_code == 401


def test_catalogue_search_ratings_watchlist_and_recommendations(client: TestClient) -> None:
    # Login fresh user B
    reg = client.post(
        "/api/auth/register",
        json={"email": "viewer2@cinema-app.org", "username": "viewer2", "password": "CinemaPassword123!"},
    )
    assert reg.status_code == 201
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    # Onboarding cold-start preferences
    onb = client.put(
        "/api/auth/onboarding",
        json={"preferred_genres": ["Action", "Drama"], "preferred_industries": ["tollywood", "bollywood"]},
        headers=headers,
    )
    assert onb.status_code == 200
    assert onb.json()["onboarding_completed"] is True

    # Cold-start recommendations before rating anything
    cold_recs = client.get("/api/recommendations/me?k=5", headers=headers)
    assert cold_recs.status_code == 200
    assert cold_recs.json()["strategy"] == "onboarding_cold_start"
    assert len(cold_recs.json()["items"]) >= 1

    # List movies, trending, genres, search, detail, SVG fallback
    movies_res = client.get("/api/movies?page=1&page_size=5")
    assert movies_res.status_code == 200
    movie_list = movies_res.json()["items"]
    assert len(movie_list) >= 3
    first_id = movie_list[0]["id"]
    first_title = movie_list[0]["title"]

    search_res = client.get(f"/api/movies/search?q={first_title[:4]}")
    assert search_res.status_code == 200
    assert any(m["id"] == first_id for m in search_res.json())

    svg_res = client.get(f"/api/posters/{first_id}.svg")
    assert svg_res.status_code == 200
    assert "image/svg+xml" in svg_res.headers["content-type"]
    assert "<svg" in svg_res.text

    # Validation failure on invalid rating step
    bad_rate = client.put(f"/api/ratings/{first_id}", json={"rating": 3.3}, headers=headers)
    assert bad_rate.status_code == 422
    assert bad_rate.json()["error"]["code"] == "validation_error"

    # Upsert rating -> personalized recommendations -> delete rating
    rate_ok = client.put(f"/api/ratings/{first_id}", json={"rating": 5.0}, headers=headers)
    assert rate_ok.status_code == 200
    assert rate_ok.json()["rating"] == 5.0

    pers_recs = client.get("/api/recommendations/me?k=5", headers=headers)
    assert pers_recs.status_code == 200
    assert pers_recs.json()["strategy"] == "personalized_hybrid_cf"

    sim_res = client.get(f"/api/recommendations/similar/{first_id}?k=4")
    assert sim_res.status_code == 200

    genre_res = client.get("/api/recommendations/genre/Action?k=6")
    assert genre_res.status_code == 200

    trending_res = client.get("/api/movies/trending?limit=10")
    assert trending_res.status_code == 200
    assert len(trending_res.json()) >= 1

    genres_res = client.get("/api/genres")
    assert genres_res.status_code == 200
    assert len(genres_res.json()) >= 1

    detail_res = client.get(f"/api/movies/{first_id}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["user_rating"] == 5.0

    filtered_res = client.get("/api/movies?industry=tollywood&sort=rating&page=1&page_size=5")
    assert filtered_res.status_code == 200

    fuzzy_res = client.get(f"/api/movies/search?q={first_title[:-1]}")
    assert fuzzy_res.status_code == 200

    my_ratings_res = client.get("/api/ratings/me", headers=headers)
    assert my_ratings_res.status_code == 200
    assert len(my_ratings_res.json()) == 1

    # Watchlist add, list, remove
    wl_add = client.post(f"/api/watchlist/{first_id}", headers=headers)
    assert wl_add.status_code == 201
    wl_list = client.get("/api/watchlist/me", headers=headers)
    assert len(wl_list.json()) == 1
    wl_del = client.delete(f"/api/watchlist/{first_id}", headers=headers)
    assert wl_del.status_code == 204

    del_rate = client.delete(f"/api/ratings/{first_id}", headers=headers)
    assert del_rate.status_code == 204

    # Logout revokes refresh cookie
    out = client.post("/api/auth/logout")
    assert out.status_code == 204


def test_admin_role_gating_and_model_info(client: TestClient) -> None:
    info = client.get("/api/model/info")
    assert info.status_code == 200
    assert info.json()["loaded"] is True

    # Normal user forbidden from admin endpoint
    u_login = client.post(
        "/api/auth/login",
        json={"email": "viewer2@cinema-app.org", "password": "CinemaPassword123!"},
    )
    u_headers = {"Authorization": f"Bearer {u_login.json()['access_token']}"}
    assert client.post("/api/admin/model/reload", headers=u_headers).status_code == 403

    # Admin user succeeds (when artifact exists on disk)
    a_login = client.post(
        "/api/auth/login",
        json={"email": "admin@cinema-app.org", "password": "StrongAdminPass123!"},
    )
    assert a_login.status_code == 200
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}
    artifacts_dir = Path(__file__).resolve().parents[2] / "ml" / "artifacts"
    if list(artifacts_dir.glob("model_v*.joblib")):
        reload_res = client.post("/api/admin/model/reload", headers=a_headers)
        assert reload_res.status_code == 200


def test_alembic_upgrade_and_downgrade_roundtrip(tmp_path: Path) -> None:
    db_file = tmp_path / "alembic_roundtrip.db"
    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
    try:
        from app.config import get_settings

        get_settings.cache_clear()
        command.upgrade(alembic_cfg, "head")
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")
    finally:
        if prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_db_url
        get_settings.cache_clear()


def test_seed_database_idempotent(tmp_path: Path) -> None:
    import pandas as pd

    from app.config import get_settings
    from app.services.seed import seed_database

    proc = tmp_path / "proc"
    proc.mkdir()
    pd.DataFrame(
        [
            {
                "movie_id": 101,
                "title": "Sample Film",
                "year": 2021,
                "industry": "hollywood",
                "language": "en",
                "genres": "Drama|Action",
                "runtime": 120,
                "dominant_color": "#C35A1A",
                "accent_color": "#FFB45C",
                "shadow_color": "#291207",
                "color_luminance": "dark",
                "rating_avg": 4.2,
                "rating_count": 10,
            }
        ]
    ).to_csv(proc / "movies_catalogue.csv", index=False)
    pd.DataFrame(
        [{"user_id": 501, "movie_id": 101, "rating": 4.5, "timestamp": 1700000000, "source": "movielens"}]
    ).to_csv(proc / "ratings_clean.csv", index=False)

    db_file = tmp_path / "seed_test.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    Sess = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    prev_proc = os.environ.get("PROCESSED_DATA_DIR")
    os.environ["PROCESSED_DATA_DIR"] = str(proc)
    get_settings.cache_clear()
    try:
        with Sess() as s:
            first = seed_database(s)
            second = seed_database(s)
        assert first["added_movies"] == 1
        assert first["added_ratings"] == 1
        assert second["added_movies"] == 0
    finally:
        if prev_proc is None:
            os.environ.pop("PROCESSED_DATA_DIR", None)
        else:
            os.environ["PROCESSED_DATA_DIR"] = prev_proc
        get_settings.cache_clear()


def test_search_wildcard_escaping_and_admin_version_regex(client: TestClient) -> None:
    # LIKE wildcard amplification must not treat '%' as match-all across catalogue
    wildcard_res = client.get("/api/movies/search?q=%25%25%25")
    assert wildcard_res.status_code == 200
    assert wildcard_res.json() == []

    # Invalid version formats (e.g. traversal tokens like v..) rejected with 422 before hitting filesystem
    a_login = client.post(
        "/api/auth/login",
        json={"email": "admin@cinema-app.org", "password": "StrongAdminPass123!"},
    )
    assert a_login.status_code == 200
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}
    bad_ver = client.post("/api/admin/model/reload?version=v..", headers=a_headers)
    assert bad_ver.status_code == 422


def test_google_oauth_sign_in_linking_and_validation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    client_id = "test-google-client-id.apps.googleusercontent.com"

    # Unconfigured client ID returns 503 cleanly
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    get_settings.cache_clear()
    unconf = client.post("/api/auth/google", json={"credential": "x" * 24})
    assert unconf.status_code == 503

    # Configure Google client ID
    monkeypatch.setenv("GOOGLE_CLIENT_ID", client_id)
    get_settings.cache_clear()

    try:
        # 1. Expired / bad signature raised by verifier
        def raise_expired(_cred: str, _aud: str):
            raise ValueError("Token expired")

        monkeypatch.setattr("app.routers.auth.verify_google_id_token", raise_expired)
        exp_res = client.post("/api/auth/google", json={"credential": "expired-token-payload-123456"})
        assert exp_res.status_code == 401

        # 2. Wrong audience rejected
        monkeypatch.setattr(
            "app.routers.auth.verify_google_id_token",
            lambda _c, _a: {
                "iss": "https://accounts.google.com",
                "aud": "other-client.apps.googleusercontent.com",
                "sub": "gsub-001",
                "email": "g1@cinema-app.org",
                "email_verified": True,
            },
        )
        aud_res = client.post("/api/auth/google", json={"credential": "wrong-aud-token-payload-123"})
        assert aud_res.status_code == 401

        # 3. Unverified email rejected
        monkeypatch.setattr(
            "app.routers.auth.verify_google_id_token",
            lambda _c, _a: {
                "iss": "https://accounts.google.com",
                "aud": client_id,
                "sub": "gsub-002",
                "email": "unverified@cinema-app.org",
                "email_verified": False,
            },
        )
        unv_res = client.post("/api/auth/google", json={"credential": "unverified-token-payload-123"})
        assert unv_res.status_code == 401

        # 4. New Google user creation + friendly block on password login
        monkeypatch.setattr(
            "app.routers.auth.verify_google_id_token",
            lambda _c, _a: {
                "iss": "https://accounts.google.com",
                "aud": client_id,
                "sub": "gsub-new-101",
                "email": "googleviewer@cinema-app.org",
                "name": "Satyajit Fan",
                "picture": "https://lh3.googleusercontent.com/a/testavatar",
                "email_verified": True,
            },
        )
        new_res = client.post("/api/auth/google", json={"credential": "valid-google-token-12345678"})
        assert new_res.status_code == 200
        body = new_res.json()
        assert body["user"]["email"] == "googleviewer@cinema-app.org"
        assert body["user"]["auth_provider"] == "google"
        assert body["user"]["avatar_url"] == "https://lh3.googleusercontent.com/a/testavatar"
        assert "ac_refresh_token" in new_res.cookies

        pw_block = client.post(
            "/api/auth/login",
            json={"email": "googleviewer@cinema-app.org", "password": "SomePassword123!"},
        )
        assert pw_block.status_code == 400
        assert "Google Sign-In" in pw_block.json()["error"]["message"]

        # Returning Google user updates avatar / keeps same user ID
        ret_res = client.post("/api/auth/google", json={"credential": "valid-google-token-again-123"})
        assert ret_res.status_code == 200
        assert ret_res.json()["user"]["id"] == body["user"]["id"]

        # 5. Existing local account linking by verified email
        local_reg = client.post(
            "/api/auth/register",
            json={
                "email": "localfirst@cinema-app.org",
                "username": "localfirst",
                "password": "LocalPassword!123",
            },
        )
        assert local_reg.status_code == 201
        local_uid = local_reg.json()["user"]["id"]

        monkeypatch.setattr(
            "app.routers.auth.verify_google_id_token",
            lambda _c, _a: {
                "iss": "accounts.google.com",
                "aud": client_id,
                "sub": "gsub-linked-202",
                "email": "localfirst@cinema-app.org",
                "email_verified": True,
            },
        )
        link_res = client.post("/api/auth/google", json={"credential": "valid-link-token-12345678"})
        assert link_res.status_code == 200
        assert link_res.json()["user"]["id"] == local_uid
        assert link_res.json()["user"]["auth_provider"] == "both"

        # 6. Conflicting google_sub for already-linked email rejected with 409
        monkeypatch.setattr(
            "app.routers.auth.verify_google_id_token",
            lambda _c, _a: {
                "iss": "accounts.google.com",
                "aud": client_id,
                "sub": "gsub-hijack-999",
                "email": "localfirst@cinema-app.org",
                "email_verified": True,
            },
        )
        conflict_res = client.post("/api/auth/google", json={"credential": "conflict-sub-token-123456"})
        assert conflict_res.status_code == 409
    finally:
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        get_settings.cache_clear()


def test_live_recommendation_personalization_and_isolation(client: TestClient) -> None:
    # Create two isolated users with distinct rating histories and test live mutation immediacy & privacy
    reg_a = client.post(
        "/api/auth/register",
        json={"email": "scififan@cinema-app.org", "username": "scififan", "password": "CinemaPassword123!"},
    )
    reg_b = client.post(
        "/api/auth/register",
        json={"email": "bollyfan@cinema-app.org", "username": "bollyfan", "password": "CinemaPassword123!"},
    )
    assert reg_a.status_code == 201 and reg_b.status_code == 201
    uid_a = reg_a.json()["user"]["id"]
    h_a = {"Authorization": f"Bearer {reg_a.json()['access_token']}"}
    h_b = {"Authorization": f"Bearer {reg_b.json()['access_token']}"}

    scifi_movies = client.get("/api/movies?genre=Sci-Fi&industry=hollywood&sort=popular&page_size=6").json()[
        "items"
    ]
    bolly_movies = client.get("/api/movies?genre=Romance&industry=bollywood&sort=popular&page_size=6").json()[
        "items"
    ]
    assert len(scifi_movies) >= 4 and len(bolly_movies) >= 4

    # User A rates Sci-Fi films at 5.0 and 4.5 (and test idempotent double upsert + 0.5 rating support)
    first_sf = scifi_movies[0]["id"]
    for m in scifi_movies[:4]:
        assert client.put(f"/api/ratings/{m['id']}", json={"rating": 5.0}, headers=h_a).status_code == 200
    assert client.put(f"/api/ratings/{first_sf}", json={"rating": 5.0}, headers=h_a).status_code == 200
    assert (
        client.put(f"/api/ratings/{bolly_movies[0]['id']}", json={"rating": 0.5}, headers=h_a).status_code
        == 200
    )

    # User B rates Bollywood films at 5.0
    for m in bolly_movies[:4]:
        assert client.put(f"/api/ratings/{m['id']}", json={"rating": 5.0}, headers=h_b).status_code == 200

    recs_a = client.get("/api/recommendations/me?k=15", headers=h_a).json()
    recs_b = client.get("/api/recommendations/me?k=15", headers=h_b).json()
    assert recs_a["strategy"] == "personalized_hybrid_cf"
    assert recs_b["strategy"] == "personalized_hybrid_cf"
    ids_a = {it["movie"]["id"] for it in recs_a["items"]}
    ids_b = {it["movie"]["id"] for it in recs_b["items"]}
    assert first_sf not in ids_a
    assert bolly_movies[0]["id"] not in ids_a
    assert ids_a != ids_b

    # Personalized genre, industry, profile, because, explain endpoints respond per user
    prof_a = client.get("/api/recommendations/profile", headers=h_a).json()
    prof_b = client.get("/api/recommendations/profile", headers=h_b).json()
    assert (
        prof_a["genre_order"][0] != prof_b["genre_order"][0]
        or prof_a["industry_order"] != prof_b["industry_order"]
    )

    genre_a = client.get("/api/recommendations/genre/Action?k=8", headers=h_a).json()
    assert genre_a["strategy"] == "personalized_genre_cf"
    ind_a = client.get("/api/recommendations/industry/hollywood?k=8", headers=h_a).json()
    assert ind_a["strategy"] == "personalized_industry_cf"
    because_a = client.get("/api/recommendations/because?limit_rows=2&k=6", headers=h_a).json()
    assert len(because_a["rows"]) >= 1
    top_pick_id = recs_a["items"][0]["movie"]["id"]
    explain_a = client.get(f"/api/recommendations/explain/{top_pick_id}", headers=h_a).json()
    assert explain_a["movie_id"] == top_pick_id

    # Re-rating updates recommendations immediately; deleting restores item eligibility
    client.put(f"/api/ratings/{scifi_movies[1]['id']}", json={"rating": 1.0}, headers=h_a)
    client.delete(f"/api/ratings/{bolly_movies[0]['id']}", headers=h_a)
    recs_a2 = client.get("/api/recommendations/me?k=15", headers=h_a).json()
    assert recs_a2["items"]

    # Privacy & object-level isolation checks:
    # 1. Watchlist & ratings owned by A are invisible to B even if A passes query/guessed IDs
    wl_target = scifi_movies[3]["id"]
    assert client.post(f"/api/watchlist/{wl_target}", headers=h_a).status_code == 201
    assert client.get("/api/watchlist/me", headers=h_b).json() == []
    assert client.delete(f"/api/watchlist/{wl_target}", headers=h_b).status_code == 404
    assert client.delete(f"/api/ratings/{first_sf}", headers=h_b).status_code == 404
    assert client.get(f"/api/movies/{first_sf}", headers=h_b).json()["user_rating"] is None
    assert client.get(f"/api/movies/{wl_target}", headers=h_b).json()["in_watchlist"] is False

    # Passing user_id parameter on personal endpoint never leaks User A's ratings to User B
    b_ratings = client.get(f"/api/ratings/me?user_id={uid_a}", headers=h_b).json()
    assert all(r["movie_id"] != first_sf for r in b_ratings)

    # Unauthenticated access returns 401 cleanly
    for path in ("/api/auth/me", "/api/ratings/me", "/api/watchlist/me"):
        assert client.get(path).status_code == 401
    assert client.put(f"/api/ratings/{first_sf}", json={"rating": 4.0}).status_code == 401
    assert client.delete(f"/api/ratings/{first_sf}").status_code == 401
    assert client.post(f"/api/watchlist/{first_sf}").status_code == 401
    assert client.delete(f"/api/watchlist/{first_sf}").status_code == 401
    assert client.post("/api/admin/model/reload").status_code == 401


def test_account_switching_privacy_hashes_and_db_constraints(client: TestClient, tmp_path: Path) -> None:
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.models import Rating, RefreshToken, Watchlist

    # Switching login revokes prior refresh cookie server-side; search/detail never leak user PII
    r1 = client.post(
        "/api/auth/register",
        json={"email": "priv_a@cinema-app.org", "username": "priv_a", "password": "PasswordOne!123"},
    )
    assert r1.status_code == 201
    tok_a = r1.cookies["ac_refresh_token"]
    client.cookies.set("ac_refresh_token", tok_a)

    # Register second user while A cookie is present -> revokes A's cookie and creates distinct user row
    r2 = client.post(
        "/api/auth/register",
        json={"email": "priv_b@cinema-app.org", "username": "priv_b", "password": "PasswordTwo!123"},
    )
    assert r2.status_code == 201
    assert r2.json()["user"]["id"] != r1.json()["user"]["id"]

    client.cookies.set("ac_refresh_token", tok_a)
    assert client.post("/api/auth/refresh").status_code == 401

    # Public search/detail responses never include emails or usernames
    mov = client.get("/api/movies?page=1&page_size=2").json()["items"][0]
    det = client.get(f"/api/movies/{mov['id']}").text
    assert "priv_a@cinema-app.org" not in det and "priv_a" not in det

    # Direct DB check: bcrypt hashes, unique (user_id, movie_id), and cascade delete
    db_path = tmp_path / "constraints.db"
    eng = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})
    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _fk(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=eng)
    Sess = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    with Sess() as s:
        u = User(email="dbtest@cinema.org", username="dbtest", password_hash=hash_password("ValidPass!123"))
        m = Movie(id=999, title="Test Movie", industry="hollywood", language="en", genres_csv="Drama")
        s.add_all([u, m])
        s.flush()
        assert u.password_hash is not None and u.password_hash.startswith("$2")
        s.add(Rating(user_id=u.id, movie_id=m.id, rating=4.5, source="user"))
        s.add(Watchlist(user_id=u.id, movie_id=m.id))
        s.commit()

        s.add(Rating(user_id=u.id, movie_id=m.id, rating=2.0, source="user"))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()

        # Cascade delete removes ratings, watchlist, refresh tokens cleanly
        s.delete(u)
        s.commit()
        assert s.scalar(select(Rating).where(Rating.movie_id == m.id)) is None
        assert s.scalar(select(Watchlist).where(Watchlist.movie_id == m.id)) is None
        assert s.scalar(select(RefreshToken)) is None
