"""Offline poster color extraction in CIELAB space with KMeans (k=5) + amber palette fallback."""

from __future__ import annotations

import json
import logging
import time
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from PIL import Image
from sklearn.cluster import KMeans

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
POSTER_CACHE_DIR = ROOT_DIR / "data" / "posters"
COLOR_CACHE_PATH = ROOT_DIR / "data" / "processed" / "color_cache.json"
USER_AGENT = "AbsoluteCinemaPaletteExtractor/1.0 (https://github.com/absolute-cinema)"

GENRE_PALETTE_FALLBACK: dict[str, tuple[str, str, str, str]] = {
    "Action": ("#C35A1A", "#FFB45C", "#3A1607", "dark"),
    "Adventure": ("#D97822", "#FFD9A3", "#3B1B0A", "mid"),
    "Animation": ("#F28B2C", "#FFD9A3", "#4F2108", "mid"),
    "Comedy": ("#E59A3E", "#FFD9A3", "#4B250C", "mid"),
    "Crime": ("#8F3412", "#F28B2C", "#230E05", "dark"),
    "Drama": ("#A34A19", "#FFB45C", "#291207", "dark"),
    "Fantasy": ("#C86C24", "#FFD9A3", "#3A1808", "mid"),
    "Horror": ("#7A2E0B", "#E06D2B", "#1A0D06", "dark"),
    "Mystery": ("#883D18", "#FFB45C", "#221007", "dark"),
    "Romance": ("#D47744", "#FFD9A3", "#3B180B", "mid"),
    "Sci-Fi": ("#B56327", "#FFD9A3", "#261309", "dark"),
    "Thriller": ("#913A13", "#F28B2C", "#210E06", "dark"),
    "War": ("#7C3917", "#E69B4E", "#200F07", "dark"),
    "Musical": ("#E68B2E", "#FFD9A3", "#441D08", "mid"),
    "Family": ("#E09848", "#FFD9A3", "#45220B", "mid"),
}
DEFAULT_PALETTE = ("#C35A1A", "#FFB45C", "#291207", "dark")


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Vectorized sRGB [0..255] (N, 3) -> CIELAB (L*, a*, b*)."""
    srgb = np.clip(rgb.astype(np.float64) / 255.0, 0.0, 1.0)
    mask = srgb <= 0.04045
    lin = np.where(mask, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    M = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = lin @ M.T
    xyz_ref = np.array([0.95047, 1.00000, 1.08883])
    norm = xyz / xyz_ref
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(norm > eps, np.cbrt(norm), (kappa * norm + 16.0) / 116.0)
    L = 116.0 * f[:, 1] - 16.0
    a = 500.0 * (f[:, 0] - f[:, 1])
    b = 200.0 * (f[:, 1] - f[:, 2])
    return np.column_stack([L, a, b])


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Vectorized CIELAB (N, 3) -> sRGB uint8 (N, 3)."""
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    fy = (L + 16.0) / 116.0
    fx = a / 500.0 + fy
    fz = fy - b / 200.0
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    xr = np.where(fx**3 > eps, fx**3, (116.0 * fx - 16.0) / kappa)
    yr = np.where(L > kappa * eps, ((L + 16.0) / 116.0) ** 3, L / kappa)
    zr = np.where(fz**3 > eps, fz**3, (116.0 * fz - 16.0) / kappa)
    xyz = np.column_stack([xr * 0.95047, yr * 1.00000, zr * 1.08883])
    M_inv = np.array(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ]
    )
    lin = np.clip(xyz @ M_inv.T, 0.0, 1.0)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * (lin ** (1.0 / 2.4)) - 0.055)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _rgb_to_hex(rgb: np.ndarray) -> str:
    return f"#{int(rgb[0]):02X}{int(rgb[1]):02X}{int(rgb[2]):02X}"


def extract_palette_from_image(image: Image.Image) -> dict[str, str] | None:
    """Extract dominant, accent, shadow hex colors + luminance flag via Lab KMeans(k=5)."""
    thumb = image.convert("RGB").resize((80, 112), Image.Resampling.BILINEAR)
    pixels = np.asarray(thumb).reshape(-1, 3)
    lab = _srgb_to_lab(pixels)
    chroma = np.sqrt(lab[:, 1] ** 2 + lab[:, 2] ** 2)

    valid = (lab[:, 0] >= 14.0) & (lab[:, 0] <= 90.0) & (chroma >= 11.0)
    filtered_lab = lab[valid]
    if len(filtered_lab) < 40:
        valid = (lab[:, 0] >= 12.0) & (lab[:, 0] <= 92.0) & (chroma >= 5.0)
        filtered_lab = lab[valid]
    if len(filtered_lab) < 25:
        return None

    n_unique = len(np.unique(np.round(filtered_lab, 1), axis=0))
    k = min(5, max(1, n_unique))
    km = KMeans(n_clusters=k, random_state=42, n_init=5)
    labels = km.fit_predict(filtered_lab)
    counts = np.bincount(labels, minlength=k)
    centers_lab = km.cluster_centers_
    centers_chroma = np.sqrt(centers_lab[:, 1] ** 2 + centers_lab[:, 2] ** 2)

    dom_idx = int(np.argmax(counts))
    dom_lab = centers_lab[dom_idx].copy()

    best_acc_idx = dom_idx
    best_score = -1.0
    for idx in range(k):
        dist = float(np.linalg.norm(centers_lab[idx] - dom_lab))
        score = float(centers_chroma[idx]) + (0.35 * dist if idx != dom_idx else 0.0)
        if score > best_score:
            best_score = score
            best_acc_idx = idx
    acc_lab = centers_lab[best_acc_idx].copy()
    acc_lab[0] = max(48.0, min(84.0, acc_lab[0]))

    dark_idx = int(np.argmin(centers_lab[:, 0]))
    shd_lab = centers_lab[dark_idx].copy()
    shd_lab[0] = max(8.0, min(28.0, shd_lab[0] * 0.65))
    shd_lab[1] = shd_lab[1] * 0.55 + 3.0
    shd_lab[2] = shd_lab[2] * 0.55 + 3.0

    rgb_out = _lab_to_rgb(np.vstack([dom_lab, acc_lab, shd_lab]))
    lum = "light" if dom_lab[0] >= 64.0 else ("mid" if dom_lab[0] >= 36.0 else "dark")
    return {
        "dominant_color": _rgb_to_hex(rgb_out[0]),
        "accent_color": _rgb_to_hex(rgb_out[1]),
        "shadow_color": _rgb_to_hex(rgb_out[2]),
        "color_luminance": lum,
    }


def genre_fallback_palette(genres: str | None) -> dict[str, str]:
    """Derive a warm palette matching palette.png from the movie's primary genre."""
    first_genre = (str(genres or "").split("|")[0]).strip()
    dom, acc, shd, lum = GENRE_PALETTE_FALLBACK.get(first_genre, DEFAULT_PALETTE)
    return {
        "dominant_color": dom,
        "accent_color": acc,
        "shadow_color": shd,
        "color_luminance": lum,
    }


def _load_color_cache() -> dict[str, dict[str, str]]:
    if COLOR_CACHE_PATH.exists():
        try:
            return json.loads(COLOR_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _save_color_cache(cache: dict[str, dict[str, str]]) -> None:
    COLOR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COLOR_CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def extract_catalogue_colors(catalogue: pd.DataFrame, max_downloads: int = 350) -> pd.DataFrame:
    """
    Extract Lab KMeans(k=5) poster colors from locally cached posters and polite remote fetches.

    Prioritizes popular and curated films first, respects HTTP 429 rate-limits immediately with
    graceful genre-palette fallback so CDN endpoints are never overloaded.
    """
    POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _load_color_cache()

    # 1. Process all already-cached local thumbnails first (zero network)
    for _, row in catalogue.iterrows():
        mk = str(int(row["movie_id"]))
        if mk in cache:
            continue
        local_path = POSTER_CACHE_DIR / f"{mk}.jpg"
        if local_path.exists():
            try:
                img = Image.open(local_path)
                pal = extract_palette_from_image(img)
                if pal is not None:
                    cache[mk] = pal
            except OSError as exc:
                logger.debug("Skipping unreadable cached poster %s: %s", local_path, exc)

    # 2. Fetch remaining thumbnails politely (prioritize Indian marquee titles & popular Hollywood)
    cat_copy = catalogue.copy()
    cat_copy["_is_indian"] = (cat_copy["movie_id"] >= 900_000).astype(int)
    prioritized = cat_copy.sort_values(
        by=["_is_indian", "ml_count", "movie_id"], ascending=[False, False, True]
    ).drop(columns=["_is_indian"])
    downloads_done = 0
    consecutive_429 = 0

    with httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for _, row in prioritized.iterrows():
            if downloads_done >= max_downloads or consecutive_429 >= 4:
                break
            mk = str(int(row["movie_id"]))
            if mk in cache:
                continue
            url = row.get("poster_url")
            if pd.isna(url) or not str(url).startswith("http"):
                continue

            local_path = POSTER_CACHE_DIR / f"{mk}.jpg"
            try:
                time.sleep(0.18)
                resp = client.get(str(url))
                if resp.status_code == 429:
                    consecutive_429 += 1
                    retry_after = float(resp.headers.get("Retry-After", "2"))
                    time.sleep(min(retry_after, 4.0))
                    continue
                consecutive_429 = 0
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
                    img = Image.open(BytesIO(resp.content))
                    img.convert("RGB").thumbnail((200, 300))
                    img.convert("RGB").save(local_path, format="JPEG", quality=82)
                    pal = extract_palette_from_image(img)
                    cache[mk] = pal if pal is not None else genre_fallback_palette(row.get("genres"))
                    downloads_done += 1
            except (httpx.HTTPError, OSError, ValueError) as exc:
                logger.debug("Poster fetch skipped for %s: %s", mk, exc)
                continue

    _save_color_cache(cache)
    logger.info(
        "Color cache ready: %d extracted from posters, remaining use genre-amber harmony",
        len(cache),
    )

    out = catalogue.copy()
    palettes = out.apply(
        lambda r: cache.get(str(int(r["movie_id"])), genre_fallback_palette(r.get("genres"))),
        axis=1,
    )
    out["dominant_color"] = palettes.apply(lambda p: p["dominant_color"])
    out["accent_color"] = palettes.apply(lambda p: p["accent_color"])
    out["shadow_color"] = palettes.apply(lambda p: p["shadow_color"])
    out["color_luminance"] = palettes.apply(lambda p: p["color_luminance"])
    return out
