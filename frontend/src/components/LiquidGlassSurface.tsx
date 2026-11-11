import { useEffect, useRef, type HTMLAttributes, type ReactNode } from "react";
import LiquidGlass from "liquid-glass-js";
import { useAmbient } from "../context/AmbientContext";

interface LiquidGlassSurfaceProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  enableRefraction?: boolean;
  glassZIndex?: number;
  radius?: number;
  scale?: number;
  blur?: number;
}

/**
 * Tier-aware liquid-glass container.
 * On `high` tier (for sticky chrome), mounts liquid-glass-js refracting `#ambient-backdrop`
 * directly underneath the chrome's stacking layer (`glassZIndex`, default 290 < sticky-nav 300).
 * On `mid`/`low` tiers or inline surfaces, renders graceful CSS backdrop-filter glass.
 */
export function LiquidGlassSurface({
  children,
  className = "",
  enableRefraction = false,
  glassZIndex = 290,
  radius = 22,
  scale = 26,
  blur = 10,
  ...rest
}: LiquidGlassSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const glassRef = useRef<LiquidGlass | null>(null);
  const lastPosRef = useRef<{ x: number; y: number } | null>(null);
  const { palette } = useAmbient();

  useEffect(() => {
    if (!enableRefraction) return;
    const tier = document.documentElement.dataset.tier;
    if (tier !== "high") return;

    const el = containerRef.current;
    const backdrop = document.getElementById("ambient-backdrop");
    if (!el || !backdrop) return;

    let instance: LiquidGlass | null = null;
    const syncRect = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width < 20 || rect.height < 20) return;
      const nx = Math.round(rect.left);
      const ny = Math.round(rect.top);
      if (!instance) {
        instance = new LiquidGlass({
          background: backdrop,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          radius,
          scale,
          depth: 26,
          curvature: 3.2,
          convexity: 0.85,
          chroma: 0.06,
          blur,
          glow: 0.12,
          edge: 0.42,
          tint: 0.14,
          tintColor: "#1A0D06",
          draggable: false,
          zIndex: glassZIndex,
          x: nx,
          y: ny,
        });
        const internal = instance as unknown as {
          lensEl?: HTMLElement;
          glassEl?: HTMLElement;
        };
        if (internal.lensEl) internal.lensEl.style.pointerEvents = "none";
        if (internal.glassEl) internal.glassEl.style.pointerEvents = "none";
        glassRef.current = instance;
        lastPosRef.current = { x: nx, y: ny };
      } else {
        const cur = instance.get();
        if (Math.abs(cur.width - rect.width) > 2 || Math.abs(cur.height - rect.height) > 2) {
          instance.set({ width: Math.round(rect.width), height: Math.round(rect.height) });
        }
        if (
          !lastPosRef.current ||
          Math.abs(lastPosRef.current.x - nx) > 0.5 ||
          Math.abs(lastPosRef.current.y - ny) > 0.5
        ) {
          instance.moveTo(nx, ny);
          lastPosRef.current = { x: nx, y: ny };
        }
      }
    };

    syncRect();
    const ro = new ResizeObserver(syncRect);
    ro.observe(el);
    window.addEventListener("scroll", syncRect, { passive: true });
    window.addEventListener("resize", syncRect, { passive: true });

    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", syncRect);
      window.removeEventListener("resize", syncRect);
      instance?.destroy();
      glassRef.current = null;
      lastPosRef.current = null;
    };
  }, [enableRefraction, glassZIndex, radius, scale, blur]);

  useEffect(() => {
    if (glassRef.current) {
      glassRef.current.refresh();
    }
  }, [palette.c1, palette.c2, palette.c3]);

  return (
    <div
      ref={containerRef}
      className={`glass-surface ${className}`.trim()}
      style={{ borderRadius: `${radius}px` }}
      {...rest}
    >
      {children}
    </div>
  );
}
