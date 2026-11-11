import { useLayoutEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import gsap from "gsap";
import { Star } from "lucide-react";
import { AppShell } from "../components/AppShell";
import { GlassSelect, type GlassSelectOption } from "../components/GlassSelect";
import { HoverPosterCard } from "../components/HoverPosterCard";
import { useMovieTransition } from "../context/TransitionContext";
import { api } from "../lib/api";
import { prefersReducedMotion } from "../lib/tier";

export function ExplorePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page") || 1) || 1);
  const industry = searchParams.get("industry") || "";
  const genre = searchParams.get("genre") || "";
  const sort = searchParams.get("sort") || "popular";

  const { openMovie, prefetchMovie, captureSourceRect } = useMovieTransition();
  const gridRef = useRef<HTMLDivElement | null>(null);
  const cardNodeMapRef = useRef<Map<number, HTMLElement>>(new Map());
  const prevBoxesRef = useRef<Map<number, { left: number; top: number }>>(new Map());
  const revealedIdsRef = useRef<Set<number>>(new Set());

  const updateFilterParams = (next: {
    page?: number;
    industry?: string;
    genre?: string;
    sort?: string;
  }) => {
    const p = new URLSearchParams();
    const pVal = next.page ?? page;
    const iVal = next.industry !== undefined ? next.industry : industry;
    const gVal = next.genre !== undefined ? next.genre : genre;
    const sVal = next.sort !== undefined ? next.sort : sort;
    if (pVal > 1) p.set("page", String(pVal));
    if (iVal) p.set("industry", iVal);
    if (gVal) p.set("genre", gVal);
    if (sVal && sVal !== "popular") p.set("sort", sVal);
    setSearchParams(p, { replace: true });
  };

  const { data: genres = [] } = useQuery({
    queryKey: ["genres"],
    queryFn: api.getGenres,
  });

  const { data, isLoading, isError } = useQuery({
    queryKey: ["catalogue", page, industry, genre, sort],
    queryFn: () =>
      api.getMovies({
        page,
        page_size: 24,
        industry: industry || undefined,
        genre: genre || undefined,
        sort,
      }),
  });

  const captureGridPositions = () => {
    const map = new Map<number, { left: number; top: number }>();
    cardNodeMapRef.current.forEach((node, id) => {
      const r = node.getBoundingClientRect();
      map.set(id, { left: r.left, top: r.top });
    });
    prevBoxesRef.current = map;
  };

  useLayoutEffect(() => {
    const items = data?.items ?? [];
    if (!items.length || prefersReducedMotion()) return;

    const prevMap = prevBoxesRef.current;
    const enteringNodes: HTMLElement[] = [];

    const ctx = gsap.context(() => {
      items.forEach((m) => {
        const el = cardNodeMapRef.current.get(m.id);
        if (!el) return;
        const oldBox = prevMap.get(m.id);
        if (oldBox) {
          const newBox = el.getBoundingClientRect();
          const dx = oldBox.left - newBox.left;
          const dy = oldBox.top - newBox.top;
          if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
            gsap.fromTo(
              el,
              { x: dx, y: dy },
              { x: 0, y: 0, duration: 0.48, ease: "power3.out", clearProps: "transform" }
            );
          }
        } else if (!revealedIdsRef.current.has(m.id)) {
          enteringNodes.push(el);
        }
      });
    }, gridRef);

    if (enteringNodes.length > 0) {
      let pendingBatch: HTMLElement[] = [];
      let rafScheduled = false;
      const flushBatch = () => {
        rafScheduled = false;
        const batch = pendingBatch.slice();
        pendingBatch = [];
        if (batch.length === 0) return;
        gsap.fromTo(
          batch,
          { opacity: 0, y: 18, scale: 0.97 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.48,
            stagger: 0.032,
            ease: "expo.out",
            clearProps: "transform,opacity",
          }
        );
      };

      const obs = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              const target = entry.target as HTMLElement;
              const mid = Number(target.dataset.cardMovieId);
              if (Number.isFinite(mid)) revealedIdsRef.current.add(mid);
              obs.unobserve(target);
              pendingBatch.push(target);
              if (!rafScheduled) {
                rafScheduled = true;
                window.requestAnimationFrame(flushBatch);
              }
            }
          });
        },
        { threshold: 0.05, rootMargin: "40px 0px" }
      );

      enteringNodes.forEach((el) => {
        el.style.opacity = "0";
        obs.observe(el);
      });

      return () => {
        obs.disconnect();
        ctx.revert();
      };
    }

    return () => ctx.revert();
  }, [data?.items]);

  const industryOptions: GlassSelectOption[] = useMemo(
    () => [
      { value: "", label: "All industries" },
      { value: "hollywood", label: "Hollywood" },
      { value: "bollywood", label: "Bollywood" },
      { value: "tollywood", label: "Tollywood" },
    ],
    []
  );

  const genreOptions: GlassSelectOption[] = useMemo(
    () => [
      { value: "", label: "All genres" },
      ...genres.map((g) => ({
        value: g.name,
        label: g.name,
        count: g.movie_count,
      })),
    ],
    [genres]
  );

  const sortOptions: GlassSelectOption[] = useMemo(
    () => [
      { value: "popular", label: "Most rated" },
      { value: "rating", label: "Highest rated" },
      { value: "year", label: "Newest first" },
      { value: "title", label: "Title A to Z" },
    ],
    []
  );

  return (
    <AppShell>
      <div className="cinema-container pt-6 pb-10">
        <div
          className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-6 border-b"
          style={{ borderColor: "var(--color-rule)" }}
        >
          <div>
            <h1 style={{ fontSize: "var(--text-display)" }}>Catalogue</h1>
            <p className="text-sm mt-1" style={{ color: "var(--color-ink-muted)" }}>
              Explore {data?.total ?? "2,300"} films spanning Hollywood, Bollywood, and Tollywood.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <GlassSelect
              ariaLabel="Filter by industry"
              value={industry}
              options={industryOptions}
              onChange={(val) => {
                captureGridPositions();
                updateFilterParams({ industry: val, page: 1 });
              }}
            />

            <GlassSelect
              ariaLabel="Filter by genre"
              value={genre}
              options={genreOptions}
              onChange={(val) => {
                captureGridPositions();
                updateFilterParams({ genre: val, page: 1 });
              }}
            />

            <GlassSelect
              ariaLabel="Sort films"
              value={sort}
              options={sortOptions}
              onChange={(val) => {
                captureGridPositions();
                updateFilterParams({ sort: val, page: 1 });
              }}
            />
          </div>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-5 mt-8">
            {Array.from({ length: 12 }).map((_, i) => (
              <div key={i} className="skeleton-block aspect-[3/4.2] w-full" />
            ))}
          </div>
        ) : isError ? (
          <div className="py-16 text-center">
            <p style={{ color: "var(--color-danger)" }}>Unable to load catalogue right now.</p>
          </div>
        ) : data && data.items.length === 0 ? (
          <div className="py-16 text-center flex flex-col items-center gap-3">
            <p style={{ color: "var(--color-ink-muted)" }}>
              No films match that filter combination.
            </p>
            <button
              type="button"
              className="cinema-btn cinema-btn-secondary"
              onClick={() => {
                captureGridPositions();
                updateFilterParams({ industry: "", genre: "", sort: "popular", page: 1 });
              }}
            >
              Reset filters
            </button>
          </div>
        ) : (
          <>
            <div
              ref={gridRef}
              className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-5 mt-8"
            >
              {data?.items.map((m) => (
                <div
                  key={m.id}
                  data-card-movie-id={m.id}
                  ref={(el) => {
                    if (el) cardNodeMapRef.current.set(m.id, el);
                    else cardNodeMapRef.current.delete(m.id);
                  }}
                  className="flex flex-col gap-2 min-w-0"
                >
                  <HoverPosterCard
                    movie={m}
                    onPrefetch={() => prefetchMovie(m.id)}
                    onClick={(e) => {
                      const frame =
                        e.currentTarget.querySelector<HTMLElement>("[data-poster-frame]");
                      const rect = captureSourceRect(frame);
                      openMovie(m, frame, { preCapturedRect: rect });
                    }}
                    className="w-full flex flex-col gap-2"
                    overlay={
                      <>
                        <div className="carousel-card-scrim z-10" aria-hidden="true" />
                        <div className="absolute top-2 left-2 right-2 flex items-center justify-between pointer-events-none z-10">
                          <span className="carousel-card-chip capitalize">
                            {m.industry.slice(0, 5)}
                          </span>
                          <span
                            className="tabular-figure text-xs font-medium inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full"
                            style={{ backgroundColor: "var(--color-chip-bg)" }}
                          >
                            {(m.tmdb_rating ? m.tmdb_rating : m.rating_avg * 2).toFixed(1)}
                            <Star size={10} fill="currentColor" aria-hidden="true" />
                          </span>
                        </div>
                      </>
                    }
                  >
                    <div className="min-w-0 w-full">
                      <div
                        className="font-medium truncate group-hover:text-[var(--soft-amber)] transition-colors"
                        style={{ fontFamily: "var(--font-display)", fontSize: "1rem" }}
                      >
                        {m.title}
                      </div>
                      <div
                        className="flex items-center gap-2 text-xs"
                        style={{ color: "var(--color-ink-muted)" }}
                      >
                        {m.year && <span className="tabular-figure">{m.year}</span>}
                        <span className="truncate">{m.genres[0]}</span>
                      </div>
                    </div>
                  </HoverPosterCard>
                </div>
              ))}
            </div>

            {data && data.total_pages > 1 && (
              <div className="flex items-center justify-center gap-3 mt-10">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => {
                    captureGridPositions();
                    updateFilterParams({ page: Math.max(1, page - 1) });
                  }}
                  className="cinema-btn cinema-btn-secondary"
                >
                  Previous
                </button>
                <span
                  className="tabular-figure text-sm"
                  style={{ color: "var(--color-ink-muted)" }}
                >
                  Page {data.page} of {data.total_pages}
                </span>
                <button
                  type="button"
                  disabled={page >= data.total_pages}
                  onClick={() => {
                    captureGridPositions();
                    updateFilterParams({ page: Math.min(data.total_pages, page + 1) });
                  }}
                  className="cinema-btn cinema-btn-secondary"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
