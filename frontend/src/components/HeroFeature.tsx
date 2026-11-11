import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { Bookmark, ChevronLeft, ChevronRight, Sparkles, Star } from "lucide-react";
import { useAmbient } from "../context/AmbientContext";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { heroCtaGlassTokens } from "../lib/colorHarmony";
import { prefersReducedMotion } from "../lib/tier";
import type { MovieSummary } from "../types/cinema";
import { LiquidGlassSurface } from "./LiquidGlassSurface";
import { HoverPosterCard } from "./HoverPosterCard";
import { StarRating } from "./StarRating";

interface HeroFeatureProps {
  movies: MovieSummary[];
  watchlistIds: Set<number>;
  userRatings: Map<number, number>;
  onToggleWatchlist: (movieId: number) => void;
  onRateMovie: (movieId: number, rating: number) => void;
}

const HERO_SLIDE_MS = 6800;

export function HeroFeature({
  movies,
  watchlistIds,
  userRatings,
  onToggleWatchlist,
  onRateMovie,
}: HeroFeatureProps) {
  const [index, setIndex] = useState(0);
  const [showRater, setShowRater] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [bookmarkPopped, setBookmarkPopped] = useState(false);

  const { setFromMovie } = useAmbient();
  const { user } = useAuth();
  const { openMovie, prefetchMovie, captureSourceRect } = useMovieTransition();

  const textGroupRef = useRef<HTMLDivElement | null>(null);
  const posterWrapRef = useRef<HTMLDivElement | null>(null);
  const preCapturedRectRef = useRef<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const progressBarRef = useRef<HTMLDivElement | null>(null);

  const current = movies[index % Math.max(1, movies.length)];

  useEffect(() => {
    setShowRater(false);
    setIndex(0);
  }, [user?.id]);

  useEffect(() => {
    if (current) {
      setFromMovie(current);
    }
  }, [current, setFromMovie]);

  const ctaGlass = useMemo(
    () => (current ? heroCtaGlassTokens(current.dominant_color, current.accent_color) : null),
    [current]
  );

  // Synchronized slide-in masked text & parallax poster reveal on active movie change
  useLayoutEffect(() => {
    if (!current || prefersReducedMotion()) return;

    const textEl = textGroupRef.current;
    const posterEl = posterWrapRef.current;
    if (!textEl || !posterEl) return;

    const ctx = gsap.context(() => {
      const words = textEl.querySelectorAll(".masked-word-inner");
      const metaItems = textEl.querySelectorAll("[data-hero-stagger]");
      if (words.length) {
        gsap.fromTo(
          words,
          { yPercent: 108, opacity: 0 },
          { yPercent: 0, opacity: 1, duration: 0.56, stagger: 0.045, ease: "expo.out" }
        );
      }
      if (metaItems.length) {
        gsap.fromTo(
          metaItems,
          { y: 12, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.48, stagger: 0.055, ease: "power3.out" }
        );
      }
      gsap.fromTo(
        posterEl,
        { opacity: 0.35, scale: 1.05, y: 10 },
        { opacity: 1, scale: 1, y: 0, duration: 0.65, ease: "expo.out", clearProps: "transform" }
      );
    }, textEl);

    return () => ctx.revert();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  // Synchronized auto-advance progress bar + interval
  useEffect(() => {
    if (movies.length <= 1 || hovered || showRater || prefersReducedMotion()) {
      if (progressBarRef.current) {
        gsap.killTweensOf(progressBarRef.current);
      }
      return;
    }

    const bar = progressBarRef.current;
    let barTween: gsap.core.Tween | null = null;
    if (bar) {
      barTween = gsap.fromTo(
        bar,
        { scaleX: 0 },
        { scaleX: 1, duration: HERO_SLIDE_MS / 1000, ease: "none" }
      );
    }

    const timer = window.setInterval(() => {
      setShowRater(false);
      setIndex((i) => (i + 1) % movies.length);
    }, HERO_SLIDE_MS);

    return () => {
      window.clearInterval(timer);
      barTween?.kill();
    };
  }, [hovered, index, movies.length, showRater]);

  if (!current) {
    return (
      <section className="cinema-container pt-6 pb-8">
        <div className="skeleton-block w-full" style={{ height: "min(62dvh, 480px)" }} />
      </section>
    );
  }

  const inWatchlist = watchlistIds.has(current.id);
  const myRating = userRatings.get(current.id) ?? null;
  const displayScore =
    current.tmdb_rating && current.tmdb_rating > 0
      ? current.tmdb_rating.toFixed(1)
      : (current.rating_avg * 2).toFixed(1);

  const heroVars = ctaGlass
    ? ({
        "--hero-cta-bg": ctaGlass.bg,
        "--hero-cta-border": ctaGlass.border,
        "--hero-cta-glow": ctaGlass.glow,
      } as CSSProperties)
    : undefined;

  const titleWords = current.title.split(/\s+/).filter(Boolean);

  return (
    <section
      className="cinema-container pt-4 pb-6"
      aria-label="Featured spotlight"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={heroVars}
    >
      <div
        className="relative overflow-hidden border"
        style={{
          borderRadius: "var(--radius-shell)",
          borderColor: "var(--color-glass-rim)",
          backgroundColor: "var(--color-paper-2)",
          minHeight: "min(60dvh, 470px)",
        }}
      >
        {/* Subtle poster tint & dramatic dark gradient scrim */}
        <div
          aria-hidden="true"
          className="absolute inset-0 pointer-events-none"
          style={{
            background: `radial-gradient(circle at 76% 32%, ${current.dominant_color}58 0%, transparent 58%), linear-gradient(100deg, var(--rich-espresso) 24%, var(--color-scrim) 64%, var(--color-scrim-soft) 100%)`,
          }}
        />

        <div className="relative z-10 grid grid-cols-1 md:grid-cols-[minmax(0,1.4fr)_minmax(0,0.85fr)] items-center gap-6 p-6 md:p-10">
          {/* Left editorial content */}
          <div ref={textGroupRef} className="flex flex-col gap-4 min-w-0">
            <div data-hero-stagger className="flex flex-wrap items-center gap-2">
              <span className="carousel-card-chip capitalize">{current.industry}</span>
              {current.genres.slice(0, 3).map((g) => (
                <span key={g} className="carousel-card-chip">
                  {g}
                </span>
              ))}
              {current.year && (
                <span className="carousel-card-chip tabular-figure">{current.year}</span>
              )}
            </div>

            <h1 style={{ fontSize: "var(--text-display)" }}>
              {titleWords.map((w, idx) => (
                <span key={`${current.id}-w-${idx}`} className="masked-word-wrap mr-[0.22em]">
                  <span className="masked-word-inner">{w}</span>
                </span>
              ))}
            </h1>

            <p data-hero-stagger className="hero-subtitle-italic">
              Curated spotlight in{" "}
              {current.industry === "tollywood"
                ? "Telugu cinema"
                : current.industry === "bollywood"
                  ? "Hindi cinema"
                  : "world cinema"}
            </p>

            <div data-hero-stagger className="flex flex-wrap items-center gap-4">
              <span
                className="tabular-figure inline-flex items-center gap-1.5 text-lg font-medium"
                style={{ color: "var(--color-accent)" }}
              >
                <Star size={18} fill="currentColor" aria-hidden="true" />
                {displayScore}
              </span>
              {current.runtime && (
                <span
                  className="tabular-figure text-sm"
                  style={{ color: "var(--color-ink-muted)" }}
                >
                  {Math.floor(current.runtime / 60)}h {current.runtime % 60}m
                </span>
              )}
              <span className="tabular-figure text-sm" style={{ color: "var(--color-ink-muted)" }}>
                {current.rating_count} ratings
              </span>
            </div>

            {/* Translucent poster-harmonized glass action dock */}
            <LiquidGlassSurface
              radius={20}
              blur={12}
              className="p-3 mt-1 inline-flex flex-wrap items-center gap-3 w-fit max-w-full"
            >
              <button
                type="button"
                className="cinema-btn cinema-btn-hero-primary"
                onMouseEnter={() => prefetchMovie(current.id)}
                onPointerDown={() => {
                  prefetchMovie(current.id);
                  preCapturedRectRef.current = captureSourceRect(posterWrapRef.current);
                }}
                onClick={() => {
                  const rect =
                    preCapturedRectRef.current ?? captureSourceRect(posterWrapRef.current);
                  preCapturedRectRef.current = null;
                  openMovie(current, posterWrapRef.current, { preCapturedRect: rect });
                }}
              >
                <Sparkles size={16} aria-hidden="true" />
                More like this
              </button>

              <button
                type="button"
                className={`cinema-btn ${inWatchlist ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
                onClick={() => {
                  setBookmarkPopped(true);
                  window.setTimeout(() => setBookmarkPopped(false), 320);
                  onToggleWatchlist(current.id);
                }}
              >
                <Bookmark
                  size={16}
                  fill={inWatchlist ? "currentColor" : "none"}
                  aria-hidden="true"
                  style={{
                    transform: bookmarkPopped ? "scale(1.25)" : "scale(1)",
                    transition: "transform 280ms var(--ease-cinema)",
                  }}
                />
                {inWatchlist ? "Saved" : "Watchlist"}
              </button>

              {user ? (
                <button
                  type="button"
                  className={`cinema-btn ${myRating ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
                  aria-expanded={showRater}
                  onClick={() => setShowRater((s) => !s)}
                >
                  <Star size={16} fill={myRating ? "currentColor" : "none"} aria-hidden="true" />
                  {myRating ? `Rated ${myRating.toFixed(1)}` : "Rate"}
                </button>
              ) : (
                <Link to="/auth" className="cinema-btn cinema-btn-ghost">
                  Sign in to rate
                </Link>
              )}
            </LiquidGlassSurface>

            {showRater && user && (
              <div className="pt-1">
                <StarRating
                  value={myRating}
                  onChange={(val) => {
                    onRateMovie(current.id, val);
                    setShowRater(false);
                  }}
                />
              </div>
            )}
          </div>

          {/* Right featured portrait poster */}
          <div className="flex flex-col items-center md:items-end justify-center gap-4">
            <div ref={posterWrapRef} style={{ width: "clamp(175px, 19vw, 240px)" }}>
              <HoverPosterCard
                movie={current}
                priority
                ariaLabel={`Open ${current.title}`}
                onPrefetch={() => prefetchMovie(current.id)}
                onPointerDownCaptureRect={(frameEl) => {
                  preCapturedRectRef.current = captureSourceRect(frameEl);
                }}
                onClick={(e) => {
                  const frame = e.currentTarget.querySelector<HTMLElement>("[data-poster-frame]");
                  const rect = preCapturedRectRef.current ?? captureSourceRect(frame);
                  preCapturedRectRef.current = null;
                  openMovie(current, frame, { preCapturedRect: rect });
                }}
                className="w-full"
              />
            </div>

            {movies.length > 1 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="cinema-btn cinema-btn-secondary"
                  aria-label="Previous spotlight film"
                  onClick={() => {
                    setShowRater(false);
                    setIndex((i) => (i - 1 + movies.length) % movies.length);
                  }}
                >
                  <ChevronLeft size={16} aria-hidden="true" />
                </button>
                <span
                  className="tabular-figure text-xs px-2"
                  style={{ color: "var(--color-ink-muted)" }}
                >
                  {(index % movies.length) + 1} / {movies.length}
                </span>
                <button
                  type="button"
                  className="cinema-btn cinema-btn-secondary"
                  aria-label="Next spotlight film"
                  onClick={() => {
                    setShowRater(false);
                    setIndex((i) => (i + 1) % movies.length);
                  }}
                >
                  <ChevronRight size={16} aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Sleek hero slide timer bar */}
        {movies.length > 1 && (
          <div className="hero-progress-track" aria-hidden="true">
            <div ref={progressBarRef} className="hero-progress-bar" />
          </div>
        )}
      </div>
    </section>
  );
}
