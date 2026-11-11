import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type WheelEvent,
} from "react";
import { useLocation } from "react-router-dom";
import gsap from "gsap";
import { ChevronLeft, ChevronRight, Pause, Play, Star } from "lucide-react";
import { useAmbient } from "../context/AmbientContext";
import { useAuth } from "../context/AuthContext";
import { useMovieTransition } from "../context/TransitionContext";
import { usePosterHover } from "../hooks/usePosterHover";
import { harmonizePosterPalette } from "../lib/colorHarmony";
import { prefersReducedMotion } from "../lib/tier";
import type { MovieSummary } from "../types/cinema";
import { PosterImage } from "./PosterImage";

interface PosterCarouselProps {
  title: string;
  subtitle?: string;
  movies: MovieSummary[];
  syncGlobalAmbient?: boolean;
  priorityFirst?: boolean;
}

function wrapOffset(raw: number, total: number): number {
  if (total <= 0) return 0;
  let d = raw % total;
  if (d > total / 2) d -= total;
  if (d < -total / 2) d += total;
  return d;
}

function formatRuntime(minutes?: number | null): string | null {
  if (!minutes || minutes <= 0) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatIndustryLabel(industry: string): string {
  if (industry === "bollywood") return "HI";
  if (industry === "tollywood") return "TE";
  return "EN";
}

function cardTransformMetrics(d: number, baseCardWidth: number) {
  const absD = Math.abs(d);
  const sign = d >= 0 ? 1 : -1;

  let scale: number;
  if (absD <= 1) {
    scale = 1.28 - 0.42 * absD;
  } else if (absD <= 2) {
    scale = 0.86 - 0.16 * (absD - 1);
  } else {
    scale = Math.max(0.54, 0.7 - 0.12 * (absD - 2));
  }

  let offsetX: number;
  if (absD <= 1) {
    offsetX = d * baseCardWidth * 1.14;
  } else if (absD <= 2) {
    offsetX = sign * (baseCardWidth * 1.14 + (absD - 1) * baseCardWidth * 0.94);
  } else {
    offsetX = sign * (baseCardWidth * 2.08 + (absD - 2) * baseCardWidth * 0.82);
  }

  const offsetY = absD < 1 ? -10 * (1 - absD) : 0;

  let opacity: number;
  if (absD <= 1) {
    opacity = 1.0 - 0.4 * absD;
  } else if (absD <= 2) {
    opacity = 0.6 - 0.35 * (absD - 1);
  } else if (absD <= 3.15) {
    opacity = Math.max(0, 0.25 * (1 - (absD - 2) / 1.15));
  } else {
    opacity = 0;
  }

  const dimOpacity = absD < 1 ? 0.38 * absD : Math.min(0.62, 0.38 + 0.2 * (absD - 1));
  const zIndex = absD < 0.45 ? 30 : absD < 1.45 ? 20 : absD < 2.45 ? 10 : 1;

  return { scale, offsetX, offsetY, opacity, dimOpacity, zIndex };
}

interface CarouselCardItemProps {
  movie: MovieSummary;
  idx: number;
  isActive: boolean;
  priority: boolean;
  hoverDisabled: boolean;
  setOuterRef: (idx: number, el: HTMLButtonElement | null) => void;
  setDimRef: (idx: number, el: HTMLDivElement | null) => void;
  onHoverChange: (idx: number, entering: boolean) => void;
  onCardClick: (
    idx: number,
    movie: MovieSummary,
    frameEl: HTMLElement | null,
    preCapturedRect: { top: number; left: number; width: number; height: number } | null
  ) => void;
}

function CarouselCardItem({
  movie,
  idx,
  isActive,
  priority,
  hoverDisabled,
  setOuterRef,
  setDimRef,
  onHoverChange,
  onCardClick,
}: CarouselCardItemProps) {
  const { prefetchMovie, captureSourceRect } = useMovieTransition();
  const capturedRectRef = useRef<{
    top: number;
    left: number;
    width: number;
    height: number;
  } | null>(null);

  const { hoverLayerRef, mediaLayerRef, glowLayerRef, sheenLayerRef, hitProps } = usePosterHover({
    disabled: hoverDisabled,
    lift: 6,
    scale: 1.03,
    mediaScale: 1.06,
    maxParallax: 6,
    onEnterExtra: () => {
      onHoverChange(idx, true);
      prefetchMovie(movie.id);
    },
    onLeaveExtra: () => {
      onHoverChange(idx, false);
    },
  });

  const displayScore =
    movie.tmdb_rating && movie.tmdb_rating > 0
      ? movie.tmdb_rating.toFixed(1)
      : (movie.rating_avg * 2).toFixed(1);
  const runtimeTxt = formatRuntime(movie.runtime);

  return (
    <button
      type="button"
      ref={(el) => setOuterRef(idx, el)}
      role="option"
      aria-selected={isActive}
      tabIndex={isActive ? 0 : -1}
      data-active={isActive ? "true" : "false"}
      className="carousel-card poster-slot"
      {...hitProps}
      onPointerDown={() => {
        prefetchMovie(movie.id);
        capturedRectRef.current = captureSourceRect(hoverLayerRef.current);
      }}
      onClick={(e) => {
        const frameEl = hoverLayerRef.current ?? e.currentTarget;
        const preRect = capturedRectRef.current ?? captureSourceRect(frameEl);
        capturedRectRef.current = null;
        onCardClick(idx, movie, frameEl, preRect);
      }}
    >
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

      <div
        ref={hoverLayerRef}
        data-movie-poster-id={movie.id}
        data-poster-frame="true"
        className="poster-hover-layer"
      >
        <div ref={mediaLayerRef} className="poster-media-layer">
          <PosterImage movie={movie} priority={priority} />
        </div>

        <div ref={sheenLayerRef} aria-hidden="true" className="poster-sheen-layer" />

        <div ref={(el) => setDimRef(idx, el)} className="carousel-card-dim" aria-hidden="true" />

        <div className="carousel-card-scrim" aria-hidden="true" />

        <div className="absolute top-2.5 left-2.5 right-2.5 flex items-center justify-between gap-2 pointer-events-none z-10">
          <span className="carousel-card-chip font-medium">
            {formatIndustryLabel(movie.industry)}
          </span>
          <span
            className="tabular-figure flex items-center gap-1 font-light"
            style={{
              color: "var(--color-ink)",
              fontSize: isActive ? "1.35rem" : "1.05rem",
              textShadow: "0 2px 10px var(--color-shadow-deep)",
            }}
          >
            {displayScore}
            <Star size={12} fill="currentColor" aria-hidden="true" />
          </span>
        </div>

        <div className="absolute bottom-2.5 left-2.5 right-2.5 flex flex-col gap-1.5 pointer-events-none z-10">
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "1.06rem",
              fontWeight: 600,
              lineHeight: 1.14,
              color: "var(--color-ink)",
            }}
            className="line-clamp-2"
          >
            {movie.title}
          </span>

          <div className="flex flex-wrap items-center gap-1.5">
            {movie.year && <span className="carousel-card-chip tabular-figure">{movie.year}</span>}
            {runtimeTxt && <span className="carousel-card-chip tabular-figure">{runtimeTxt}</span>}
          </div>
        </div>
      </div>
    </button>
  );
}

export function PosterCarousel({
  title,
  subtitle,
  movies,
  syncGlobalAmbient = false,
  priorityFirst = false,
}: PosterCarouselProps) {
  const { openMovie, captureSourceRect } = useMovieTransition();
  const { setFromMovie } = useAmbient();
  const { user } = useAuth();
  const { pathname } = useLocation();

  const userKey = user?.id ?? "guest";
  const storageKey = `ac_carousel:${userKey}:${pathname}:${title}`;

  const readInitialIndex = () => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      const parsed = raw ? parseInt(raw, 10) : 0;
      return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
    } catch {
      return 0;
    }
  };

  const stageRef = useRef<HTMLDivElement | null>(null);
  const cardRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
  const dimRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const [activeIndex, setActiveIndex] = useState<number>(readInitialIndex);
  const [isMoving, setIsMoving] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isHoverOrFocus, setIsHoverOrFocus] = useState(false);
  const [isInView, setIsInView] = useState(false);
  const [tabHidden, setTabHidden] = useState(
    typeof document !== "undefined" ? document.hidden : false
  );
  const [baseCardWidth, setBaseCardWidth] = useState(190);

  const [glowSlot, setGlowSlot] = useState<"a" | "b">("a");
  const [glowColors, setGlowColors] = useState<{ a: string; b: string }>({
    a: "rgba(242, 139, 44, 0.42)",
    b: "rgba(242, 139, 44, 0.42)",
  });

  const floatPosRef = useRef(activeIndex);
  const targetFloatRef = useRef(activeIndex);
  const floatVelRef = useRef(0);
  const hoveredIdxRef = useRef<number | null>(null);
  const movingRef = useRef(false);

  const dragRef = useRef<{
    dragging: boolean;
    startX: number;
    startFloat: number;
    lastX: number;
    lastTime: number;
    velocity: number;
    moved: boolean;
  }>({
    dragging: false,
    startX: 0,
    startFloat: 0,
    lastX: 0,
    lastTime: 0,
    velocity: 0,
    moved: false,
  });

  const count = movies.length;
  const normalizedActive = count > 0 ? ((activeIndex % count) + count) % count : 0;
  const activeMovie = movies[normalizedActive];

  // Keep restored active index clamped when list length resolves
  useEffect(() => {
    if (count > 0) {
      const clamped = ((activeIndex % count) + count) % count;
      if (Math.abs(targetFloatRef.current - clamped) > count) {
        targetFloatRef.current = clamped;
        floatPosRef.current = clamped;
      }
      try {
        sessionStorage.setItem(storageKey, String(clamped));
      } catch {
        // Ignore storage error
      }
    }
  }, [activeIndex, count, storageKey]);

  const setOuterRef = useCallback((idx: number, el: HTMLButtonElement | null) => {
    if (el) cardRefs.current.set(idx, el);
    else cardRefs.current.delete(idx);
  }, []);

  const setDimRef = useCallback((idx: number, el: HTMLDivElement | null) => {
    if (el) dimRefs.current.set(idx, el);
    else dimRefs.current.delete(idx);
  }, []);

  // Outer card transform ONLY (never mutates hover lift/scale; zero transform conflict)
  const applyTransforms = useCallback(
    (floatIdx: number) => {
      if (count === 0) return;
      const hoverId = hoveredIdxRef.current;
      for (let i = 0; i < count; i++) {
        const el = cardRefs.current.get(i);
        if (!el) continue;
        const d = wrapOffset(i - floatIdx, count);
        if (Math.abs(d) > 3.5) {
          el.style.opacity = "0";
          el.style.visibility = "hidden";
          el.style.pointerEvents = "none";
          continue;
        }
        const m = cardTransformMetrics(d, baseCardWidth);
        el.style.transform = `translate3d(${m.offsetX.toFixed(1)}px, ${m.offsetY.toFixed(
          1
        )}px, 0) scale(${m.scale.toFixed(4)})`;
        el.style.opacity = m.opacity.toFixed(3);
        el.style.visibility = "visible";
        el.style.zIndex = hoverId === i ? "35" : String(m.zIndex);
        el.style.pointerEvents = m.opacity > 0.08 ? "auto" : "none";

        const dimEl = dimRefs.current.get(i);
        if (dimEl) {
          dimEl.style.opacity = hoverId === i ? "0" : m.dimOpacity.toFixed(3);
        }
      }
    },
    [baseCardWidth, count]
  );

  useEffect(() => {
    const updateWidth = () => {
      const vw = window.innerWidth;
      const clamped = Math.max(148, Math.min(204, vw * 0.145));
      setBaseCardWidth(clamped);
    };
    updateWidth();
    window.addEventListener("resize", updateWidth, { passive: true });
    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  useEffect(() => {
    if (count === 0) return;
    if (prefersReducedMotion()) {
      floatPosRef.current = targetFloatRef.current;
      applyTransforms(floatPosRef.current);
      return;
    }

    const stiffness = 115;
    const damping = 21.5;

    const tick = (_time: number, deltaMs: number) => {
      if (dragRef.current.dragging) {
        applyTransforms(floatPosRef.current);
        return;
      }
      const dt = Math.min(0.05, Math.max(0.001, deltaMs / 1000));
      const displacement = targetFloatRef.current - floatPosRef.current;
      const speed = Math.abs(floatVelRef.current);

      const nowMoving = speed > 0.45;
      if (nowMoving !== movingRef.current) {
        movingRef.current = nowMoving;
        setIsMoving(nowMoving);
      }

      if (Math.abs(displacement) < 0.0008 && speed < 0.002) {
        floatPosRef.current = targetFloatRef.current;
        floatVelRef.current = 0;
        if (movingRef.current) {
          movingRef.current = false;
          setIsMoving(false);
        }
        if (Math.abs(floatPosRef.current) > count) {
          const mod = ((floatPosRef.current % count) + count) % count;
          floatPosRef.current = mod;
          targetFloatRef.current = mod;
        }
        applyTransforms(floatPosRef.current);
        return;
      }

      const accel = stiffness * displacement - damping * floatVelRef.current;
      floatVelRef.current += accel * dt;
      floatPosRef.current += floatVelRef.current * dt;
      applyTransforms(floatPosRef.current);
    };

    gsap.ticker.add(tick);
    applyTransforms(floatPosRef.current);
    return () => {
      gsap.ticker.remove(tick);
    };
  }, [applyTransforms, count]);

  const prevMoviesSigRef = useRef<string | null>(null);
  const moviesSig = useMemo(() => movies.map((m) => m.id).join(","), [movies]);

  useEffect(() => {
    applyTransforms(floatPosRef.current);
  }, [applyTransforms, movies]);

  useLayoutEffect(() => {
    const prev = prevMoviesSigRef.current;
    prevMoviesSigRef.current = moviesSig;
    if (prev === null || prev === moviesSig) return;
    targetFloatRef.current = 0;
    floatPosRef.current = 0;
    floatVelRef.current = 0;
    setActiveIndex(0);
    applyTransforms(0);
    if (prefersReducedMotion()) return;
    const stage = stageRef.current;
    if (!stage) return;
    const layers = Array.from(stage.querySelectorAll<HTMLElement>(".poster-media-layer"));
    if (layers.length === 0) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        layers,
        { opacity: 0.42, scale: 0.95 },
        {
          opacity: 1,
          scale: 1,
          duration: 0.44,
          stagger: 0.025,
          ease: "expo.out",
          clearProps: "opacity,transform",
        }
      );
    }, stage);
    return () => ctx.revert();
  }, [applyTransforms, moviesSig]);

  useEffect(() => {
    if (!activeMovie) return;
    const harm = harmonizePosterPalette(
      activeMovie.dominant_color,
      activeMovie.accent_color,
      activeMovie.shadow_color
    );
    setGlowColors((prev) => {
      if (glowSlot === "a") {
        setGlowSlot("b");
        return { ...prev, b: harm.glow };
      }
      setGlowSlot("a");
      return { ...prev, a: harm.glow };
    });
    if (syncGlobalAmbient && isHoverOrFocus) {
      setFromMovie(activeMovie);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMovie?.id]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const obs = new IntersectionObserver(([entry]) => setIsInView(entry.isIntersecting), {
      threshold: 0.15,
    });
    obs.observe(stage);
    const onVis = () => setTabHidden(document.hidden);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      obs.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  const goTo = useCallback(
    (targetIdx: number) => {
      if (count === 0) return;
      const wrappedDelta = wrapOffset(targetIdx - floatPosRef.current, count);
      const destFloat = floatPosRef.current + wrappedDelta;
      const wrappedNorm = ((Math.round(targetIdx) % count) + count) % count;
      targetFloatRef.current = destFloat;
      setActiveIndex(wrappedNorm);
      if (prefersReducedMotion()) {
        floatPosRef.current = wrappedNorm;
        targetFloatRef.current = wrappedNorm;
        applyTransforms(wrappedNorm);
      }
    },
    [applyTransforms, count]
  );

  useEffect(() => {
    if (
      count <= 1 ||
      isPaused ||
      isHoverOrFocus ||
      !isInView ||
      tabHidden ||
      prefersReducedMotion()
    ) {
      return;
    }
    const timer = window.setInterval(() => {
      goTo(normalizedActive + 1);
    }, 3200);
    return () => window.clearInterval(timer);
  }, [count, goTo, isHoverOrFocus, isInView, isPaused, normalizedActive, tabHidden]);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || count <= 1) return;
    dragRef.current = {
      dragging: true,
      startX: e.clientX,
      startFloat: floatPosRef.current,
      lastX: e.clientX,
      lastTime: performance.now(),
      velocity: 0,
      moved: false,
    };
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const st = dragRef.current;
    if (!st.dragging) return;
    const dx = e.clientX - st.startX;
    if (Math.abs(dx) > 6 && !st.moved) {
      st.moved = true;
      setIsMoving(true);
    }
    const now = performance.now();
    const dt = Math.max(8, now - st.lastTime);
    st.velocity = (e.clientX - st.lastX) / dt;
    st.lastX = e.clientX;
    st.lastTime = now;

    const nextFloat = st.startFloat - dx / (baseCardWidth * 1.14);
    floatPosRef.current = nextFloat;
    targetFloatRef.current = nextFloat;
  };

  const finishDrag = () => {
    const st = dragRef.current;
    if (!st.dragging) return;
    st.dragging = false;
    if (st.moved) {
      const momentumSteps = Math.max(-2.6, Math.min(2.6, -st.velocity * 0.65));
      floatVelRef.current = -st.velocity * 2.4;
      const snapped = Math.round(floatPosRef.current + momentumSteps);
      goTo(snapped);
      window.setTimeout(() => {
        dragRef.current.moved = false;
      }, 0);
    }
  };

  const wheelLockRef = useRef(0);
  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY) || Math.abs(e.deltaX) < 18) return;
    const now = performance.now();
    if (now - wheelLockRef.current < 260) return;
    wheelLockRef.current = now;
    goTo(normalizedActive + (e.deltaX > 0 ? 1 : -1));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      goTo(normalizedActive + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      goTo(normalizedActive - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      goTo(0);
    } else if (e.key === "End") {
      e.preventDefault();
      goTo(count - 1);
    }
  };

  const handleHoverChange = useCallback((idx: number, entering: boolean) => {
    if (entering) {
      hoveredIdxRef.current = idx;
    } else if (hoveredIdxRef.current === idx) {
      hoveredIdxRef.current = null;
    }
  }, []);

  const handleCardClick = useCallback(
    (
      idx: number,
      movie: MovieSummary,
      frameEl: HTMLElement | null,
      preCapturedRect: { top: number; left: number; width: number; height: number } | null
    ) => {
      if (dragRef.current.moved) return;
      if (idx === normalizedActive) {
        const rect = preCapturedRect ?? captureSourceRect(frameEl);
        openMovie(movie, frameEl, { preCapturedRect: rect });
      } else {
        goTo(idx);
      }
    },
    [captureSourceRect, goTo, normalizedActive, openMovie]
  );

  const visibleRange = useMemo(() => {
    if (count <= 9) return movies.map((_, idx) => idx);
    const indices: number[] = [];
    for (let offset = -4; offset <= 4; offset++) {
      const idx = (((normalizedActive + offset) % count) + count) % count;
      if (!indices.includes(idx)) indices.push(idx);
    }
    return indices;
  }, [count, movies, normalizedActive]);

  if (count === 0) return null;

  return (
    <section
      className="py-6"
      aria-roledescription="carousel"
      aria-label={title}
      onMouseEnter={() => setIsHoverOrFocus(true)}
      onMouseLeave={() => setIsHoverOrFocus(false)}
      onFocusCapture={() => setIsHoverOrFocus(true)}
      onBlurCapture={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setIsHoverOrFocus(false);
        }
      }}
    >
      <div className="cinema-container flex items-end justify-between gap-4 mb-2">
        <div>
          <h2 style={{ fontSize: "var(--text-section)" }}>{title}</h2>
          {subtitle && (
            <p className="text-sm mt-1" style={{ color: "var(--color-ink-muted)" }}>
              {subtitle}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            className="cinema-btn cinema-btn-ghost"
            aria-label={isPaused ? `Resume ${title} carousel` : `Pause ${title} carousel`}
            onClick={() => setIsPaused((p) => !p)}
          >
            {isPaused ? (
              <Play size={16} aria-hidden="true" />
            ) : (
              <Pause size={16} aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="cinema-btn cinema-btn-secondary"
            aria-label={`Previous in ${title}`}
            onClick={() => goTo(normalizedActive - 1)}
          >
            <ChevronLeft size={18} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="cinema-btn cinema-btn-secondary"
            aria-label={`Next in ${title}`}
            onClick={() => goTo(normalizedActive + 1)}
          >
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="sr-only" aria-live="polite">
        {activeMovie ? `Focused film: ${activeMovie.title}` : ""}
      </div>

      <div
        ref={stageRef}
        role="listbox"
        aria-label={`${title} posters`}
        data-moving={isMoving ? "true" : "false"}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onWheel={onWheel}
        className="carousel-stage"
      >
        <div
          aria-hidden="true"
          className="carousel-glow-layer"
          style={{
            background: `radial-gradient(ellipse at center, ${glowColors.a} 0%, transparent 68%)`,
            opacity: glowSlot === "a" ? 0.92 : 0,
          }}
        />
        <div
          aria-hidden="true"
          className="carousel-glow-layer"
          style={{
            background: `radial-gradient(ellipse at center, ${glowColors.b} 0%, transparent 68%)`,
            opacity: glowSlot === "b" ? 0.92 : 0,
          }}
        />

        {visibleRange.map((idx) => {
          const movie = movies[idx];
          const isActive = idx === normalizedActive;
          return (
            <CarouselCardItem
              key={movie.id}
              movie={movie}
              idx={idx}
              isActive={isActive}
              priority={priorityFirst && isActive}
              hoverDisabled={isMoving}
              setOuterRef={setOuterRef}
              setDimRef={setDimRef}
              onHoverChange={handleHoverChange}
              onCardClick={handleCardClick}
            />
          );
        })}
      </div>
    </section>
  );
}
