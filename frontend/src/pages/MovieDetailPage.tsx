import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import gsap from "gsap";
import { ArrowLeft, Bookmark, Clock, Star, Trash2 } from "lucide-react";
import { AppShell } from "../components/AppShell";
import { LiquidGlassSurface } from "../components/LiquidGlassSurface";
import { PosterCarousel } from "../components/PosterCarousel";
import { PosterImage } from "../components/PosterImage";
import { StarRating } from "../components/StarRating";
import { useToast } from "../components/ToastProvider";
import { useAmbient } from "../context/AmbientContext";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { api } from "../lib/api";
import { heroCtaGlassTokens } from "../lib/colorHarmony";
import { prefersReducedMotion } from "../lib/tier";

export function MovieDetailPage() {
  const { id } = useParams<{ id: string }>();
  const movieId = Number(id);
  const { user } = useAuth();
  const { setFromMovie } = useAmbient();
  const { notify } = useToast();
  const { registerDetailPoster, isPosterHidden, goBackFromMovie, getBackLabel } =
    useMovieTransition();
  const queryClient = useQueryClient();

  const posterBoxRef = useRef<HTMLDivElement | null>(null);
  const backdropGlowRef = useRef<HTMLDivElement | null>(null);
  const detailsColRef = useRef<HTMLDivElement | null>(null);
  const scoreNumRef = useRef<HTMLSpanElement | null>(null);
  const [bookmarkPopped, setBookmarkPopped] = useState(false);

  const {
    data: movie,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["movie", movieId, user?.id ?? "guest"],
    queryFn: () => api.getMovieDetail(movieId),
    enabled: Number.isFinite(movieId) && movieId > 0,
  });

  const { data: similarRes } = useQuery({
    queryKey: ["similar", movieId],
    queryFn: () => api.getSimilarMovies(movieId, 14),
    enabled: Number.isFinite(movieId) && movieId > 0,
  });

  const { data: explainRes } = useQuery({
    queryKey: ["recs", "explain", movieId, user?.id ?? "guest"],
    queryFn: () => api.getMovieExplain(movieId),
    enabled: Boolean(user && Number.isFinite(movieId) && movieId > 0),
  });

  useEffect(() => {
    if (movie) setFromMovie(movie);
  }, [movie, setFromMovie]);

  const ctaGlass = useMemo(
    () => (movie ? heroCtaGlassTokens(movie.dominant_color, movie.accent_color) : null),
    [movie]
  );

  // Register shared-element poster destination independently from entrance timeline
  useLayoutEffect(() => {
    if (!movie?.id) return;
    registerDetailPoster(movie.id, posterBoxRef.current);
  }, [movie?.id, registerDetailPoster]);

  // Run Ken-Burns, Masked word reveal, and Score count-up once per opened film ID
  useLayoutEffect(() => {
    if (!movie || prefersReducedMotion()) return;

    const targetScore =
      movie.tmdb_rating && movie.tmdb_rating > 0 ? movie.tmdb_rating : movie.rating_avg * 2;
    const scoreCounter = { value: 0 };

    const ctx = gsap.context(() => {
      if (backdropGlowRef.current) {
        gsap.fromTo(
          backdropGlowRef.current,
          { scale: 1.08, opacity: 0 },
          { scale: 1.0, opacity: 1, duration: 1.25, ease: "power2.out" }
        );
      }
      if (detailsColRef.current) {
        const words = detailsColRef.current.querySelectorAll(".masked-word-inner");
        const staggers = detailsColRef.current.querySelectorAll("[data-detail-stagger]");
        if (words.length) {
          gsap.fromTo(
            words,
            { yPercent: 112, opacity: 0 },
            {
              yPercent: 0,
              opacity: 1,
              duration: 0.65,
              stagger: 0.055,
              delay: 0.14,
              ease: "expo.out",
            }
          );
        }
        if (staggers.length) {
          gsap.fromTo(
            staggers,
            { y: 14, opacity: 0 },
            {
              y: 0,
              opacity: 1,
              duration: 0.56,
              stagger: 0.07,
              delay: 0.24,
              ease: "power3.out",
            }
          );
        }
      }
      if (scoreNumRef.current) {
        gsap.to(scoreCounter, {
          value: targetScore,
          duration: 0.8,
          delay: 0.25,
          ease: "power2.out",
          onUpdate: () => {
            if (scoreNumRef.current) {
              scoreNumRef.current.textContent = scoreCounter.value.toFixed(1);
            }
          },
        });
      }
    });

    return () => ctx.revert();
    // Only trigger when a different film opens, never on query refetch or mutation updates
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [movie?.id]);

  const rateMutation = useMutation({
    mutationFn: (rating: number) => api.upsertRating(movieId, rating),
    onMutate: async (rating: number) => {
      const key = ["movie", movieId, user?.id ?? "guest"];
      await queryClient.cancelQueries({ queryKey: key });
      const prev = queryClient.getQueryData(key);
      queryClient.setQueryData(key, (old: typeof movie) =>
        old ? { ...old, user_rating: rating } : old
      );
      return { prev, key };
    },
    onError: (e: Error, _rating, ctx) => {
      if (ctx?.prev !== undefined) queryClient.setQueryData(ctx.key, ctx.prev);
      notify(e.message, "error");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["movie", movieId] });
      queryClient.invalidateQueries({ queryKey: ["my-ratings"] });
      queryClient.invalidateQueries({ queryKey: ["recs"] });
      queryClient.invalidateQueries({ queryKey: ["because"] });
    },
  });

  const deleteRateMutation = useMutation({
    mutationFn: () => api.deleteRating(movieId),
    onMutate: async () => {
      const key = ["movie", movieId, user?.id ?? "guest"];
      await queryClient.cancelQueries({ queryKey: key });
      const prev = queryClient.getQueryData(key);
      queryClient.setQueryData(key, (old: typeof movie) =>
        old ? { ...old, user_rating: null } : old
      );
      return { prev, key };
    },
    onError: (e: Error, _vars, ctx) => {
      if (ctx?.prev !== undefined) queryClient.setQueryData(ctx.key, ctx.prev);
      notify(e.message, "error");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["movie", movieId] });
      queryClient.invalidateQueries({ queryKey: ["my-ratings"] });
      queryClient.invalidateQueries({ queryKey: ["recs"] });
      queryClient.invalidateQueries({ queryKey: ["because"] });
    },
  });

  const watchlistMutation = useMutation({
    mutationFn: async () => {
      if (movie?.in_watchlist) {
        await api.removeWatchlist(movieId);
      } else {
        await api.addWatchlist(movieId);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["movie", movieId] });
      queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
    onError: (e: Error) => notify(e.message, "error"),
  });

  if (isLoading) {
    return (
      <AppShell>
        <div className="cinema-container py-8 flex flex-col gap-6">
          <div className="skeleton-block h-10 w-36" />
          <div
            className="p-6 md:p-10 border grid grid-cols-1 md:grid-cols-[260px_minmax(0,1fr)] gap-8"
            style={{
              borderRadius: "var(--radius-shell)",
              borderColor: "var(--color-glass-rim)",
              backgroundColor: "var(--color-paper-2)",
            }}
          >
            <div
              className="skeleton-block mx-auto md:mx-0"
              style={{ width: "clamp(200px, 24vw, 260px)", aspectRatio: "3 / 4.2" }}
            />
            <div className="flex flex-col gap-4">
              <div className="skeleton-block h-12 w-3/4" />
              <div className="skeleton-block h-6 w-1/3" />
              <div className="skeleton-block h-28 w-full" />
              <div className="skeleton-block h-14 w-2/3" />
            </div>
          </div>
        </div>
      </AppShell>
    );
  }

  if (isError || !movie) {
    return (
      <AppShell>
        <div className="cinema-container py-20 text-center flex flex-col items-center gap-4">
          <h1 style={{ fontSize: "var(--text-section)" }}>Film not found</h1>
          <p style={{ color: "var(--color-ink-muted)" }}>
            This catalogue entry could not be located.
          </p>
          <button
            type="button"
            onClick={() => goBackFromMovie(null, null)}
            className="cinema-btn cinema-btn-primary"
          >
            <ArrowLeft size={16} aria-hidden="true" />
            {getBackLabel(null)}
          </button>
        </div>
      </AppShell>
    );
  }

  const displayScore =
    movie.tmdb_rating && movie.tmdb_rating > 0
      ? movie.tmdb_rating.toFixed(1)
      : (movie.rating_avg * 2).toFixed(1);
  const titleWords = movie.title.split(/\s+/).filter(Boolean);
  const heroVars = ctaGlass
    ? ({
        "--hero-cta-bg": ctaGlass.bg,
        "--hero-cta-border": ctaGlass.border,
        "--hero-cta-glow": ctaGlass.glow,
      } as CSSProperties)
    : undefined;

  return (
    <AppShell>
      <div className="cinema-container pt-4 pb-6" style={heroVars}>
        <button
          type="button"
          onClick={() => goBackFromMovie(movie, posterBoxRef.current)}
          className="cinema-btn cinema-btn-ghost mb-4 inline-flex"
        >
          <ArrowLeft size={16} aria-hidden="true" />
          {getBackLabel(movie)}
        </button>

        <div
          className="relative overflow-hidden border p-6 md:p-10"
          style={{
            borderRadius: "var(--radius-shell)",
            borderColor: "var(--color-glass-rim)",
            backgroundColor: "var(--color-paper-2)",
          }}
        >
          <div
            ref={backdropGlowRef}
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `radial-gradient(circle at 20% 25%, ${movie.dominant_color}48 0%, transparent 55%), radial-gradient(circle at 82% 72%, ${movie.accent_color}26 0%, transparent 60%)`,
              willChange: "transform, opacity",
            }}
          />

          <div className="relative z-10 grid grid-cols-1 md:grid-cols-[260px_minmax(0,1fr)] gap-8 items-start">
            <div
              ref={posterBoxRef}
              data-poster-frame="true"
              className="mx-auto md:mx-0 overflow-hidden border"
              style={{
                width: "clamp(200px, 24vw, 260px)",
                aspectRatio: "3 / 4.2",
                borderRadius: "var(--radius-card)",
                borderColor: "var(--glass-accent-border)",
                visibility: isPosterHidden(movie.id) ? "hidden" : "visible",
              }}
            >
              <PosterImage movie={movie} priority />
            </div>

            <div ref={detailsColRef} className="flex flex-col gap-5 min-w-0">
              <div data-detail-stagger className="flex flex-wrap items-center gap-2">
                <span className="carousel-card-chip capitalize">{movie.industry}</span>
                <span className="carousel-card-chip uppercase">{movie.language}</span>
                {movie.genres.map((g) => (
                  <Link
                    key={g}
                    to={`/explore?genre=${encodeURIComponent(g)}`}
                    className="carousel-card-chip hover:border-[var(--glass-accent-border)] border border-transparent"
                  >
                    {g}
                  </Link>
                ))}
              </div>

              <h1 style={{ fontSize: "var(--text-display)" }}>
                {titleWords.map((w, i) => (
                  <span key={`${movie.id}-dw-${i}`} className="masked-word-wrap mr-[0.22em]">
                    <span className="masked-word-inner">{w}</span>
                  </span>
                ))}
              </h1>

              <div
                data-detail-stagger
                className="flex flex-wrap items-center gap-5 text-sm"
                style={{ color: "var(--color-ink-muted)" }}
              >
                <span
                  className="tabular-figure inline-flex items-center gap-1.5 text-lg font-medium"
                  style={{ color: "var(--soft-amber)" }}
                >
                  <Star size={18} fill="currentColor" aria-hidden="true" />
                  <span ref={scoreNumRef}>{displayScore}</span>
                </span>
                {movie.year && <span className="tabular-figure">{movie.year}</span>}
                {movie.runtime && (
                  <span className="tabular-figure inline-flex items-center gap-1.5">
                    <Clock size={14} aria-hidden="true" />
                    {Math.floor(movie.runtime / 60)}h {movie.runtime % 60}m
                  </span>
                )}
                <span className="tabular-figure">{movie.rating_count} viewer ratings</span>
              </div>

              {movie.overview && (
                <p
                  data-detail-stagger
                  className="text-base leading-relaxed"
                  style={{ color: "var(--color-ink)" }}
                >
                  {movie.overview}
                </p>
              )}

              {(() => {
                const becauseTitles = (explainRes?.reasons ?? [])
                  .filter((r) => r.type === "because_you_rated" && r.title)
                  .map((r) => r.title)
                  .slice(0, 3);
                if (!becauseTitles.length) return null;
                return (
                  <p
                    data-detail-stagger
                    className="text-sm"
                    style={{ color: "var(--color-ink-muted)" }}
                  >
                    Recommended for you because you rated{" "}
                    <span style={{ color: "var(--soft-amber)" }}>{becauseTitles.join(", ")}</span>
                  </p>
                );
              })()}

              <dl
                data-detail-stagger
                className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t"
                style={{ borderColor: "var(--color-rule)" }}
              >
                {movie.director && (
                  <div>
                    <dt
                      className="text-xs font-semibold"
                      style={{ color: "var(--color-ink-subtle)" }}
                    >
                      Directed by
                    </dt>
                    <dd className="text-sm mt-0.5">{movie.director}</dd>
                  </div>
                )}
                {movie.cast && (
                  <div>
                    <dt
                      className="text-xs font-semibold"
                      style={{ color: "var(--color-ink-subtle)" }}
                    >
                      Featuring
                    </dt>
                    <dd className="text-sm mt-0.5">{movie.cast}</dd>
                  </div>
                )}
              </dl>

              {/* Translucent glass rating & watchlist dock */}
              <div data-detail-stagger>
                <LiquidGlassSurface
                  radius={20}
                  blur={12}
                  className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                >
                  <div className="flex flex-wrap items-center gap-3">
                    {user ? (
                      <>
                        <StarRating
                          value={movie.user_rating}
                          disabled={rateMutation.isPending}
                          onChange={(val) => rateMutation.mutate(val)}
                        />
                        {movie.user_rating !== null && (
                          <button
                            type="button"
                            onClick={() => deleteRateMutation.mutate()}
                            aria-label="Remove rating"
                            className="cinema-btn cinema-btn-ghost px-2"
                          >
                            <Trash2 size={16} aria-hidden="true" />
                          </button>
                        )}
                      </>
                    ) : (
                      <Link to="/auth" className="cinema-btn cinema-btn-hero-primary">
                        Sign in to rate this film
                      </Link>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      if (!user) {
                        notify("Sign in to build your watchlist.");
                        return;
                      }
                      setBookmarkPopped(true);
                      window.setTimeout(() => setBookmarkPopped(false), 320);
                      watchlistMutation.mutate();
                    }}
                    className={`cinema-btn ${movie.in_watchlist ? "cinema-btn-hero-primary" : "cinema-btn-secondary"}`}
                  >
                    <Bookmark
                      size={16}
                      fill={movie.in_watchlist ? "currentColor" : "none"}
                      aria-hidden="true"
                      style={{
                        transform: bookmarkPopped ? "scale(1.25)" : "scale(1)",
                        transition: "transform 280ms var(--ease-cinema)",
                      }}
                    />
                    {movie.in_watchlist ? "In watchlist" : "Add to watchlist"}
                  </button>
                </LiquidGlassSurface>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Similar films carousel */}
      {similarRes && similarRes.items.length > 0 && (
        <div id="similar">
          <PosterCarousel
            title="More like this"
            subtitle="Collaborative neighbors and thematic echoes"
            movies={similarRes.items.map((x) => x.movie)}
            syncGlobalAmbient
          />
        </div>
      )}
    </AppShell>
  );
}
