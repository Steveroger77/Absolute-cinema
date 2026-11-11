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
import { useLocation } from "react-router-dom";
import Lenis from "lenis";
import gsap from "gsap";
import { prefersReducedMotion } from "../lib/tier";

interface LenisContextValue {
  pauseScroll: () => void;
  resumeScroll: () => void;
  resetScrollLock: () => void;
  scrollToTop: (immediate?: boolean) => void;
  getScrollY: () => number;
  scrollToY: (y: number, immediate?: boolean) => void;
  suppressNextReset: () => void;
}

const LenisContext = createContext<LenisContextValue | undefined>(undefined);

export function LenisProvider({ children }: { children: ReactNode }) {
  const lenisRef = useRef<Lenis | null>(null);
  const progressBarRef = useRef<HTMLDivElement | null>(null);
  const suppressResetRef = useRef(false);
  const scrollTimerRef = useRef<number | null>(null);
  const [pauseCount, setPauseCount] = useState(0);
  const { pathname } = useLocation();

  useEffect(() => {
    if (typeof window !== "undefined" && "scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
  }, []);

  const updateProgressBar = useCallback((scrollY?: number) => {
    const bar = progressBarRef.current;
    if (!bar) return;
    const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const y = scrollY ?? window.scrollY;
    const ratio =
      document.documentElement.scrollHeight <= window.innerHeight
        ? 0
        : Math.min(1, Math.max(0, y / maxScroll));
    bar.style.transform = `scaleX(${ratio.toFixed(4)})`;
    bar.style.opacity = ratio > 0.005 ? "1" : "0";
  }, []);

  const markFastScroll = useCallback((velocity: number) => {
    const win = window as unknown as { __acFastScroll?: boolean };
    if (Math.abs(velocity) > 3.2) {
      win.__acFastScroll = true;
    }
    if (scrollTimerRef.current !== null) {
      window.clearTimeout(scrollTimerRef.current);
    }
    scrollTimerRef.current = window.setTimeout(() => {
      win.__acFastScroll = false;
      scrollTimerRef.current = null;
    }, 110);
  }, []);

  useEffect(() => {
    if (prefersReducedMotion()) {
      const onNativeScroll = () => updateProgressBar(window.scrollY);
      window.addEventListener("scroll", onNativeScroll, { passive: true });
      updateProgressBar(window.scrollY);
      return () => window.removeEventListener("scroll", onNativeScroll);
    }

    const lenis = new Lenis({
      lerp: 0.09,
      smoothWheel: true,
      syncTouch: false,
      autoRaf: false,
    });
    lenisRef.current = lenis;

    lenis.on("scroll", ({ scroll, velocity }: { scroll: number; velocity: number }) => {
      updateProgressBar(scroll);
      markFastScroll(velocity);
    });

    const tick = (timeSeconds: number) => {
      lenis.raf(timeSeconds * 1000);
    };
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    updateProgressBar(0);

    return () => {
      if (scrollTimerRef.current !== null) window.clearTimeout(scrollTimerRef.current);
      gsap.ticker.remove(tick);
      lenis.destroy();
      lenisRef.current = null;
    };
  }, [markFastScroll, updateProgressBar]);

  useEffect(() => {
    const lenis = lenisRef.current;
    if (!lenis) return;
    if (pauseCount > 0) {
      lenis.stop();
    } else {
      lenis.start();
    }
  }, [pauseCount]);

  useEffect(() => {
    if (suppressResetRef.current) {
      suppressResetRef.current = false;
      return;
    }
    if (lenisRef.current) {
      lenisRef.current.scrollTo(0, { immediate: true });
    } else {
      window.scrollTo(0, 0);
    }
    updateProgressBar(0);
  }, [pathname, updateProgressBar]);

  const pauseScroll = useCallback(() => {
    lenisRef.current?.stop();
    setPauseCount((c) => c + 1);
  }, []);

  const resumeScroll = useCallback(() => {
    setPauseCount((c) => {
      const next = Math.max(0, c - 1);
      if (next === 0) lenisRef.current?.start();
      return next;
    });
  }, []);

  const resetScrollLock = useCallback(() => {
    setPauseCount(0);
    lenisRef.current?.start();
  }, []);

  const getScrollY = useCallback(
    () => (lenisRef.current ? lenisRef.current.scroll : window.scrollY),
    []
  );

  const scrollToY = useCallback(
    (y: number, immediate = true) => {
      if (lenisRef.current) {
        lenisRef.current.scrollTo(y, { immediate });
      }
      window.scrollTo({ top: y, behavior: immediate ? "auto" : "smooth" });
      updateProgressBar(y);
    },
    [updateProgressBar]
  );

  const scrollToTop = useCallback((immediate = false) => scrollToY(0, immediate), [scrollToY]);

  const suppressNextReset = useCallback(() => {
    suppressResetRef.current = true;
  }, []);

  const value = useMemo(
    () => ({
      pauseScroll,
      resumeScroll,
      resetScrollLock,
      scrollToTop,
      getScrollY,
      scrollToY,
      suppressNextReset,
    }),
    [
      pauseScroll,
      resumeScroll,
      resetScrollLock,
      scrollToTop,
      getScrollY,
      scrollToY,
      suppressNextReset,
    ]
  );

  return (
    <LenisContext.Provider value={value}>
      <div
        ref={progressBarRef}
        aria-hidden="true"
        className="scroll-progress-hairline"
        style={{ opacity: 0 }}
      />
      {children}
    </LenisContext.Provider>
  );
}

export function useLenisScroll(): LenisContextValue {
  const ctx = useContext(LenisContext);
  if (!ctx) throw new Error("useLenisScroll must be used inside LenisProvider");
  return ctx;
}
