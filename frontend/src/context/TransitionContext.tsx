import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import gsap from "gsap";
import { api } from "../lib/api";
import { prefersReducedMotion } from "../lib/tier";
import type { MovieSummary } from "../types/cinema";
import { useAmbient } from "./AmbientContext";
import { useLenisScroll } from "./LenisProvider";

type TransitionPhase = "idle" | "measuring" | "flying" | "landed";

interface RectBox {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface CinemaOriginState {
  key: string;
  path: string;
  label: string;
  scrollY: number;
  originType: "route" | "search";
}

interface CinemaNavLocationState {
  from?: CinemaOriginState;
  sourceMovieId?: number;
}

interface OpenMovieOptions {
  originType?: "route" | "search";
  originLabel?: string;
  preCapturedRect?: RectBox | null;
}

interface FlightState {
  id: number;
  direction: "forward" | "reverse";
  movie: Pick<MovieSummary, "id" | "title" | "poster_url" | "shadow_color">;
  fromRect: RectBox;
  token: number;
}

interface ScrollRecord {
  scrollY: number;
  path: string;
}

interface TransitionContextValue {
  openMovie: (movie: MovieSummary, sourceEl?: HTMLElement | null, opts?: OpenMovieOptions) => void;
  captureSourceRect: (el?: HTMLElement | null) => RectBox | null;
  prefetchMovie: (movieId: number) => void;
  registerDetailPoster: (movieId: number, targetEl: HTMLElement | null) => void;
  isPosterHidden: (movieId: number) => boolean;
  goBackFromMovie: (
    movie?: Pick<
      MovieSummary,
      "id" | "title" | "poster_url" | "shadow_color" | "industry" | "genres"
    > | null,
    detailPosterEl?: HTMLElement | null
  ) => void;
  getBackLabel: (movie?: Pick<MovieSummary, "industry" | "genres"> | null) => string;
}

const SCROLL_STORAGE_KEY = "ac_route_scroll_v1";
const IN_APP_FLAG_KEY = "ac_in_app_nav";
const DECODE_TIMEOUT_MS = 600;
const CARD_RADIUS_PX = 16;

const TransitionContext = createContext<TransitionContextValue | undefined>(undefined);

function isValidViewportRect(rect: DOMRect | RectBox | null | undefined): rect is RectBox {
  if (!rect) return false;
  const { top, left, width, height } = rect;
  if (![top, left, width, height].every(Number.isFinite)) return false;
  if (width <= 8 || height <= 8) return false;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  return top + height > 0 && top < vh && left + width > 0 && left < vw;
}

function measurePosterFrame(el?: HTMLElement | null): RectBox | null {
  if (!el || !el.isConnected) return null;
  const frame = el.matches("[data-poster-frame]")
    ? el
    : (el.querySelector<HTMLElement>("[data-poster-frame]") ??
      el.closest<HTMLElement>("[data-poster-frame]") ??
      el);
  const rect = frame.getBoundingClientRect();
  if (!isValidViewportRect(rect)) return null;
  return { top: rect.top, left: rect.left, width: rect.width, height: rect.height };
}

function deriveOriginLabel(pathname: string, originType?: "route" | "search"): string {
  if (originType === "search") return "Back to search results";
  if (pathname.startsWith("/explore")) return "Back to catalogue";
  if (pathname.startsWith("/library")) return "Back to my vault";
  if (pathname.startsWith("/onboarding")) return "Back to preferences";
  if (pathname.startsWith("/movie/")) return "Back to previous film";
  if (pathname === "/") return "Back to home";
  return "Back";
}

function loadSavedScrollMap(): Record<string, ScrollRecord> {
  try {
    const raw = sessionStorage.getItem(SCROLL_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, ScrollRecord>) : {};
  } catch {
    return {};
  }
}

function persistSavedScrollMap(map: Record<string, ScrollRecord>): void {
  try {
    const keys = Object.keys(map);
    if (keys.length > 40) {
      delete map[keys[0]];
    }
    sessionStorage.setItem(SCROLL_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Storage quota ignored safely
  }
}

function fallbackDestination(movie?: Pick<MovieSummary, "industry" | "genres"> | null): {
  path: string;
  label: string;
} {
  if (movie?.industry) {
    const industry = movie.industry;
    const cap = industry[0].toUpperCase() + industry.slice(1);
    const qs = new URLSearchParams({ industry });
    if (movie.genres?.[0]) qs.set("genre", movie.genres[0]);
    return {
      path: `/explore?${qs.toString()}`,
      label: `Back to ${cap} catalogue`,
    };
  }
  return { path: "/explore", label: "Back to catalogue" };
}

function devWarnFallback(reason: string, extra?: unknown): void {
  if (import.meta.env.DEV) {
    console.debug(`[Transition] Fallback fade-rise: ${reason}`, extra ?? "");
  }
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

async function waitDetailImageAndFonts(targetEl: HTMLElement): Promise<boolean> {
  const fontsPromise = document.fonts?.ready ?? Promise.resolve();
  const imgEl = targetEl.querySelector("img");
  const decodePromise = imgEl
    ? imgEl.complete && imgEl.naturalWidth > 0
      ? imgEl.decode().catch(() => undefined)
      : new Promise<void>((res) => {
          const onDone = () => {
            imgEl.removeEventListener("load", onDone);
            imgEl.removeEventListener("error", onDone);
            imgEl
              .decode()
              .catch(() => undefined)
              .finally(() => res());
          };
          imgEl.addEventListener("load", onDone, { once: true });
          imgEl.addEventListener("error", onDone, { once: true });
        })
    : Promise.resolve();

  const timeoutPromise = new Promise<"timeout">((res) => {
    window.setTimeout(() => res("timeout"), DECODE_TIMEOUT_MS);
  });

  const winner = await Promise.race([
    Promise.all([fontsPromise, decodePromise]).then(() => "ready" as const),
    timeoutPromise,
  ]);
  return winner === "ready";
}

export function TransitionProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const navType = useNavigationType();
  const queryClient = useQueryClient();
  const { setFromMovie } = useAmbient();
  const { pauseScroll, resumeScroll, resetScrollLock, getScrollY, scrollToY, suppressNextReset } =
    useLenisScroll();

  const [flight, setFlight] = useState<FlightState | null>(null);
  const [hiddenMovieId, setHiddenMovieId] = useState<number | null>(null);

  const phaseRef = useRef<TransitionPhase>("idle");
  const flightRef = useRef<FlightState | null>(null);
  flightRef.current = flight;
  const activeTweenRef = useRef<gsap.core.Tween | gsap.core.Timeline | null>(null);
  const flightOverlayRef = useRef<HTMLDivElement | null>(null);
  const flightTokenRef = useRef(0);
  const scrollStoreRef = useRef<Record<string, ScrollRecord>>(loadSavedScrollMap());

  // Latest detail route state & poster box snapshot so browser Back works seamlessly
  const activeDetailSnapshotRef = useRef<{
    movie: Pick<MovieSummary, "id" | "title" | "poster_url" | "shadow_color">;
    el: HTMLElement | null;
    rect: RectBox | null;
  } | null>(null);
  const prevPathRef = useRef<string>(location.pathname + location.search);
  const prevKeyRef = useRef<string>(location.key);

  const canAnimate = useCallback(() => {
    if (prefersReducedMotion()) return false;
    return document.documentElement.dataset.tier !== "low";
  }, []);

  const stopAllFlight = useCallback(() => {
    activeTweenRef.current?.kill();
    activeTweenRef.current = null;
    if (flightOverlayRef.current) {
      gsap.killTweensOf(flightOverlayRef.current);
    }
    phaseRef.current = "idle";
    setFlight(null);
    setHiddenMovieId(null);
    resetScrollLock();
  }, [resetScrollLock]);

  useEffect(() => {
    const onSessionReset = () => {
      stopAllFlight();
      scrollStoreRef.current = {};
      activeDetailSnapshotRef.current = null;
    };
    window.addEventListener("ac:session-reset", onSessionReset);
    return () => {
      window.removeEventListener("ac:session-reset", onSessionReset);
      activeTweenRef.current?.kill();
    };
  }, [stopAllFlight]);

  const saveScrollForRoute = useCallback((key: string, path: string, scrollY: number) => {
    scrollStoreRef.current[key] = { scrollY, path };
    scrollStoreRef.current[`path:${path}`] = { scrollY, path };
    persistSavedScrollMap(scrollStoreRef.current);
  }, []);

  const readSavedScrollForRoute = useCallback((key: string, path: string): number | null => {
    const byKey = scrollStoreRef.current[key];
    if (byKey && byKey.path === path) return byKey.scrollY;
    const byPath = scrollStoreRef.current[`path:${path}`];
    if (byPath) return byPath.scrollY;
    return null;
  }, []);

  const prefetchMovie = useCallback(
    (movieId: number) => {
      void queryClient.prefetchQuery({
        queryKey: ["movie", movieId],
        queryFn: () => api.getMovieDetail(movieId),
        staleTime: 5 * 60_000,
      });
    },
    [queryClient]
  );

  const captureSourceRect = useCallback((el?: HTMLElement | null) => measurePosterFrame(el), []);

  const animateGhostBetween = useCallback(
    (fromRect: RectBox, toRect: RectBox, duration: number, onLanded: () => void) => {
      const overlay = flightOverlayRef.current;
      if (!overlay) {
        onLanded();
        return;
      }

      activeTweenRef.current?.kill();
      const dx = toRect.left - fromRect.left;
      const dy = toRect.top - fromRect.top;
      const sx = toRect.width / Math.max(1, fromRect.width);
      const sy = toRect.height / Math.max(1, fromRect.height);

      const proxy = { p: 0 };
      const tween = gsap.to(proxy, {
        p: 1,
        duration,
        ease: "power3.inOut",
        onUpdate: () => {
          const t = proxy.p;
          const curSx = 1 + (sx - 1) * t;
          const curSy = 1 + (sy - 1) * t;
          overlay.style.transform = `translate3d(${(dx * t).toFixed(2)}px, ${(dy * t).toFixed(2)}px, 0) scale(${curSx.toFixed(4)}, ${curSy.toFixed(4)})`;
          const rx = (CARD_RADIUS_PX / Math.max(0.15, curSx)).toFixed(2);
          const ry = (CARD_RADIUS_PX / Math.max(0.15, curSy)).toFixed(2);
          overlay.style.clipPath = `inset(0px round ${rx}px / ${ry}px)`;
        },
        onComplete: onLanded,
      });
      activeTweenRef.current = tween;
    },
    []
  );

  const openMovie = useCallback(
    (movie: MovieSummary, sourceEl?: HTMLElement | null, opts?: OpenMovieOptions) => {
      if (phaseRef.current === "measuring" || phaseRef.current === "flying") {
        return;
      }

      activeTweenRef.current?.kill();
      activeTweenRef.current = null;

      prefetchMovie(movie.id);
      setFromMovie(movie);

      const currentPath = location.pathname + location.search;
      const scrollY = getScrollY();
      saveScrollForRoute(location.key, currentPath, scrollY);

      try {
        sessionStorage.setItem(IN_APP_FLAG_KEY, "1");
      } catch {
        // Ignore storage restrictions
      }

      // Synchronously capture and validate source viewport box before any scroll lock or route transition
      const srcRect = opts?.preCapturedRect ?? measurePosterFrame(sourceEl);
      const originLabel =
        opts?.originLabel ?? deriveOriginLabel(location.pathname, opts?.originType);

      const navState: CinemaNavLocationState = {
        from: {
          key: location.key,
          path: currentPath,
          label: originLabel,
          scrollY,
          originType: opts?.originType ?? "route",
        },
        sourceMovieId: movie.id,
      };

      const token = ++flightTokenRef.current;

      if (!canAnimate() || !srcRect) {
        if (!srcRect) devWarnFallback("source rect missing or outside viewport", movie.title);
        else devWarnFallback("reduced motion or low tier active", movie.title);
        phaseRef.current = "idle";
        setFlight(null);
        setHiddenMovieId(null);
        navigate(`/movie/${movie.id}`, { state: navState });
        return;
      }

      pauseScroll();
      phaseRef.current = "measuring";
      setHiddenMovieId(movie.id);
      setFlight({
        id: movie.id,
        direction: "forward",
        movie: {
          id: movie.id,
          title: movie.title,
          poster_url: movie.poster_url,
          shadow_color: movie.shadow_color,
        },
        fromRect: srcRect,
        token,
      });

      navigate(`/movie/${movie.id}`, { state: navState });
    },
    [
      canAnimate,
      getScrollY,
      location.key,
      location.pathname,
      location.search,
      navigate,
      pauseScroll,
      prefetchMovie,
      saveScrollForRoute,
      setFromMovie,
    ]
  );

  const runFallbackPosterReveal = useCallback(
    (targetEl: HTMLElement | null, movieId: number) => {
      activeTweenRef.current?.kill();
      setFlight(null);
      setHiddenMovieId(null);
      phaseRef.current = "idle";
      resumeScroll();
      if (targetEl && !prefersReducedMotion()) {
        gsap.fromTo(
          targetEl,
          { opacity: 0, y: 12 },
          { opacity: 1, y: 0, duration: 0.34, ease: "power2.out", clearProps: "transform,opacity" }
        );
      } else if (targetEl) {
        targetEl.style.opacity = "1";
      }
      if (activeDetailSnapshotRef.current?.movie.id === movieId) {
        activeDetailSnapshotRef.current.rect = measurePosterFrame(targetEl);
      }
    },
    [resumeScroll]
  );

  const registerDetailPoster = useCallback(
    (movieId: number, targetEl: HTMLElement | null) => {
      if (!targetEl) return;

      // Record latest detail snapshot for browser Back / forward hardware buttons
      const curFlight = flightRef.current;
      activeDetailSnapshotRef.current = {
        movie:
          curFlight && curFlight.id === movieId
            ? curFlight.movie
            : { id: movieId, title: "", poster_url: null, shadow_color: "#291207" },
        el: targetEl,
        rect: measurePosterFrame(targetEl),
      };

      if (
        !curFlight ||
        curFlight.direction !== "forward" ||
        curFlight.id !== movieId ||
        phaseRef.current !== "measuring"
      ) {
        return;
      }

      const activeToken = curFlight.token;

      void (async () => {
        // Enforce top scroll immediately BEFORE measuring destination rect
        scrollToY(0, true);
        await nextFrame();
        if (flightTokenRef.current !== activeToken || !targetEl.isConnected) return;

        const readyInTime = await waitDetailImageAndFonts(targetEl);
        if (flightTokenRef.current !== activeToken || !targetEl.isConnected) return;

        if (!readyInTime) {
          devWarnFallback("detail image/font decode exceeded 600ms", movieId);
          runFallbackPosterReveal(targetEl, movieId);
          return;
        }

        // Wait committed layout + next frame stability check
        await nextFrame();
        if (flightTokenRef.current !== activeToken || !targetEl.isConnected) return;
        const r1 = measurePosterFrame(targetEl);

        await nextFrame();
        if (flightTokenRef.current !== activeToken || !targetEl.isConnected) return;
        const r2 = measurePosterFrame(targetEl);

        const settled =
          r1 &&
          r2 &&
          Math.abs(r1.top - r2.top) < 2 &&
          Math.abs(r1.left - r2.left) < 2 &&
          Math.abs(r1.width - r2.width) < 2;

        if (!r2 || !settled) {
          devWarnFallback("detail target rect unmeasurable or unstable", { r1, r2 });
          runFallbackPosterReveal(targetEl, movieId);
          return;
        }

        phaseRef.current = "flying";
        animateGhostBetween(curFlight.fromRect, r2, 0.78, () => {
          if (flightTokenRef.current !== activeToken) return;
          phaseRef.current = "landed";
          // Swap ghost & real poster cleanly in the same frame
          setHiddenMovieId(null);
          setFlight(null);
          activeDetailSnapshotRef.current = {
            ...activeDetailSnapshotRef.current!,
            el: targetEl,
            rect: r2,
          };
          phaseRef.current = "idle";
          resumeScroll();
        });
      })();
    },
    [animateGhostBetween, resumeScroll, runFallbackPosterReveal, scrollToY]
  );

  // Sync detail snapshot rect if user scrolls down on a detail page before hitting Browser Back
  useEffect(() => {
    if (!location.pathname.startsWith("/movie/")) return;
    const syncRect = () => {
      const snap = activeDetailSnapshotRef.current;
      if (snap && snap.el && snap.el.isConnected) {
        snap.rect = measurePosterFrame(snap.el);
      }
    };
    window.addEventListener("scroll", syncRect, { passive: true });
    window.addEventListener("resize", syncRect, { passive: true });
    return () => {
      window.removeEventListener("scroll", syncRect);
      window.removeEventListener("resize", syncRect);
    };
  }, [location.pathname]);

  const hasInAppHistory = useCallback(() => {
    const state = location.state as CinemaNavLocationState | null;
    if (state?.from) return true;
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    try {
      return idx > 0 && sessionStorage.getItem(IN_APP_FLAG_KEY) === "1";
    } catch {
      return false;
    }
  }, [location.state]);

  const getBackLabel = useCallback(
    (movie?: Pick<MovieSummary, "industry" | "genres"> | null) => {
      const state = location.state as CinemaNavLocationState | null;
      if (state?.from?.label) return state.from.label;
      if (hasInAppHistory()) return "Back";
      return fallbackDestination(movie).label;
    },
    [hasInAppHistory, location.state]
  );

  const launchReverseFlight = useCallback(
    (
      movie: Pick<MovieSummary, "id" | "title" | "poster_url" | "shadow_color">,
      fromRect: RectBox | null
    ): FlightState | null => {
      if (!canAnimate() || !fromRect) {
        if (!fromRect) devWarnFallback("reverse source detail rect missing", movie.id);
        return null;
      }
      const token = ++flightTokenRef.current;
      pauseScroll();
      phaseRef.current = "measuring";
      const nextFlight: FlightState = {
        id: movie.id,
        direction: "reverse",
        movie,
        fromRect,
        token,
      };
      flightRef.current = nextFlight;
      setFlight(nextFlight);
      return nextFlight;
    },
    [canAnimate, pauseScroll]
  );

  // Record live scroll position per history key continuously so normal link navigation also restores scroll on Back/Forward
  useEffect(() => {
    const key = location.key;
    const path = location.pathname + location.search;
    let rafId = 0;
    const record = () => {
      if (rafId) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = 0;
        saveScrollForRoute(key, path, getScrollY());
      });
    };
    window.addEventListener("scroll", record, { passive: true });
    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      window.removeEventListener("scroll", record);
    };
  }, [getScrollY, location.key, location.pathname, location.search, saveScrollForRoute]);

  const goBackFromMovie = useCallback(
    (
      movie?: Pick<
        MovieSummary,
        "id" | "title" | "poster_url" | "shadow_color" | "industry" | "genres"
      > | null,
      detailPosterEl?: HTMLElement | null
    ) => {
      if (phaseRef.current === "flying" || phaseRef.current === "measuring") return;

      const snapRect = measurePosterFrame(detailPosterEl ?? activeDetailSnapshotRef.current?.el);
      if (movie && snapRect) {
        launchReverseFlight(movie, snapRect);
      }

      if (hasInAppHistory()) {
        suppressNextReset();
        navigate(-1);
      } else {
        const fb = fallbackDestination(movie);
        navigate(fb.path);
      }
    },
    [hasInAppHistory, launchReverseFlight, navigate, suppressNextReset]
  );

  // Restore scroll cleanly + trigger reverse FLIP landing when returning via navigate(-1) OR browser Back/Forward
  useEffect(() => {
    const prevPath = prevPathRef.current;
    const prevKey = prevKeyRef.current;
    const curFull = location.pathname + location.search;
    prevPathRef.current = curFull;
    prevKeyRef.current = location.key;

    if (prevPath === curFull && prevKey === location.key) return;

    // Case 1: Hardware Browser Back (`POP`) leaving a detail page before goBackFromMovie ran
    let reverseFlight = flightRef.current;
    if (navType === "POP" && prevPath.startsWith("/movie/") && phaseRef.current === "idle") {
      const snap = activeDetailSnapshotRef.current;
      if (snap && snap.rect && canAnimate()) {
        const cached = queryClient.getQueryData<MovieSummary>(["movie", snap.movie.id]);
        const hydrated = cached
          ? {
              id: cached.id,
              title: cached.title,
              poster_url: cached.poster_url,
              shadow_color: cached.shadow_color,
            }
          : snap.movie;
        if (hydrated.poster_url || hydrated.id) {
          reverseFlight = launchReverseFlight(hydrated, snap.rect);
        }
      }
    }

    // Case 2: Any POP transition restores saved Lenis scrollY cleanly
    if (navType === "POP" || phaseRef.current === "measuring") {
      const savedY = readSavedScrollForRoute(location.key, curFull);
      if (savedY !== null && !curFull.startsWith("/movie/")) {
        suppressNextReset();
      }

      const curFlight = reverseFlight;
      if (savedY !== null && !curFull.startsWith("/movie/")) {
        window.requestAnimationFrame(() => {
          scrollToY(savedY, true);
        });
      }

      if (curFlight && curFlight.direction === "reverse") {
        const activeToken = curFlight.token;
        void (async () => {
          await nextFrame();
          if (savedY !== null && !curFull.startsWith("/movie/")) {
            scrollToY(savedY, true);
          }
          await nextFrame();
          if (flightTokenRef.current !== activeToken) return;

          const candidates = document.querySelectorAll<HTMLElement>(
            `[data-movie-poster-id="${curFlight.id}"]`
          );
          let bestEl: HTMLElement | null = null;
          let bestRect: RectBox | null = null;
          candidates.forEach((cand) => {
            const r = measurePosterFrame(cand);
            if (r && !bestRect) {
              bestEl = cand;
              bestRect = r;
            }
          });

          if (bestEl && bestRect) {
            const targetEl = bestEl as HTMLElement;
            const prevVis = targetEl.style.visibility;
            targetEl.style.visibility = "hidden";
            phaseRef.current = "flying";
            animateGhostBetween(curFlight.fromRect, bestRect, 0.64, () => {
              targetEl.style.visibility = prevVis;
              if (flightTokenRef.current !== activeToken) return;
              setFlight(null);
              phaseRef.current = "idle";
              resumeScroll();
            });
          } else {
            devWarnFallback("reverse target card off-screen or unmounted", curFlight.id);
            const overlay = flightOverlayRef.current;
            if (overlay) {
              activeTweenRef.current = gsap.to(overlay, {
                opacity: 0,
                scale: 0.92,
                y: 14,
                duration: 0.28,
                ease: "power2.out",
                onComplete: () => {
                  if (flightTokenRef.current !== activeToken) return;
                  setFlight(null);
                  phaseRef.current = "idle";
                  resumeScroll();
                },
              });
            } else {
              stopAllFlight();
            }
          }
        })();
      }
    }
  }, [
    animateGhostBetween,
    canAnimate,
    launchReverseFlight,
    location.key,
    location.pathname,
    location.search,
    navType,
    queryClient,
    readSavedScrollForRoute,
    resumeScroll,
    scrollToY,
    stopAllFlight,
    suppressNextReset,
  ]);

  // Universal safety watchdog: guarantee no frozen UI or orphan ghost ever remains
  useEffect(() => {
    if (!flight) return;
    const watchdog = window.setTimeout(() => {
      if (phaseRef.current === "measuring" || phaseRef.current === "flying") {
        devWarnFallback("watchdog cleaned up incomplete flight", flight.id);
        stopAllFlight();
      }
    }, 1700);
    return () => window.clearTimeout(watchdog);
  }, [flight, stopAllFlight]);

  const isPosterHidden = useCallback(
    (movieId: number) => hiddenMovieId === movieId,
    [hiddenMovieId]
  );

  const value = useMemo(
    () => ({
      openMovie,
      captureSourceRect,
      prefetchMovie,
      registerDetailPoster,
      isPosterHidden,
      goBackFromMovie,
      getBackLabel,
    }),
    [
      openMovie,
      captureSourceRect,
      prefetchMovie,
      registerDetailPoster,
      isPosterHidden,
      goBackFromMovie,
      getBackLabel,
    ]
  );

  const overlaySrc = flight
    ? flight.movie.poster_url || api.posterFallbackUrl(flight.movie.id)
    : "";

  return (
    <TransitionContext.Provider value={value}>
      {children}
      {flight && (
        <div
          ref={flightOverlayRef}
          aria-hidden="true"
          className="fixed pointer-events-none overflow-hidden"
          style={{
            zIndex: 520,
            top: `${flight.fromRect.top}px`,
            left: `${flight.fromRect.left}px`,
            width: `${flight.fromRect.width}px`,
            height: `${flight.fromRect.height}px`,
            clipPath: `inset(0px round ${CARD_RADIUS_PX}px)`,
            transformOrigin: "top left",
            willChange: "transform, clip-path",
            backfaceVisibility: "hidden",
            backgroundColor: flight.movie.shadow_color || "var(--color-paper-2)",
            boxShadow: "0 24px 56px var(--color-shadow-deep)",
          }}
        >
          <img
            src={overlaySrc}
            alt=""
            decoding="async"
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover"
          />
        </div>
      )}
    </TransitionContext.Provider>
  );
}

export function useMovieTransition(): TransitionContextValue {
  const ctx = useContext(TransitionContext);
  if (!ctx) throw new Error("useMovieTransition must be used inside TransitionProvider");
  return ctx;
}
