import type { CSSProperties, MouseEvent, ReactNode } from "react";
import { usePosterHover } from "../hooks/usePosterHover";
import type { MovieSummary } from "../types/cinema";
import { PosterImage } from "./PosterImage";

interface HoverPosterCardProps {
  movie: Pick<MovieSummary, "id" | "title" | "poster_url" | "shadow_color" | "accent_color">;
  priority?: boolean;
  disabledHover?: boolean;
  lift?: number;
  scale?: number;
  mediaScale?: number;
  maxParallax?: number;
  className?: string;
  style?: CSSProperties;
  ariaLabel?: string;
  onPrefetch?: () => void;
  onPointerDownCaptureRect?: (el: HTMLElement) => void;
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
  overlay?: ReactNode;
  children?: ReactNode;
}

/**
 * Reusable 4-layer GPU hover poster button:
 * - Outer button owns fixed layout slot & stable pointer listeners.
 * - Glow layer fades poster accent aura via opacity only.
 * - Hover layer owns lift/scale (marked [data-poster-frame] & [data-movie-poster-id]).
 * - Media layer owns poster zoom & quickTo pointer parallax.
 * - Sheen layer owns soft specular light sweep.
 */
export function HoverPosterCard({
  movie,
  priority = false,
  disabledHover = false,
  lift = 6,
  scale = 1.03,
  mediaScale = 1.06,
  maxParallax = 6,
  className = "",
  style,
  ariaLabel,
  onPrefetch,
  onPointerDownCaptureRect,
  onClick,
  overlay,
  children,
}: HoverPosterCardProps) {
  const { hoverLayerRef, mediaLayerRef, glowLayerRef, sheenLayerRef, hitProps } = usePosterHover({
    disabled: disabledHover,
    lift,
    scale,
    mediaScale,
    maxParallax,
    onEnterExtra: onPrefetch,
  });

  const accentGlowStyle: CSSProperties | undefined = movie.accent_color
    ? {
        background: `radial-gradient(ellipse at 50% 60%, ${movie.accent_color}52 0%, transparent 74%)`,
      }
    : undefined;

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      className={`poster-slot group cursor-pointer ${className}`.trim()}
      style={style}
      {...hitProps}
      onPointerDown={(e) => {
        onPrefetch?.();
        if (hoverLayerRef.current) onPointerDownCaptureRect?.(hoverLayerRef.current);
        else onPointerDownCaptureRect?.(e.currentTarget);
      }}
      onClick={onClick}
    >
      <div className="relative w-full" style={{ aspectRatio: "3 / 4.2" }}>
        <div
          ref={glowLayerRef}
          aria-hidden="true"
          className="poster-glow-layer"
          style={accentGlowStyle}
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
          {overlay}
        </div>
      </div>
      {children}
    </button>
  );
}
