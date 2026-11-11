import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { AppShell } from "../components/AppShell";
import { HeroFeature } from "../components/HeroFeature";
import { PosterCarousel } from "../components/PosterCarousel";
import { PosterImage } from "../components/PosterImage";
import { useToast } from "../components/ToastProvider";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { usePosterHover } from "../hooks/usePosterHover";
import { api } from "../lib/api";
import { invalidateRecommendationQueries } from "../lib/queryInvalidation";
import { prefersReducedMotion } from "../lib/tier";
import type { MovieSummary, RecommendedMovie, UserRatingItem } from "../types/cinema";

const DEFAULT_GENRE_ORDER = [
  "Action",
  "Sci-Fi",
  "Drama",
  "Thriller",
  "Romance",
  "Comedy",
  "Mystery",
  "Horror",
];

const GENRE_SUBTITLES: Record<string, string> = {
  Action: "High-stakes spectacles and relentless momentum",
  "Sci-Fi": "Speculative worlds and visionary futures",
  Drama: "Character studies across eras and continents",
  Thriller: "Taut suspense and razor-sharp twists",
  Romance: "Intimate portraits of longing and connection",
  Comedy: "Sharp wit, satire, and warm ensembles",
  Mystery: "Whodunits, noir investigations, and secrets",
  Horror: "Atmospheric dread and folklore chills",
  Adventure: "Sweeping expeditions and audacious quests",
  Crime: "Heists, underworld chronicles, and moral reckonings",
  Fantasy: "Mythic realms and heightened imagination",
  Animation: "Hand-crafted and stylized animated landmarks",
  Family: "Generational favorites and heartfelt journeys",
  Musical: "Rhythm, choreography, and soaring score sequences",
  War: "Frontline chronicles and human resilience",
  Western: "Frontier legends and sunlit standoffs",
  Documentary: "Real stories and investigative portraiture",
  "Film-Noir": "Shadow-drenched classics and fatalistic intrigue",
};

const INDUSTRY_META: Record<
  "hollywood" | "bollywood" | "tollywood",
  { title: string; subtitle: string }
> = {
  hollywood: {
    title: "Hollywood",
    subtitle: "Studio landmarks, auteur classics, and modern sci-fi",
  },
  bollywood: {
    title: "Bollywood",
    subtitle: "Hindi-language epics, noir thrillers, and contemporary drama",
  },
  tollywood: {
    title: "Tollywood",
    subtitle: "Telugu-language mythology, high-octane action, and indie gems",
  },
};

function LazyGenreRow({
  genre,
  subtitle,
  industry,
  userKey,
  onRegisterNode,
}: {
  genre: string;
  subtitle: string;
  industry?: string;
  userKey: string | number;
  onRegisterNode: (genre: string, el: HTMLDivElement | null) => void;
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || visible) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          obs.disconnect();
        }
      },
      { rootMargin: "320px 0px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [visible]);

  const { data, isLoading } = useQuery({
    queryKey: ["recs", "genre", genre, userKey, industry || "all"],
    queryFn: () => api.getGenreRecommendations(genre, 16, industry),
    enabled: visible,
  });

  const movies = useMemo(() => data?.items.map((x) => x.movie) ?? [], [data]);
  const personalNote =
    data?.strategy === "personalized_genre_cf"
      ? `Ranked for your taste in ${genre}`
      : data?.strategy === "onboarding_cold_start"
        ? `Curated for your ${genre} onboarding pick`
        : subtitle;

  return (
    <div
      ref={(el) => {
        sentinelRef.current = el;
        onRegisterNode(genre, el);
      }}
      style={{ contentVisibility: "auto", containIntrinsicSize: "420px" }}
    >
      {!visible || isLoading ? (
        <section className="cinema-container py-6">
          <div className="skeleton-block h-8 w-44 mb-4" />
          <div className="skeleton-block w-full h-80" />
        </section>
      ) : movies.length > 0 ? (
        <PosterCarousel title={genre} subtitle={personalNote} movies={movies} />
      ) : null}
    </div>
  );
}

function ExplainedPosterCard({
  item,
  onPrefetch,
  onCaptureRect,
  onOpen,
}: {
  item: RecommendedMovie;
  onPrefetch: (id: number) => void;
  onCaptureRect: (el?: HTMLElement | null) => {
    top: number;
    left: number;
    width: number;
    height: number;
  } | null;
  onOpen: (
    movie: MovieSummary,
    sourceEl: HTMLElement | null,
    preCapturedRect: { top: number; left: number; width: number; height: number } | null
  ) => void;
}) {
  const { hoverLayerRef, mediaLayerRef, glowLayerRef, sheenLayerRef, hitProps } = usePosterHover({
    lift: 3,
    scale: 1.04,
    mediaScale: 1.06,
    maxParallax: 4,
    onEnterExtra: () => onPrefetch(item.movie.id),
  });
  const preRectRef = useRef<{ top: number; left: number; width: number; height: number } | null>(
    null
  );
  const reasons = item.reasons.filter((r) => r.title);

  return (
    <Link
      to={`/movie/${item.movie.id}`}
      onMouseEnter={() => onPrefetch(item.movie.id)}
      onPointerDown={() => {
        onPrefetch(item.movie.id);
        preRectRef.current = onCaptureRect(hoverLayerRef.current);
      }}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        const rect = preRectRef.current ?? onCaptureRect(hoverLayerRef.current);
        preRectRef.current = null;
        onOpen(item.movie, hoverLayerRef.current, rect);
      }}
      className="flex items-center gap-4 p-4 rounded-2xl border text-left transition-colors hover:bg-[var(--color-paper-3)]"
      style={{
        backgroundColor: "var(--color-paper-2)",
        borderColor: "var(--color-rule)",
      }}
    >
      <div
        className="poster-slot relative shrink-0"
        style={{ width: 64, aspectRatio: "3 / 4.2" }}
        {...hitProps}
      >
        <div
          ref={glowLayerRef}
          aria-hidden="true"
          className="poster-glow-layer"
          style={
            item.movie.accent_color
              ? {
                  background: `radial-gradient(ellipse at 50% 60%, ${item.movie.accent_color}52 0%, transparent 74%)`,
                }
              : undefined
          }
        />
        <div
          ref={hoverLayerRef}
          data-movie-poster-id={item.movie.id}
          data-poster-frame="true"
          className="poster-hover-layer"
        >
          <div ref={mediaLayerRef} className="poster-media-layer">
            <PosterImage movie={item.movie} />
          </div>
          <div ref={sheenLayerRef} aria-hidden="true" className="poster-sheen-layer" />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="truncate" style={{ fontSize: "1.2rem" }}>
          {item.movie.title}
        </h3>
        <p className="text-xs mt-1" style={{ color: "var(--color-ink-muted)" }}>
          Because you rated{" "}
          <span style={{ color: "var(--soft-amber)" }}>
            {reasons.map((r) => r.title).join(", ")}
          </span>
        </p>
        <div className="flex items-center gap-2 mt-2">
          <span className="carousel-card-chip capitalize">{item.movie.industry}</span>
          <span className="carousel-card-chip tabular-figure">
            Match {(item.score * 20).toFixed(0)}%
          </span>
        </div>
      </div>
    </Link>
  );
}

export function HomePage() {
  const [industry, setIndustry] = useState<string | undefined>(undefined);
  const { user } = useAuth();
  const { notify } = useToast();
  const { openMovie, prefetchMovie, captureSourceRect } = useMovieTransition();
  const queryClient = useQueryClient();
  const userKey = user?.id ?? "guest";

  const { data: trending = [], isLoading: loadingTrending } = useQuery({
    queryKey: ["trending", industry || "all"],
    queryFn: () => api.getTrending(industry, 15),
  });

  const { data: myRatings = [] } = useQuery({
    queryKey: ["my-ratings", userKey],
    queryFn: api.getMyRatings,
    enabled: Boolean(user),
  });

  const hasRatedFilms = Boolean(user && myRatings.length > 0);

  const { data: recRes, isLoading: loadingRecs } = useQuery({
    queryKey: ["recs", "me", userKey, industry || "all"],
    queryFn: () => api.getRecommendationsMe({ k: 18, industry }),
    enabled: hasRatedFilms,
  });

  const { data: becauseRes } = useQuery({
    queryKey: ["because", userKey, industry || "all"],
    queryFn: () => api.getBecauseYouRated(industry, 3, 16),
    enabled: hasRatedFilms,
  });

  const { data: superheroRes, isLoading: loadingSuperheroes } = useQuery({
    queryKey: ["superheroes", userKey, industry || "all"],
    queryFn: () => api.getSuperheroRecommendations(100, industry),
  });

  const { data: hollyRec } = useQuery({
    queryKey: ["recs", "industry", "hollywood", userKey],
    queryFn: () => api.getIndustryRecommendations("hollywood", 16),
    enabled: !industry,
  });

  const { data: bollyRec } = useQuery({
    queryKey: ["recs", "industry", "bollywood", userKey],
    queryFn: () => api.getIndustryRecommendations("bollywood", 16),
    enabled: !industry,
  });

  const { data: tollyRec } = useQuery({
    queryKey: ["recs", "industry", "tollywood", userKey],
    queryFn: () => api.getIndustryRecommendations("tollywood", 16),
    enabled: !industry,
  });

  const { data: watchlist = [] } = useQuery({
    queryKey: ["watchlist", userKey],
    queryFn: api.getWatchlist,
    enabled: Boolean(user),
  });

  const watchlistIds = useMemo(() => new Set(watchlist.map((w) => w.movie_id)), [watchlist]);
  const userRatingsMap = useMemo(
    () => new Map(myRatings.map((r) => [r.movie_id, r.rating])),
    [myRatings]
  );

  const watchlistMutation = useMutation({
    mutationFn: async (movieId: number) => {
      if (watchlistIds.has(movieId)) {
        await api.removeWatchlist(movieId);
      } else {
        await api.addWatchlist(movieId);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlist"] });
    },
    onError: (err: Error) => notify(err.message, "error"),
  });

  const rateMutation = useMutation({
    mutationFn: ({ movieId, rating }: { movieId: number; rating: number }) =>
      api.upsertRating(movieId, rating),
    onMutate: async ({ movieId, rating }) => {
      const rKey = ["my-ratings", userKey];
      await queryClient.cancelQueries({ queryKey: rKey });
      const prev = queryClient.getQueryData<UserRatingItem[]>(rKey);
      const baseList = prev ?? [];
      const exists = baseList.some((r) => r.movie_id === movieId);
      const matchMovie =
        trending.find((m) => m.id === movieId) ??
        superheroMovies.find((m) => m.id === movieId) ??
        pickedMovies.find((m) => m.id === movieId);
      const nextList = exists
        ? baseList.map((r) => (r.movie_id === movieId ? { ...r, rating } : r))
        : matchMovie
          ? [
              {
                movie_id: movieId,
                rating,
                source: "user",
                rated_at: new Date().toISOString(),
                movie: matchMovie,
              },
              ...baseList,
            ]
          : baseList;
      queryClient.setQueryData(rKey, nextList);
      return { prev, rKey };
    },
    onError: (err: Error, _vars, ctx) => {
      if (ctx?.prev !== undefined) queryClient.setQueryData(ctx.rKey, ctx.prev);
      notify(err.message, "error");
    },
    onSettled: (_data, _err, vars) => {
      invalidateRecommendationQueries(queryClient, vars.movieId);
    },
  });

  const handleToggleWatchlist = (movieId: number) => {
    if (!user) {
      notify("Sign in to save films to your watchlist.");
      return;
    }
    watchlistMutation.mutate(movieId);
  };

  const handleRate = (movieId: number, rating: number) => {
    if (!user) {
      notify("Sign in to rate films and personalize recommendations.");
      return;
    }
    rateMutation.mutate({ movieId, rating });
  };

  const superheroMovies: MovieSummary[] = useMemo(
    () => (superheroRes?.items ?? []).map((it) => it.movie),
    [superheroRes]
  );

  const pickedMovies: MovieSummary[] = useMemo(
    () => (hasRatedFilms ? (recRes?.items ?? []).map((it) => it.movie) : []),
    [hasRatedFilms, recRes]
  );

  const explainedItems: RecommendedMovie[] = useMemo(
    () =>
      hasRatedFilms
        ? (recRes?.items ?? [])
            .filter((it) => it.reasons.some((r) => r.type === "because_you_rated" && r.title))
            .slice(0, 4)
        : [],
    [hasRatedFilms, recRes]
  );

  const industryOrder = useMemo(() => {
    const raw = hasRatedFilms
      ? (becauseRes?.industry_order ?? ["hollywood", "bollywood", "tollywood"])
      : ["hollywood", "bollywood", "tollywood"];
    return raw.filter(
      (i): i is "hollywood" | "bollywood" | "tollywood" =>
        i === "hollywood" || i === "bollywood" || i === "tollywood"
    );
  }, [hasRatedFilms, becauseRes?.industry_order]);

  const industryRecsMap = useMemo(
    () => ({
      hollywood: hollyRec,
      bollywood: bollyRec,
      tollywood: tollyRec,
    }),
    [hollyRec, bollyRec, tollyRec]
  );

  const orderedGenres = useMemo(() => {
    const src =
      hasRatedFilms && becauseRes?.genre_order?.length
        ? becauseRes.genre_order
        : DEFAULT_GENRE_ORDER;
    return src.slice(0, 8);
  }, [hasRatedFilms, becauseRes?.genre_order]);

  // Smooth FLIP reorder when personalized genre row priority changes live
  const genreNodeMapRef = useRef<Map<string, HTMLDivElement>>(new Map());
  const prevGenreTopsRef = useRef<Map<string, number>>(new Map());
  const prevGenreSigRef = useRef<string | null>(null);
  const genreSig = orderedGenres.join(",");

  const registerGenreNode = (genre: string, el: HTMLDivElement | null) => {
    if (el) genreNodeMapRef.current.set(genre, el);
    else genreNodeMapRef.current.delete(genre);
  };

  useLayoutEffect(() => {
    const prevSig = prevGenreSigRef.current;
    prevGenreSigRef.current = genreSig;
    const nextTops = new Map<string, number>();
    genreNodeMapRef.current.forEach((node, g) => {
      nextTops.set(g, node.getBoundingClientRect().top);
    });
    if (prevSig !== null && prevSig !== genreSig && !prefersReducedMotion()) {
      orderedGenres.forEach((g) => {
        const node = genreNodeMapRef.current.get(g);
        const oldTop = prevGenreTopsRef.current.get(g);
        const newTop = nextTops.get(g);
        if (node && oldTop !== undefined && newTop !== undefined) {
          const dy = oldTop - newTop;
          if (Math.abs(dy) > 4 && Math.abs(dy) < 2200) {
            gsap.fromTo(
              node,
              { y: dy },
              { y: 0, duration: 0.52, ease: "expo.out", clearProps: "transform" }
            );
          }
        }
      });
    }
    prevGenreTopsRef.current = nextTops;
  }, [genreSig, orderedGenres]);

  const superheroSubtitle =
    superheroRes?.strategy === "personalized_superheroes"
      ? "Every superhero film in the catalogue — ordered dynamically by your taste"
      : industry
        ? `Every ${industry} superhero film in the catalogue`
        : "Every superhero film across Hollywood, Bollywood, and Tollywood";

  const pickedSubtitle =
    recRes?.strategy === "personalized_hybrid_cf"
      ? "Similar to the films you’ve rated — updates live with every star"
      : "Recommendations similar to your rated films";

  return (
    <AppShell activeIndustry={industry} onSelectIndustry={setIndustry}>
      {/* Hero spotlight */}
      {loadingTrending ? (
        <section className="cinema-container pt-4 pb-6">
          <div className="skeleton-block w-full h-[420px]" />
        </section>
      ) : (
        <HeroFeature
          movies={trending}
          watchlistIds={watchlistIds}
          userRatings={userRatingsMap}
          onToggleWatchlist={handleToggleWatchlist}
          onRateMovie={handleRate}
        />
      )}

      {/* Onboarding CTA banner for signed-in users without completed onboarding */}
      {user && !user.onboarding_completed && (
        <section className="cinema-container py-3">
          <div
            className="glass-surface rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border"
            style={{ borderColor: "var(--glass-accent-border)" }}
          >
            <div>
              <h2 style={{ fontSize: "1.35rem" }}>Tune your taste profile</h2>
              <p className="text-sm mt-1" style={{ color: "var(--color-ink-muted)" }}>
                Choose your favorite industries and rate 5 titles so collaborative filtering locks
                onto your voice.
              </p>
            </div>
            <Link to="/onboarding" className="cinema-btn cinema-btn-primary shrink-0">
              Start onboarding
            </Link>
          </div>
        </section>
      )}

      {/* Superheroes — full superhero collection across industries */}
      {loadingSuperheroes ? (
        <section className="cinema-container py-6">
          <div className="skeleton-block h-8 w-52 mb-4" />
          <div className="skeleton-block w-full h-80" />
        </section>
      ) : superheroMovies.length > 0 ? (
        <PosterCarousel
          title="Superheroes"
          subtitle={superheroSubtitle}
          movies={superheroMovies}
          syncGlobalAmbient
          priorityFirst
        />
      ) : null}

      {/* Picked for you — only appears after the user rates at least one film */}
      {hasRatedFilms &&
        (loadingRecs ? (
          <section className="cinema-container py-6">
            <div className="skeleton-block h-8 w-52 mb-4" />
            <div className="skeleton-block w-full h-80" />
          </section>
        ) : pickedMovies.length > 0 ? (
          <PosterCarousel
            title="Picked for you"
            subtitle={pickedSubtitle}
            movies={pickedMovies}
            syncGlobalAmbient
          />
        ) : null)}

      {/* Transparent "Because you rated..." explanations */}
      {hasRatedFilms && explainedItems.length > 0 && (
        <section className="cinema-container py-8" aria-label="Recommendation explanations">
          <div className="flex items-end justify-between gap-4 mb-5">
            <div>
              <h2 style={{ fontSize: "var(--text-section)" }}>Why these stood out</h2>
              <p className="text-sm mt-1" style={{ color: "var(--color-ink-muted)" }}>
                Item neighbors connecting your past ratings to tonight’s shortlist
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {explainedItems.map((item) => (
              <ExplainedPosterCard
                key={item.movie.id}
                item={item}
                onPrefetch={prefetchMovie}
                onCaptureRect={captureSourceRect}
                onOpen={(movie, sourceEl, preCapturedRect) =>
                  openMovie(movie, sourceEl, { preCapturedRect })
                }
              />
            ))}
          </div>
        </section>
      )}

      {/* Dedicated "Because you rated X" nearest-neighbor shelves */}
      {(hasRatedFilms ? (becauseRes?.rows ?? []) : []).map((row) => (
        <PosterCarousel
          key={`because-${row.anchor.id}`}
          title={`Because you rated ${row.anchor.title}`}
          subtitle={`Rated ${row.user_rating.toFixed(1)} stars — closest films in story & viewer taste`}
          movies={row.items.map((x) => x.movie)}
        />
      ))}

      {/* Personalized & adaptively ordered Industry shelves when viewing All Cinema */}
      {!industry &&
        industryOrder.map((indKey) => {
          const rec = industryRecsMap[indKey];
          const movies = (rec?.items ?? []).map((it) => it.movie);
          if (movies.length === 0) return null;
          const meta = INDUSTRY_META[indKey];
          const subtitle =
            rec?.strategy === "personalized_industry_cf"
              ? `Ranked for your taste across ${meta.title}`
              : meta.subtitle;
          return (
            <PosterCarousel
              key={`ind-${indKey}`}
              title={meta.title}
              subtitle={subtitle}
              movies={movies}
            />
          );
        })}

      {/* Lazy-loaded genre carousels ordered strongest-affinity first */}
      {orderedGenres.map((genreName) => (
        <LazyGenreRow
          key={genreName}
          genre={genreName}
          subtitle={
            GENRE_SUBTITLES[genreName] ?? `Acclaimed ${genreName} cinema tuned to your taste`
          }
          industry={industry}
          userKey={userKey}
          onRegisterNode={registerGenreNode}
        />
      ))}
    </AppShell>
  );
}
