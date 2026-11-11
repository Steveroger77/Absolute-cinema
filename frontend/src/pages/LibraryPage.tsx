import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bookmark, Star, Trash2 } from "lucide-react";
import { AppShell } from "../components/AppShell";
import { HoverPosterCard } from "../components/HoverPosterCard";
import { StarRating } from "../components/StarRating";
import { useToast } from "../components/ToastProvider";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { api } from "../lib/api";
import { invalidateRecommendationQueries } from "../lib/queryInvalidation";

export function LibraryPage() {
  const [tab, setTab] = useState<"ratings" | "watchlist">("ratings");
  const { user, loading: authLoading } = useAuth();
  const { notify } = useToast();
  const { openMovie, prefetchMovie, captureSourceRect } = useMovieTransition();
  const preCapturedRectRef = useRef<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const queryClient = useQueryClient();

  const userKey = user?.id ?? "guest";

  const { data: ratings = [], isLoading: loadingRatings } = useQuery({
    queryKey: ["my-ratings", userKey],
    queryFn: api.getMyRatings,
    enabled: Boolean(user),
  });

  const { data: watchlist = [], isLoading: loadingWatchlist } = useQuery({
    queryKey: ["watchlist", userKey],
    queryFn: api.getWatchlist,
    enabled: Boolean(user),
  });

  const reRateMutation = useMutation({
    mutationFn: ({ movieId, rating }: { movieId: number; rating: number }) =>
      api.upsertRating(movieId, rating),
    onSuccess: (_data, vars) => {
      invalidateRecommendationQueries(queryClient, vars.movieId);
    },
    onError: (e: Error) => notify(e.message, "error"),
  });

  const removeRatingMutation = useMutation({
    mutationFn: (movieId: number) => api.deleteRating(movieId),
    onSuccess: (_data, movieId) => {
      invalidateRecommendationQueries(queryClient, movieId);
    },
    onError: (e: Error) => notify(e.message, "error"),
  });

  const removeWatchMutation = useMutation({
    mutationFn: (movieId: number) => api.removeWatchlist(movieId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["watchlist"] }),
    onError: (e: Error) => notify(e.message, "error"),
  });

  if (!authLoading && !user) {
    return (
      <AppShell>
        <div className="cinema-container py-20 text-center flex flex-col items-center gap-4">
          <h1 style={{ fontSize: "var(--text-section)" }}>Your Cinema Vault</h1>
          <p style={{ color: "var(--color-ink-muted)" }}>
            Sign in to view your ratings history, saved watchlist, and custom taste profile.
          </p>
          <Link to="/auth" className="cinema-btn cinema-btn-primary">
            Sign in
          </Link>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="cinema-container pt-6 pb-12">
        <div
          className="flex flex-col sm:flex-row sm:items-end justify-between gap-5 pb-7 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div className="flex flex-col gap-3">
            <h1 style={{ fontSize: "var(--text-display)" }}>My Vault</h1>
            <p
              className="text-sm tracking-wide"
              style={{ color: "var(--color-ink-muted)", opacity: 0.85 }}
            >
              Your ratings &amp; saved watchlist
            </p>
          </div>

          <div role="tablist" aria-label="Library sections" className="flex items-center gap-2">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "ratings"}
              onClick={() => setTab("ratings")}
              className={`cinema-btn ${tab === "ratings" ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
            >
              <Star size={16} aria-hidden="true" />
              Ratings ({ratings.length})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "watchlist"}
              onClick={() => setTab("watchlist")}
              className={`cinema-btn ${tab === "watchlist" ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
            >
              <Bookmark size={16} aria-hidden="true" />
              Watchlist ({watchlist.length})
            </button>
          </div>
        </div>

        {tab === "ratings" ? (
          loadingRatings ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="skeleton-block h-28" />
              ))}
            </div>
          ) : ratings.length === 0 ? (
            <div className="py-16 text-center flex flex-col items-center gap-4">
              <p style={{ color: "var(--color-ink-muted)" }}>
                You haven’t rated any films yet. Search and rate films you’ve watched to unlock
                personal recommendations.
              </p>
              <Link to="/onboarding" className="cinema-btn cinema-btn-primary">
                Choose &amp; rate films
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
              {ratings.map((item) => (
                <div
                  key={item.movie_id}
                  className="flex items-center gap-4 p-4 rounded-2xl border"
                  style={{
                    backgroundColor: "var(--color-paper-2)",
                    borderColor: "var(--color-rule)",
                  }}
                >
                  <HoverPosterCard
                    movie={item.movie}
                    lift={4}
                    scale={1.04}
                    maxParallax={4}
                    className="shrink-0"
                    style={{ width: 64 }}
                    ariaLabel={`View ${item.movie.title}`}
                    onPrefetch={() => prefetchMovie(item.movie_id)}
                    onPointerDownCaptureRect={(el) => {
                      preCapturedRectRef.current = captureSourceRect(el);
                    }}
                    onClick={(e) => {
                      const frame =
                        e.currentTarget.querySelector<HTMLElement>("[data-poster-frame]") ??
                        e.currentTarget;
                      const rect = preCapturedRectRef.current ?? captureSourceRect(frame);
                      preCapturedRectRef.current = null;
                      openMovie(item.movie, frame, { preCapturedRect: rect });
                    }}
                  />
                  <div className="min-w-0 flex-1 flex flex-col gap-2">
                    <Link
                      to={`/movie/${item.movie_id}`}
                      className="font-semibold truncate hover:text-[var(--soft-amber)]"
                      style={{ fontFamily: "var(--font-display)", fontSize: "1.15rem" }}
                    >
                      {item.movie.title}
                    </Link>
                    <StarRating
                      size={18}
                      value={item.rating}
                      onChange={(r) => reRateMutation.mutate({ movieId: item.movie_id, rating: r })}
                    />
                  </div>
                  <button
                    type="button"
                    aria-label={`Delete rating for ${item.movie.title}`}
                    onClick={() => removeRatingMutation.mutate(item.movie_id)}
                    className="cinema-btn cinema-btn-ghost px-2.5"
                  >
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )
        ) : loadingWatchlist ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-5 mt-6">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skeleton-block aspect-[3/4.2]" />
            ))}
          </div>
        ) : watchlist.length === 0 ? (
          <div className="py-16 text-center flex flex-col items-center gap-4">
            <p style={{ color: "var(--color-ink-muted)" }}>
              Your watchlist is empty. Save films from the spotlight or catalogue.
            </p>
            <Link to="/explore" className="cinema-btn cinema-btn-primary">
              Browse catalogue
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-5 mt-6">
            {watchlist.map((w) => (
              <div key={w.movie_id} className="group flex flex-col gap-2">
                <HoverPosterCard
                  movie={w.movie}
                  className="w-full"
                  ariaLabel={`View ${w.movie.title}`}
                  onPrefetch={() => prefetchMovie(w.movie_id)}
                  onPointerDownCaptureRect={(el) => {
                    preCapturedRectRef.current = captureSourceRect(el);
                  }}
                  onClick={(e) => {
                    const frame =
                      e.currentTarget.querySelector<HTMLElement>("[data-poster-frame]") ??
                      e.currentTarget;
                    const rect = preCapturedRectRef.current ?? captureSourceRect(frame);
                    preCapturedRectRef.current = null;
                    openMovie(w.movie, frame, { preCapturedRect: rect });
                  }}
                />
                <div className="flex items-center justify-between gap-2">
                  <Link
                    to={`/movie/${w.movie_id}`}
                    className="truncate font-medium"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {w.movie.title}
                  </Link>
                  <button
                    type="button"
                    aria-label={`Remove ${w.movie.title} from watchlist`}
                    onClick={() => removeWatchMutation.mutate(w.movie_id)}
                    className="cinema-btn cinema-btn-ghost px-2 py-1"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
