# Architecture — ABSOLUTE CINEMA

ABSOLUTE CINEMA is a three-tier movie discovery platform built around an offline-trained, sparse hybrid collaborative filtering model paired with live database rating profiles, FastAPI, PostgreSQL/SQLAlchemy, and a React + Vite frontend.

---

## System Topology

```text
Browser (React 19 + Vite + React Query)
   │  Access JWT in memory + HttpOnly Refresh Cookie (`ac_refresh_token`)
   │  Same-origin `/api` (Vite dev proxy / Docker Nginx) or `VITE_API_BASE_URL` (Render)
   ▼
FastAPI Application (`backend/app/main.py`, Uvicorn `--workers 1`)
   ├── Auth & Sessions (`auth.py`, `security.py`, `deps.py`) — bcrypt, PyJWT, rotating `refresh_tokens`, Google OAuth
   ├── Private User State (`ratings.py`, `watchlist.py`) — strictly token-derived `user.id` ownership
   ├── Catalogue & Search (`movies.py`, `poster_svg.py`) — SQL filters, escaped `ILIKE` + fuzzy match, SVG poster fallback
   └── Recommender Service (`recommender_service.py`) — read-only `model_v1.joblib` + per-`(user_id, version)` LRU cache
         │                                               │
         ▼                                               ▼
PostgreSQL / SQLite (`alembic/` + `models/entities.py`)  `ml/src/loader.py` (`RecommenderEngine`, sparse SciPy CSR)
```

---

## Machine Learning Pipeline (`ml/src/`)

Training stays strictly separated from API serving:

1. **Ingestion & Balancing (`ingest.py`, `seed_indian_cinema.csv`)**: Combines MovieLens Latest Small titles with balanced Bollywood and Tollywood films (total catalogue: **2,300** titles across 1,350 Hollywood, 475 Bollywood, and 475 Tollywood).
2. **Enrichment & Palettes (`enrich.py`, `colors.py`)**: Populates metadata via TMDB v3 or Wikidata/Wikimedia fallbacks, and computes Lab-space KMeans (`k=5`) poster color tokens offline.
3. **Preprocessing (`preprocess.py`)**: Normalizes genre taxonomy across industries and generates deterministically seeded (`random_state=42`, `source='synthetic'`) interaction patterns for non-MovieLens Indian titles while leaving ~10% sparse (`<= 3` ratings) to exercise cold-item content fallback.
4. **Leak-Free Split (`split.py`)**: Per-user chronological split holding out the most recent 20% of interactions for test evaluation and 10% for validation tuning (`assert_no_leakage` enforces zero overlap).
5. **Models (`matrix.py`, `item_cf.py`, `user_cf.py`, `content_fallback.py`, `popular.py`)**:
   - **Sparse CSR Representation**: Never densifies the user–item matrix. Similarity matrices retain top-N/M positive shrunk entries in `float32`.
   - **Item-Based CF + User-Based CF**: Mean-centered cosine similarities with co-rating shrinkage (`n_ij / (n_ij + beta)`). At inference time, user ratings from the database feed dynamic deviation and user-fold-in vectors with constant-rating protection and recency weighting.
   - **Content Fallback**: TF-IDF unigram/bigram matrix (`max_features=8000`) over genres, industry, language, director, cast, and synopsis, centered on user mean so low ratings actively suppress matching themes.
   - **Cold Start Blend**: Zero-rating users start with Bayesian popularity + onboarding preferences and blend smoothly (`cf_transition`) into collaborative + content + taste affinity scores between ratings `1..5`.
6. **Artifacts (`ml/artifacts/`)**: `python -m ml.src.train` exports `model_v1.joblib` (~2.3 MB compressed), `manifest.json` (SHA-256 + tuned weights), and `metrics.json`.

---

## Serving Isolation & Caching

- `RecommenderService` loads the read-only artifact once at boot (~201 MB total Python/Uvicorn RSS in single-worker mode, fitting inside Render's 512 MB limit).
- Every personalized response cache key starts with `(user_id, ratings_version, ...)`.
- Rating writes/deletes and onboarding updates increment `_user_versions[user_id]` immediately via `invalidate_user_cache(user_id)` so the very next request recomputes fresh picks for that user without touching other users' cache entries.
- `DATABASE_URL` normalizes `postgres://` and `postgresql://` automatically to `postgresql+psycopg://` for both runtime SQLAlchemy (`backend/app/db/session.py`) and Alembic (`backend/alembic/env.py`).

---

## Frontend Architecture (`frontend/src/`)

- **Routing & Code Splitting (`App.tsx`)**: Lazy-loaded routes with React Query (`staleTime: 5 min`), Lenis smooth scrolling (`LenisProvider.tsx`), and GSAP timeline choreography (`TransitionContext.tsx`, `PosterCarousel.tsx`).
- **Session Privacy (`AuthContext.tsx`, `lib/api.ts`, `lib/sessionCleanup.ts`)**: Access tokens exist only in module memory; browser navigation caches and carousel positions clear on login/logout and key on `user.id`.
- **Cold-Start UX**: `api.ts` detects slow boots or gateway cold-start responses (`502/503/504`), retries safely with exponential backoff, and toggles an unobtrusive `"Waking the projector…"` notice in `AppShell.tsx`.

