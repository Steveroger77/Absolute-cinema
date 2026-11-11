import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { Check } from "lucide-react";
import { AppShell } from "../components/AppShell";
import { HoverPosterCard } from "../components/HoverPosterCard";
import { StarRating } from "../components/StarRating";
import { useToast } from "../components/ToastProvider";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { api } from "../lib/api";
import type { Industry } from "../types/cinema";

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
  }, [user?.id, user?.preferred_genres, user?.preferred_industries]);

  const { data: starterMovies = [] } = useQuery({
    queryKey: ["onboarding-starters"],
    queryFn: () => api.getTrending(undefined, 12),
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

  const rateMutation = useMutation({
    mutationFn: ({ movieId, rating }: { movieId: number; rating: number }) =>
      api.upsertRating(movieId, rating),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-ratings"] });
      queryClient.invalidateQueries({ queryKey: ["recs"] });
      queryClient.invalidateQueries({ queryKey: ["because"] });
    },
    onError: (e: Error) => notify(e.message, "error"),
  });

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
            Sign in or create an account to save your genre taste and rate starter titles.
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
          className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-6 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div>
            <h1 style={{ fontSize: "var(--text-display)" }}>Shape your palate</h1>
            <p className="text-sm mt-2" style={{ color: "var(--color-ink-muted)" }}>
              Pick favorite industries, select genres, and rate 5 titles so collaborative filtering
              learns your taste.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <span className="tabular-figure text-sm" style={{ color: "var(--color-accent)" }}>
              {Math.min(5, ratedCount)} / 5 starter ratings
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

        {/* Step 3: Rate starter films */}
        <section>
          <h2 style={{ fontSize: "1.45rem" }} className="mb-2">
            Rate 5 films you know
          </h2>
          <p className="text-sm mb-5" style={{ color: "var(--color-ink-muted)" }}>
            Ratings immediately activate item-based and user-based neighbor scoring.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {starterMovies.map((m) => (
              <div
                key={m.id}
                className="flex items-center gap-4 p-3 rounded-2xl border"
                style={{
                  backgroundColor: "var(--color-paper-2)",
                  borderColor: "var(--color-rule)",
                }}
              >
                <HoverPosterCard
                  movie={m}
                  lift={4}
                  scale={1.04}
                  maxParallax={4}
                  className="shrink-0"
                  style={{ width: 64 }}
                  ariaLabel={`View ${m.title}`}
                  onPrefetch={() => prefetchMovie(m.id)}
                  onPointerDownCaptureRect={(el) => {
                    preCapturedRectRef.current = captureSourceRect(el);
                  }}
                  onClick={(e) => {
                    const frame =
                      e.currentTarget.querySelector<HTMLElement>("[data-poster-frame]") ??
                      e.currentTarget;
                    const rect = preCapturedRectRef.current ?? captureSourceRect(frame);
                    preCapturedRectRef.current = null;
                    openMovie(m, frame, { preCapturedRect: rect });
                  }}
                />
                <div className="min-w-0 flex-1 flex flex-col gap-2">
                  <div
                    className="font-semibold truncate"
                    style={{ fontFamily: "var(--font-display)", fontSize: "1.1rem" }}
                  >
                    {m.title}
                  </div>
                  <div className="text-xs capitalize" style={{ color: "var(--color-ink-muted)" }}>
                    {m.industry} {m.year ? `(${m.year})` : ""}
                  </div>
                  <StarRating
                    size={16}
                    value={ratedMap.get(m.id) ?? null}
                    onChange={(r) => {
                      setLocalRatings((prev) => ({ ...prev, [m.id]: r }));
                      rateMutation.mutate({ movieId: m.id, rating: r });
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
