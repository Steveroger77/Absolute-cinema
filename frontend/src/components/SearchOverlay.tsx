import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Star, X } from "lucide-react";
import { useLenisScroll } from "../context/LenisProvider";
import { useMovieTransition } from "../context/TransitionContext";
import { usePosterHover } from "../hooks/usePosterHover";
import { api } from "../lib/api";
import type { MovieSummary } from "../types/cinema";
import { LiquidGlassSurface } from "./LiquidGlassSurface";
import { PosterImage } from "./PosterImage";

interface SearchOverlayProps {
  open: boolean;
  onClose: () => void;
}

function SearchResultRow({
  movie,
  onSelect,
}: {
  movie: MovieSummary;
  onSelect: (movie: MovieSummary, frameEl: HTMLElement | null) => void;
}) {
  const { prefetchMovie } = useMovieTransition();
  const { hoverLayerRef, mediaLayerRef, glowLayerRef, sheenLayerRef, hitProps } = usePosterHover({
    lift: 3,
    scale: 1.04,
    mediaScale: 1.06,
    maxParallax: 4,
    onEnterExtra: () => prefetchMovie(movie.id),
  });

  return (
    <button
      type="button"
      {...hitProps}
      onPointerDown={() => prefetchMovie(movie.id)}
      onClick={() => onSelect(movie, hoverLayerRef.current)}
      className="flex items-center gap-3 p-2 rounded-xl text-left transition-colors hover:bg-[var(--color-paper-3)] border border-transparent"
    >
      <div className="relative shrink-0" style={{ width: 42, height: 58 }}>
        <div
          ref={glowLayerRef}
          aria-hidden="true"
          className="poster-glow-layer"
          style={
            movie.accent_color
              ? {
                  background: `radial-gradient(ellipse at 50% 60%, ${movie.accent_color}52 0%, transparent 74%)`,
                }
              : undefined
          }
        />
        <div ref={hoverLayerRef} data-poster-frame="true" className="poster-hover-layer rounded-lg">
          <div ref={mediaLayerRef} className="poster-media-layer">
            <PosterImage movie={movie} />
          </div>
          <div ref={sheenLayerRef} aria-hidden="true" className="poster-sheen-layer" />
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <div
          className="font-medium truncate"
          style={{ fontFamily: "var(--font-display)", fontSize: "1.05rem" }}
        >
          {movie.title}
        </div>
        <div
          className="flex flex-wrap items-center gap-2 mt-0.5 text-xs"
          style={{ color: "var(--color-ink-muted)" }}
        >
          <span className="capitalize">{movie.industry}</span>
          {movie.year && <span className="tabular-figure">{movie.year}</span>}
          <span>{movie.genres.slice(0, 2).join(", ")}</span>
        </div>
      </div>
      <span
        className="tabular-figure text-sm shrink-0 inline-flex items-center gap-1"
        style={{ color: "var(--color-accent)" }}
      >
        {(movie.tmdb_rating ? movie.tmdb_rating : movie.rating_avg * 2).toFixed(1)}
        <Star size={12} fill="currentColor" aria-hidden="true" />
      </span>
    </button>
  );
}

export function SearchOverlay({ open, onClose }: SearchOverlayProps) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { openMovie, captureSourceRect } = useMovieTransition();
  const { pauseScroll, resumeScroll } = useLenisScroll();

  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(query.trim()), 180);
    return () => window.clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    pauseScroll();
    const timer = window.setTimeout(() => inputRef.current?.focus(), 40);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
      resumeScroll();
    };
  }, [open, onClose, pauseScroll, resumeScroll]);

  const { data: results = [], isFetching } = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.searchMovies(debounced, 16),
    enabled: open && debounced.length >= 1,
  });

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Search films"
      className="fixed inset-0 flex items-start justify-center p-4 pt-16 sm:pt-24"
      style={{ zIndex: "var(--z-modal)", backgroundColor: "var(--color-scrim)" }}
      onClick={onClose}
    >
      <div className="w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
        <LiquidGlassSurface radius={24} blur={16} className="p-4 sm:p-5">
          <div
            className="flex items-center gap-3 pb-3 border-b"
            style={{ borderColor: "var(--color-rule)" }}
          >
            <Search size={20} style={{ color: "var(--color-accent)" }} aria-hidden="true" />
            <input
              ref={inputRef}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search titles, directors, actors, genres…"
              aria-label="Search titles, directors, actors, or genres"
              className="cinema-input border-0 bg-transparent px-1"
            />
            <button
              type="button"
              onClick={onClose}
              aria-label="Close search"
              className="cinema-btn cinema-btn-ghost px-2"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>

          <div
            data-lenis-prevent
            className="mt-3 max-h-[58dvh] overflow-y-auto no-scrollbar flex flex-col gap-2"
          >
            {debounced.length === 0 ? (
              <p className="py-6 text-center text-sm" style={{ color: "var(--color-ink-muted)" }}>
                Type a title across Hollywood, Bollywood, or Tollywood.
              </p>
            ) : isFetching && results.length === 0 ? (
              <div className="flex flex-col gap-2 py-2">
                {[1, 2, 3].map((n) => (
                  <div key={n} className="skeleton-block h-16 w-full" />
                ))}
              </div>
            ) : results.length === 0 ? (
              <p className="py-6 text-center text-sm" style={{ color: "var(--color-ink-muted)" }}>
                No matching titles found for “{debounced}”.
              </p>
            ) : (
              results.map((m) => (
                <SearchResultRow
                  key={m.id}
                  movie={m}
                  onSelect={(selectedMovie, frameEl) => {
                    // Capture synchronous viewport rect BEFORE closing overlay unmounts node
                    const rect = captureSourceRect(frameEl);
                    onClose();
                    openMovie(selectedMovie, frameEl, {
                      originType: "search",
                      originLabel: "Back to search results",
                      preCapturedRect: rect,
                    });
                  }}
                />
              ))
            )}
          </div>
        </LiquidGlassSurface>
      </div>
    </div>
  );
}
