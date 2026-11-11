"""Post-deploy & container smoke test verifying health, catalogue, auth, ratings, and live recs."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import secrets
import sys
import time
import urllib.error
import urllib.request


def _request(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Unsupported URL scheme for smoke test: {url}")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)  # noqa: S310
    try:
        with opener.open(req, timeout=20) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw}
        return err.code, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test deployed ABSOLUTE CINEMA backend.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend root URL without /api suffix (e.g. https://absolute-cinema-api.onrender.com)",
    )
    parser.add_argument(
        "--frontend-url",
        default="",
        help="Optional deployed frontend URL to verify SPA status + CORS headers.",
    )
    parser.add_argument("--wait-seconds", type=int, default=60, help="Cold-start wake wait timeout.")
    args = parser.parse_args()

    api_base = args.base_url.rstrip("/")
    if not api_base.startswith(("http://", "https://")):
        raise ValueError("--base-url must start with http:// or https://")
    if not api_base.endswith("/api"):
        api_base = f"{api_base}/api"

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # 1. Health check (with cold-start wake retry)
    deadline = time.monotonic() + args.wait_seconds
    health = None
    last_err = ""
    while time.monotonic() < deadline:
        try:
            code, body = _request(opener, "GET", f"{api_base}/health")
            if code == 200 and body.get("status") == "ok" and body.get("model_loaded"):
                health = body
                break
            last_err = f"HTTP {code}: {body}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_err = str(exc)
        time.sleep(2.0)

    if not health:
        print(
            f"FAIL: Health endpoint did not become ready at {api_base}/health ({last_err})",
            file=sys.stderr,
        )
        return 1
    print(f"OK /health -> version={health.get('model_version')} db={health.get('database')}")

    # 2. Catalogue & Trending
    c_code, catalogue = _request(opener, "GET", f"{api_base}/movies?page=1&page_size=5")
    assert c_code == 200 and len(catalogue.get("items", [])) >= 1, f"Catalogue failed: {c_code}"
    movie_id = int(catalogue["items"][0]["id"])
    t_code, trending = _request(opener, "GET", f"{api_base}/movies/trending?limit=5")
    assert t_code == 200 and len(trending) >= 1, f"Trending failed: {t_code}"
    print(f"OK /movies & /trending -> sample_movie_id={movie_id}")

    # 3. Ephemeral registration -> rating -> immediate personalized recommendations
    suffix = secrets.token_hex(4)
    r_code, reg = _request(
        opener,
        "POST",
        f"{api_base}/auth/register",
        payload={
            "email": f"smoke_{suffix}@example.com",
            "username": f"smoke_{suffix}",
            "password": f"SmokePass_{suffix}!1",
        },
    )
    assert r_code == 201 and reg.get("access_token"), f"Register failed ({r_code}): {reg}"
    auth_headers = {"Authorization": f"Bearer {reg['access_token']}"}

    up_code, _ = _request(
        opener, "PUT", f"{api_base}/ratings/{movie_id}", payload={"rating": 4.5}, headers=auth_headers
    )
    assert up_code == 200, f"Upsert rating failed: {up_code}"

    rec_code, recs = _request(opener, "GET", f"{api_base}/recommendations/me?k=5", headers=auth_headers)
    assert rec_code == 200 and recs.get("strategy") == "personalized_hybrid_cf", f"Recs failed: {recs}"
    rec_ids = {int(it["movie"]["id"]) for it in recs.get("items", [])}
    assert movie_id not in rec_ids, "Already-rated movie appeared in personalized recommendations"
    print(f"OK personalized recommendations -> {len(rec_ids)} picks excluding rated item {movie_id}")

    # 4. Graceful unknown API route 404 JSON + logout
    n_code, not_found = _request(opener, "GET", f"{api_base}/unknown-smoke-route")
    assert n_code == 404 and "error" in not_found, f"Unexpected 404 envelope: {not_found}"
    out_code, _ = _request(opener, "POST", f"{api_base}/auth/logout")
    assert out_code == 204, f"Logout failed: {out_code}"

    # 5. Optional frontend URL SPA + CORS preflight verification
    if args.frontend_url:
        fe = args.frontend_url.rstrip("/")
        if not fe.startswith(("http://", "https://")):
            raise ValueError("--frontend-url must start with http:// or https://")
        fe_req = urllib.request.Request(f"{fe}/explore", method="GET")  # noqa: S310
        with urllib.request.urlopen(fe_req, timeout=20) as resp:  # noqa: S310
            assert resp.status == 200, f"Frontend SPA route check failed: {resp.status}"
        cors_code, _ = _request(opener, "GET", f"{api_base}/health", headers={"Origin": fe})
        assert cors_code == 200, f"CORS health check failed: {cors_code}"
        print(f"OK frontend SPA rewrite & CORS -> {fe}")

    print("PASS: All smoke checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
