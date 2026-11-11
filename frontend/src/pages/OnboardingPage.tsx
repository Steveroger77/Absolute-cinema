import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Search, X } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { HoverPosterCard } from "../components/HoverPosterCard";
import { StarRating } from "../components/StarRating";
import { useToast } from "../components/ToastProvider";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { api } from "../lib/api";
import { invalidateRecommendationQueries } from "../lib/queryInvalidation";
import type { Industry, MovieSummary } from "../types/cinema";

const ONBOARDING_GENRES = [
  "Action",
  "Adventure",
  "Animation",
  "Comedy",
  "Crime",
  "Drama",
  "Fantasy",
  "Horror",
  "Musical",
  "Mystery",
  "Romance",
  "Sci-Fi",
  "Thriller",
  "War",
];

const INDUSTRIES: Array<{ id: Industry; label: string }> = [
  { id: "hollywood", label: "Hollywood" },
  { id: "bollywood", label: "Bollywood" },
  { id: "tollywood", label: "Tollywood" },
];

function OnboardingMovieCard({
  movie,
  rating,
  onRate,
  onPrefetch,
  onPointerDownCaptureRect,
  onOpen,
}: {
  movie: MovieSummary;
  rating: number | null;
  onRate: (movie: MovieSummary, rating: number) => void;
  onPrefetch: (movieId: number) => void;
  onPointerDownCaptureRect: (el: HTMLElement) => void;
  onOpen: (movie: MovieSummary, el: HTMLElement) => void;
}) {
  return (
    <div
      className="flex items-center gap-4 p-3 rounded-2xl border transition-colors"
      style={{
        backgroundColor: "var(--color-paper-2)",
        borderColor: rating !== null ? "var(--glass-accent-border)" : "var(--color-rule)",
      }}
    >
      <HoverPosterCard
        movie={movie}
        lift={4}
        scale={1.04}
        maxParallax={4}
        className="shrink-0"
        style={{ width: 64 }}
        ariaLabel={`View ${movie.title}`}
        onPrefetch={() => onPrefetch(movie.id)}
        onPointerDownCaptureRect={onPointerDownCaptureRect}
        onClick={(e) => {
          const frame =
            e.currentTarget.querySelector<HTMLElement>("[data-poster-frame]") ?? e.currentTarget;
          onOpen(movie, frame);
        }}
      />
      <div className="min-w-0 flex-1 flex flex-col gap-2">
        <div
          className="font-semibold truncate"
          style={{ fontFamily: "var(--font-display)", fontSize: "1.1rem" }}
        >
          {movie.title}
        </div>
        <div className="text-xs capitalize" style={{ color: "var(--color-ink-muted)" }}>
          {movie.industry} {movie.year ? `(${movie.year})` : ""}
        </div>
        <StarRating size={16} value={rating} onChange={(r) => onRate(movie, r)} />
      </div>
    </div>
  );
}

export function OnboardingPage() {
  const { user, saveOnboarding } = useAuth();
  const { notify } = useToast();
  const { openMovie, prefetchMovie, captureSourceRect } = useMovieTransition();
  const preCapturedRectRef = useRef<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [selectedGenres, setSelectedGenres] = useState<string[]>(
    user?.preferred_genres?.length ? user.preferred_genres : ["Sci-Fi", "Thriller", "Drama"]
  );
  const [selectedIndustries, setSelectedIndustries] = useState<Industry[]>(
    user?.preferred_industries?.length
      ? user.preferred_industries
      : ["hollywood", "bollywood", "tollywood"]
  );
  const [localRatings, setLocalRatings] = useState<Record<number, number>>({});
  const [customRatedMovies, setCustomRatedMovies] = useState<Record<number, MovieSummary>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQuery(searchQuery.trim()), 200);
    return () => window.clearTimeout(t);
  }, [searchQuery]);

  useEffect(() => {
    setSelectedGenres(
      user?.preferred_genres?.length ? user.preferred_genres : ["Sci-Fi", "Thriller", "Drama"]
    );
    setSelectedIndustries(
      user?.preferred_industries?.length
        ? user.preferred_industries
        : ["hollywood", "bollywood", "tollywood"]
    );
    setLocalRatings({});
    setCustomRatedMovies({});
  }, [user?.id, user?.preferred_genres, user?.preferred_industries]);

  const { data: searchResults = [], isFetching: isSearching } = useQuery({
    queryKey: ["onboarding-search", debouncedQuery],
    queryFn: () => api.searchMovies(debouncedQuery, 12),
    enabled: Boolean(user) && debouncedQuery.length >= 1,
  });

  const genreKey = selectedGenres.slice(0, 3).join(",");
  const industryKey = selectedIndustries.join(",");

  const { data: quickPickMovies = [], isLoading: loadingQuickPicks } = useQuery({
    queryKey: ["onboarding-suggestions", genreKey, industryKey],
    queryFn: async () => {
      const genresToFetch = selectedGenres.length > 0 ? selectedGenres.slice(0, 3) : [""];
      const indFilter = selectedIndustries.length === 1 ? selectedIndustries[0] : undefined;
      const pages = await Promise.all(
        genresToFetch.map((g) =>
          api.getMovies({
            genre: g || undefined,
            industry: indFilter,
            sort: "popular",
            page_size: 9,
          })
        )
      );
      const seen = new Set<number>();
      const out: MovieSummary[] = [];
      for (const page of pages) {
        for (const m of page.items) {
          if (!selectedIndustries.includes(m.industry) || seen.has(m.id)) continue;
          seen.add(m.id);
          out.push(m);
          if (out.length >= 9) return out;
        }
      }
      return out;
    },
    enabled: Boolean(user),
  });

  const { data: existingRatings = [] } = useQuery({
    queryKey: ["my-ratings", user?.id ?? "guest"],
    queryFn: api.getMyRatings,
    enabled: Boolean(user),
  });

  const ratedMap = useMemo(() => {
    const m = new Map<number, number>();
    existingRatings.forEach((r) => m.set(r.movie_id, r.rating));
    Object.entries(localRatings).forEach(([k, v]) => m.set(Number(k), v));
    return m;
  }, [existingRatings, localRatings]);

  const ratedMoviesList = useMemo(() => {
    const seen = new Set<number>();
    const out: MovieSummary[] = [];
    Object.values(customRatedMovies).forEach((m) => {
      if (ratedMap.has(m.id) && !seen.has(m.id)) {
        seen.add(m.id);
        out.push(m);
      }
    });
    existingRatings.forEach((r) => {
      if (!seen.has(r.movie_id)) {
        seen.add(r.movie_id);
        out.push(r.movie);
      }
    });
    return out;
  }, [customRatedMovies, existingRatings, ratedMap]);

  const filteredQuickPicks = useMemo(
    () => quickPickMovies.filter((m) => !ratedMap.has(m.id)),
    [quickPickMovies, ratedMap]
  );

  const rateMutation = useMutation({
    mutationFn: ({ movieId, rating }: { movieId: number; rating: number }) =>
      api.upsertRating(movieId, rating),
    onSuccess: (_data, vars) => {
      invalidateRecommendationQueries(queryClient, vars.movieId);
    },
    onError: (e: Error) => notify(e.message, "error"),
  });

  const handleRateMovie = (movie: MovieSummary, rating: number) => {
    setLocalRatings((prev) => ({ ...prev, [movie.id]: rating }));
    setCustomRatedMovies((prev) => ({ ...prev, [movie.id]: movie }));
    rateMutation.mutate({ movieId: movie.id, rating });
  };

  const handleOpenCard = (movie: MovieSummary, frame: HTMLElement) => {
    const rect = preCapturedRectRef.current ?? captureSourceRect(frame);
    preCapturedRectRef.current = null;
    openMovie(movie, frame, { preCapturedRect: rect });
  };

  const finishMutation = useMutation({
    mutationFn: () => saveOnboarding(selectedGenres, selectedIndustries),
    onSuccess: () => {
      navigate("/");
    },
    onError: (e: Error) => notify(e.message, "error"),
  });

  const toggleGenre = (g: string) => {
    setSelectedGenres((prev) =>
      prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g].slice(0, 8)
    );
  };

  const toggleIndustry = (ind: Industry) => {
    setSelectedIndustries((prev) =>
      prev.includes(ind) ? (prev.length > 1 ? prev.filter((x) => x !== ind) : prev) : [...prev, ind]
    );
  };

  if (!user) {
    return (
      <AppShell>
        <div className="cinema-container py-20 text-center flex flex-col items-center gap-4">
          <h1 style={{ fontSize: "var(--text-section)" }}>Personalize your cinema</h1>
          <p style={{ color: "var(--color-ink-muted)" }}>
            Sign in or create an account to save your genre taste and rate your favorite films.
          </p>
          <Link to="/auth" className="cinema-btn cinema-btn-primary">
            Sign in
          </Link>
        </div>
      </AppShell>
    );
  }

  const ratedCount = ratedMap.size;

  return (
    <AppShell>
      <div className="cinema-container pt-6 pb-14 flex flex-col gap-10">
        <div
          className="flex flex-col md:flex-row md:items-end justify-between gap-5 pb-7 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div className="flex flex-col gap-3">
            <h1 style={{ fontSize: "var(--text-display)" }}>Shape your palate</h1>
            <p
              className="text-sm tracking-wide"
              style={{ color: "var(--color-ink-muted)", opacity: 0.85 }}
            >
              Pick favorite industries, genres, and search any film you’ve watched to rate.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <span className="tabular-figure text-sm" style={{ color: "var(--color-accent)" }}>
              {ratedCount === 0
                ? "0 rated"
                : ratedCount < 5
                  ? `${ratedCount} / 5 rated`
                  : `${ratedCount} rated`}
            </span>
            <button
              type="button"
              disabled={finishMutation.isPending}
              onClick={() => finishMutation.mutate()}
              className="cinema-btn cinema-btn-primary"
            >
              <Check size={16} aria-hidden="true" />
              {finishMutation.isPending ? "Saving…" : "Save preferences"}
            </button>
          </div>
        </div>

        {/* Step 1: Industries */}
        <section>
          <h2 style={{ fontSize: "1.45rem" }} className="mb-3">
            Industries
          </h2>
          <div className="flex flex-wrap gap-3">
            {INDUSTRIES.map((ind) => {
              const active = selectedIndustries.includes(ind.id);
              return (
                <button
                  key={ind.id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleIndustry(ind.id)}
                  className={`cinema-btn ${active ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
                >
                  {ind.label}
                </button>
              );
            })}
          </div>
        </section>

        {/* Step 2: Genres */}
        <section>
          <h2 style={{ fontSize: "1.45rem" }} className="mb-3">
            Favorite genres
          </h2>
          <div className="flex flex-wrap gap-2.5">
            {ONBOARDING_GENRES.map((g) => {
              const active = selectedGenres.includes(g);
              return (
                <button
                  key={g}
                  type="button"
                  aria-pressed={active}
                  onClick={() => toggleGenre(g)}
                  className={`cinema-btn ${active ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
                >
                  {g}
                </button>
              );
            })}
          </div>
        </section>

        {/* Step 3: Search & rate films of your choice */}
        <section className="flex flex-col gap-6">
          <div>
            <h2 style={{ fontSize: "1.45rem" }} className="mb-2">
              Search &amp; rate films of your choice
            </h2>
            <p className="text-sm mb-4" style={{ color: "var(--color-ink-muted)" }}>
              Type any title, director, or actor you already know and rate it right away.
            </p>

            <div className="relative max-w-xl">
              <Search
                size={18}
                aria-hidden="true"
                className="absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none"
                style={{ color: "var(--color-accent)" }}
              />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Search films to rate"
                placeholder="Search any film to rate (e.g. The Dark Knight, 3 Idiots, RRR)…"
                className="cinema-input"
                style={{ paddingLeft: "2.65rem", paddingRight: "2.5rem" }}
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  aria-label="Clear search"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-[var(--color-paper-3)]"
                  style={{ color: "var(--color-ink-muted)" }}
                >
                  <X size={16} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>

          {debouncedQuery.length >= 1 && (
            <div>
              <h3
                className="text-sm font-medium mb-3"
                style={{ fontFamily: "var(--font-body)", color: "var(--color-ink-muted)" }}
              >
                {isSearching
                  ? `Searching for “${debouncedQuery}”…`
                  : searchResults.length > 0
                    ? `Matches for “${debouncedQuery}”`
                    : `No films matched “${debouncedQuery}”. Try another title.`}
              </h3>
              {searchResults.length > 0 && (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {searchResults.map((m) => (
                    <OnboardingMovieCard
                      key={`search-${m.id}`}
                      movie={m}
                      rating={ratedMap.get(m.id) ?? null}
                      onRate={handleRateMovie}
                      onPrefetch={prefetchMovie}
                      onPointerDownCaptureRect={(el) => {
                        preCapturedRectRef.current = captureSourceRect(el);
                      }}
                      onOpen={handleOpenCard}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {ratedMoviesList.length > 0 && (
            <div>
              <h3
                className="text-sm font-medium mb-3"
                style={{ fontFamily: "var(--font-body)", color: "var(--color-accent)" }}
              >
                Your rated films ({ratedMoviesList.length})
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {ratedMoviesList.map((m) => (
                  <OnboardingMovieCard
                    key={`rated-${m.id}`}
                    movie={m}
                    rating={ratedMap.get(m.id) ?? null}
                    onRate={handleRateMovie}
                    onPrefetch={prefetchMovie}
                    onPointerDownCaptureRect={(el) => {
                      preCapturedRectRef.current = captureSourceRect(el);
                    }}
                    onOpen={handleOpenCard}
                  />
                ))}
              </div>
            </div>
          )}

          {debouncedQuery.length === 0 && (
            <div>
              <h3
                className="text-sm font-medium mb-3"
                style={{ fontFamily: "var(--font-body)", color: "var(--color-ink-muted)" }}
              >
                Or quick-rate acclaimed films from your genres
              </h3>
              {loadingQuickPicks ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {[1, 2, 3, 4, 5, 6].map((i) => (
                    <div key={i} className="skeleton-block h-24 rounded-2xl" />
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {filteredQuickPicks.map((m) => (
                    <OnboardingMovieCard
                      key={`quick-${m.id}`}
                      movie={m}
                      rating={ratedMap.get(m.id) ?? null}
                      onRate={handleRateMovie}
                      onPrefetch={prefetchMovie}
                      onPointerDownCaptureRect={(el) => {
                        preCapturedRectRef.current = captureSourceRect(el);
                      }}
                      onOpen={handleOpenCard}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
