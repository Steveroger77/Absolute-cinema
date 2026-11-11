"""Typographic editorial SVG fallback poster generator using each movie's extracted palette."""

from __future__ import annotations

import html
import textwrap

from app.models import Movie


def render_fallback_poster_svg(movie: Movie) -> str:
    """Return a crisp 3:4.2 portrait SVG poster in the movie's palette (XML-escaped)."""
    title_lines = textwrap.wrap(movie.title.strip(), width=15)[:3]
    if not title_lines:
        title_lines = ["Absolute Cinema"]

    dom = movie.dominant_color or "#C35A1A"
    acc = movie.accent_color or "#FFB45C"
    shd = movie.shadow_color or "#1A0D06"
    year_str = str(movie.year) if movie.year else "Classic"
    industry = html.escape(movie.industry.capitalize())
    director = html.escape((movie.director or movie.genres_csv.replace("|", ", "))[:36])

    title_tspans = []
    start_y = 205 if len(title_lines) <= 2 else 185
    for idx, line in enumerate(title_lines):
        escaped = html.escape(line)
        y_pos = start_y + idx * 42
        title_tspans.append(
            f'<text x="30" y="{y_pos}" fill="#FFF1DC" font-family="Georgia, serif" '
            f'font-size="34" font-weight="600" letter-spacing="-0.6">{escaped}</text>'
        )

    lines_markup = "\n    ".join(title_tspans)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 420" '
        f'width="300" height="420" role="img" aria-label="{html.escape(movie.title)}">\n'
        f"  <defs>\n"
        f'    <linearGradient id="bg" x1="0" y1="0" x2="0.85" y2="1">\n'
        f'      <stop offset="0%" stop-color="{html.escape(dom)}" stop-opacity="0.88"/>\n'
        f'      <stop offset="55%" stop-color="{html.escape(shd)}" stop-opacity="0.98"/>\n'
        f'      <stop offset="100%" stop-color="#1A0D06"/>\n'
        f"    </linearGradient>\n"
        f'    <radialGradient id="orb" cx="72%" cy="22%" r="65%">\n'
        f'      <stop offset="0%" stop-color="{html.escape(acc)}" stop-opacity="0.52"/>\n'
        f'      <stop offset="100%" stop-color="{html.escape(dom)}" stop-opacity="0"/>\n'
        f"    </radialGradient>\n"
        f"  </defs>\n"
        f'  <rect width="300" height="420" fill="url(#bg)"/>\n'
        f'  <rect width="300" height="420" fill="url(#orb)"/>\n'
        f'  <rect x="14" y="14" width="272" height="392" rx="12" fill="none" '
        f'stroke="{html.escape(acc)}" stroke-opacity="0.28" stroke-width="1"/>\n'
        f'  <text x="30" y="54" fill="{html.escape(acc)}" font-family="system-ui, sans-serif" '
        f'font-size="13" font-weight="500">{industry}</text>\n'
        f'  <text x="270" y="54" text-anchor="end" fill="#FFD9A3" font-family="monospace" '
        f'font-size="13">{html.escape(year_str)}</text>\n'
        f'  <line x1="30" y1="72" x2="270" y2="72" stroke="#FFD9A3" stroke-opacity="0.16" '
        f'stroke-width="1"/>\n'
        f"  {lines_markup}\n"
        f'  <line x1="30" y1="348" x2="270" y2="348" stroke="#FFD9A3" stroke-opacity="0.16" '
        f'stroke-width="1"/>\n'
        f'  <text x="30" y="376" fill="#FFD9A3" fill-opacity="0.78" '
        f'font-family="system-ui, sans-serif" font-size="12">{director}</text>\n'
        f"</svg>"
    )
