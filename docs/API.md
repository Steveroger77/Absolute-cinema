# REST API Reference — ABSOLUTE CINEMA

Base URL: `/api` (proxied locally in Vite/Nginx, or hosted API URL + `/api` in Render Static Site builds). Import `docs/postman_collection.json` for interactive requests. Interactive OpenAPI docs are available at `/api/docs` when `APP_ENV=development` (disabled in `production`).

---

## System & Model

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/health` | Public | Returns DB connectivity (`ok`/`error`), `model_loaded`, and loaded `model_version`. |
| `GET` | `/api/model/info` | Public | Returns loaded model version, SHA-256 hash, dataset counts, and evaluation metrics. |
| `POST` | `/api/admin/model/reload?version=v1` | Admin (`role="admin"`) | Hot-swaps the loaded `.joblib` model artifact without restarting Uvicorn (rate-limited `10/min`). |

---

## Authentication & User Profile

Access JWTs (`15 min`) are passed in `Authorization: Bearer <token>`. Rotating refresh tokens (`7 days`) use the `HttpOnly` cookie `ac_refresh_token` (`path=/api/auth`) with reuse detection.

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/auth/register` | Public | Creates a private user account (`bcrypt` hash) and issues access + refresh tokens (`10/min`). |
| `POST` | `/api/auth/login` | Public | Authenticates email/password and rotates cookie session (`15/min`). |
| `POST` | `/api/auth/google` | Public | Verifies Google ID token (`aud`, `iss`, `exp`, `email_verified`) and signs in/links user (`15/min`). |
| `GET` | `/api/auth/session` | Public | Non-error cookie pre-check returning `{"has_session": boolean}`. |
| `POST` | `/api/auth/refresh` | Cookie | Rotates refresh token (`30/min`); replay of revoked token invalidates all user refresh tokens. |
| `POST` | `/api/auth/logout` | Cookie | Revokes the active refresh token server-side and clears cookie. |
| `GET` | `/api/auth/me` | Bearer | Returns the signed-in user's profile and onboarding preferences. |
| `PUT` | `/api/auth/onboarding` | Bearer | Saves `preferred_genres` and `preferred_industries`, invalidates user recommender cache. |

---

## Catalogue, Search & Posters

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/genres` | Public | Lists canonical genres with catalogue counts. |
| `GET` | `/api/movies` | Public | Paginated catalogue (`page`, `page_size`, `genre`, `industry`, `language`, `year`, `sort`). |
| `GET` | `/api/movies/trending` | Public | Balanced cross-industry (or single-industry) trending showcase. |
| `GET` | `/api/movies/search?q=&limit=` | Public | Escaped SQL `ILIKE` search with typo-tolerant fuzzy title fallback. |
| `GET` | `/api/movies/{movie_id}` | Optional Bearer | Movie details; includes authenticated owner's `user_rating` and `in_watchlist` only. |
| `GET` | `/api/posters/{movie_id}.svg` | Public | On-demand palette-matched SVG fallback poster (`Cache-Control: 86400s`). |

---

## Private Ratings & Watchlist

All routes below derive identity exclusively from the verified JWT (`user.id`). Client-supplied `user_id` parameters are never accepted.

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/ratings/me` | Bearer | Lists the authenticated user's ratings newest-first. |
| `PUT` | `/api/ratings/{movie_id}` | Bearer | Idempotent half-star rating upsert (`0.5–5.0` step `0.5`), updates movie aggregates and user cache. |
| `DELETE` | `/api/ratings/{movie_id}` | Bearer | Deletes the user's rating (`404` if not owned by caller), recomputes aggregates and user cache. |
| `GET` | `/api/watchlist/me` | Bearer | Lists the authenticated user's saved watchlist items newest-first. |
| `POST` | `/api/watchlist/{movie_id}` | Bearer | Adds film to caller's watchlist (`201`). |
| `DELETE` | `/api/watchlist/{movie_id}` | Bearer | Removes film from caller's watchlist (`204`, or `404` if not present). |

---

## Personalized Recommendations

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/recommendations/me` | Optional Bearer | Live hybrid CF + content + taste picks (cold-start blended `<5` ratings; excludes rated items). |
| `GET` | `/api/recommendations/genre/{genre}` | Optional Bearer | Genre shelf ranked by caller's personal score (or Bayesian prior for guests). |
| `GET` | `/api/recommendations/industry/{industry}` | Optional Bearer | Industry shelf (`hollywood`/`bollywood`/`tollywood`) ranked for caller or guest prior. |
| `GET` | `/api/recommendations/profile` | Optional Bearer | Mean-centered, recency-weighted genre and industry affinity ordering for the caller. |
| `GET` | `/api/recommendations/because` | Optional Bearer | Top `1–3` recently high-rated anchor films mapped to nearest-neighbor carousel rows + row order. |
| `GET` | `/api/recommendations/explain/{movie_id}` | Optional Bearer | Returns top `2–3` positively rated driver films explaining why the target film aligns. |
| `GET` | `/api/recommendations/similar/{movie_id}` | Public | Blended item-CF + TF-IDF content similarity neighbors for a movie (`More like this`). |

---

## Error Envelope

All `4xx`/`5xx` API responses (including unmatched routes, validation failures, and `429` rate limits) share a standardized structure:

```json
{
  "error": {
    "code": "http_404",
    "message": "Not Found",
    "details": null
  }
}
```

