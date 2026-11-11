import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { MovieSummary } from "../types/cinema";

interface PosterImageProps {
  movie: Pick<MovieSummary, "id" | "title" | "poster_url" | "shadow_color">;
  priority?: boolean;
  className?: string;
}

export function PosterImage({ movie, priority = false, className = "" }: PosterImageProps) {
  const fallback = api.posterFallbackUrl(movie.id);
  const [src, setSrc] = useState<string>(movie.poster_url || fallback);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setSrc(movie.poster_url || fallback);
    setLoaded(false);
  }, [movie.id, movie.poster_url, fallback]);

  return (
    <div
      className={`relative w-full h-full overflow-hidden ${className}`.trim()}
      style={{ backgroundColor: movie.shadow_color || "var(--color-paper-2)" }}
    >
      <img
        src={src}
        alt={`${movie.title} poster`}
        width={300}
        height={420}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        referrerPolicy="no-referrer"
        fetchPriority={priority ? "high" : "auto"}
        onLoad={() => setLoaded(true)}
        onError={() => {
          if (src !== fallback) {
            setSrc(fallback);
          } else {
            setLoaded(true);
          }
        }}
        className="w-full h-full object-cover transition-opacity duration-300"
        style={{ opacity: loaded ? 1 : 0.85 }}
      />
    </div>
  );
}
