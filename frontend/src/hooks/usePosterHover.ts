import { useCallback, useEffect, useRef, type PointerEvent } from "react";
import gsap from "gsap";
import { prefersReducedMotion } from "../lib/tier";

interface UsePosterHoverOptions {
  disabled?: boolean;
  lift?: number;
  scale?: number;
  mediaScale?: number;
  maxParallax?: number;
  onEnterExtra?: () => void;
  onLeaveExtra?: () => void;
}

interface CachedBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

function isFineDesktopHover(): boolean {
  if (typeof window === "undefined") return false;
  if (prefersReducedMotion()) return false;
  if (document.documentElement.dataset.tier === "low") return false;
  return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
}

function isInteractionSuppressed(): boolean {
  return Boolean((window as unknown as { __acFastScroll?: boolean }).__acFastScroll);
}

/**
 * Isolated 4-layer GPU poster hover controller:
 * - Hit target (outer slot) never transforms, eliminating edge-jitter loops.
 * - Hover lift & scale (hoverLayerRef), media zoom + quickTo parallax (mediaLayerRef),
 *   specular sheen (sheenLayerRef), and accent glow opacity (glowLayerRef) sit on separate nodes.
 * - Strictly animates transform & opacity; dynamically enables/clears will-change.
 */
export function usePosterHover({
  disabled = false,
  lift = 6,
  scale = 1.03,
  mediaScale = 1.06,
  maxParallax = 6,
  onEnterExtra,
  onLeaveExtra,
}: UsePosterHoverOptions = {}) {
  const hoverLayerRef = useRef<HTMLDivElement | null>(null);
  const mediaLayerRef = useRef<HTMLDivElement | null>(null);
  const glowLayerRef = useRef<HTMLDivElement | null>(null);
  const sheenLayerRef = useRef<HTMLDivElement | null>(null);

  const cachedBoxRef = useRef<CachedBox | null>(null);
  const activeHoverRef = useRef(false);
  const leaveTimerRef = useRef<number | null>(null);
  const quickXRef = useRef<gsap.QuickToFunc | null>(null);
  const quickYRef = useRef<gsap.QuickToFunc | null>(null);

  const resetImmediate = useCallback(() => {
    if (leaveTimerRef.current !== null) {
      window.clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
    activeHoverRef.current = false;
    cachedBoxRef.current = null;
    quickXRef.current = null;
    quickYRef.current = null;
    const targets = [
      hoverLayerRef.current,
      mediaLayerRef.current,
      glowLayerRef.current,
      sheenLayerRef.current,
    ].filter((n): n is HTMLDivElement => Boolean(n));
    if (targets.length) {
      gsap.killTweensOf(targets);
      gsap.set(targets, { clearProps: "willChange" });
    }
  }, []);

  useEffect(() => {
    if (disabled) {
      if (activeHoverRef.current && hoverLayerRef.current) {
        gsap.to(hoverLayerRef.current, { y: 0, scale: 1, duration: 0.45, ease: "expo.out" });
      }
      if (activeHoverRef.current && mediaLayerRef.current) {
        gsap.to(mediaLayerRef.current, { x: 0, y: 0, scale: 1, duration: 0.45, ease: "expo.out" });
      }
      if (activeHoverRef.current && glowLayerRef.current) {
        gsap.to(glowLayerRef.current, { opacity: 0, duration: 0.4, ease: "power2.out" });
      }
      activeHoverRef.current = false;
    }
  }, [disabled]);

  useEffect(() => resetImmediate, [resetImmediate]);

  const onPointerEnter = useCallback(
    (e: PointerEvent<HTMLElement>) => {
      if (
        disabled ||
        e.pointerType !== "mouse" ||
        !isFineDesktopHover() ||
        isInteractionSuppressed()
      ) {
        return;
      }
      if (leaveTimerRef.current !== null) {
        window.clearTimeout(leaveTimerRef.current);
        leaveTimerRef.current = null;
      }

      const rect = e.currentTarget.getBoundingClientRect();
      if (rect.width < 12 || rect.height < 12) return;
      cachedBoxRef.current = {
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      };
      activeHoverRef.current = true;
      onEnterExtra?.();

      const hEl = hoverLayerRef.current;
      const mEl = mediaLayerRef.current;
      const gEl = glowLayerRef.current;
      const sEl = sheenLayerRef.current;

      if (hEl) {
        hEl.style.willChange = "transform";
        gsap.to(hEl, {
          y: -lift,
          scale,
          duration: 0.45,
          ease: "expo.out",
          overwrite: "auto",
        });
      }
      if (mEl) {
        mEl.style.willChange = "transform";
        gsap.to(mEl, {
          scale: mediaScale,
          duration: 0.45,
          ease: "expo.out",
          overwrite: "auto",
        });
        quickXRef.current = gsap.quickTo(mEl, "x", { duration: 0.6, ease: "expo.out" });
        quickYRef.current = gsap.quickTo(mEl, "y", { duration: 0.6, ease: "expo.out" });
      }
      if (gEl) {
        gsap.to(gEl, {
          opacity: 0.9,
          duration: 0.42,
          ease: "power2.out",
          overwrite: "auto",
        });
      }
      if (sEl) {
        gsap.fromTo(
          sEl,
          { xPercent: -115, opacity: 0 },
          {
            xPercent: 120,
            opacity: 0.85,
            duration: 0.72,
            ease: "expo.out",
            overwrite: "auto",
            onComplete: () => {
              gsap.to(sEl, { opacity: 0, duration: 0.3, ease: "power2.out" });
            },
          }
        );
      }
    },
    [disabled, lift, mediaScale, onEnterExtra, scale]
  );

  const onPointerMove = useCallback(
    (e: PointerEvent<HTMLElement>) => {
      if (
        !activeHoverRef.current ||
        disabled ||
        e.pointerType !== "mouse" ||
        isInteractionSuppressed()
      ) {
        return;
      }
      const box = cachedBoxRef.current;
      if (!box) return;
      const nx = Math.max(-0.5, Math.min(0.5, (e.clientX - box.left) / box.width - 0.5));
      const ny = Math.max(-0.5, Math.min(0.5, (e.clientY - box.top) / box.height - 0.5));
      quickXRef.current?.(-nx * 2 * maxParallax);
      quickYRef.current?.(-ny * 2 * maxParallax);
    },
    [disabled, maxParallax]
  );

  const runLeave = useCallback(() => {
    activeHoverRef.current = false;
    cachedBoxRef.current = null;
    onLeaveExtra?.();

    const hEl = hoverLayerRef.current;
    const mEl = mediaLayerRef.current;
    const gEl = glowLayerRef.current;
    const sEl = sheenLayerRef.current;

    if (hEl) {
      gsap.to(hEl, {
        y: 0,
        scale: 1,
        duration: 0.6,
        ease: "expo.out",
        overwrite: "auto",
        onComplete: () => {
          if (!activeHoverRef.current && hEl) hEl.style.willChange = "auto";
        },
      });
    }
    if (mEl) {
      quickXRef.current = null;
      quickYRef.current = null;
      gsap.to(mEl, {
        x: 0,
        y: 0,
        scale: 1,
        duration: 0.6,
        ease: "expo.out",
        overwrite: "auto",
        onComplete: () => {
          if (!activeHoverRef.current && mEl) mEl.style.willChange = "auto";
        },
      });
    }
    if (gEl) {
      gsap.to(gEl, {
        opacity: 0,
        duration: 0.56,
        ease: "power2.out",
        overwrite: "auto",
      });
    }
    if (sEl) {
      gsap.to(sEl, {
        opacity: 0,
        duration: 0.35,
        ease: "power2.out",
        overwrite: "auto",
      });
    }
  }, [onLeaveExtra]);

  const onPointerLeave = useCallback(() => {
    if (leaveTimerRef.current !== null) {
      window.clearTimeout(leaveTimerRef.current);
    }
    leaveTimerRef.current = window.setTimeout(() => {
      leaveTimerRef.current = null;
      runLeave();
    }, 55);
  }, [runLeave]);

  const onPointerCancel = useCallback(() => {
    if (leaveTimerRef.current !== null) {
      window.clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = null;
    }
    runLeave();
  }, [runLeave]);

  return {
    hoverLayerRef,
    mediaLayerRef,
    glowLayerRef,
    sheenLayerRef,
    hitProps: {
      onPointerEnter,
      onPointerMove,
      onPointerLeave,
      onPointerCancel,
    },
  };
}
