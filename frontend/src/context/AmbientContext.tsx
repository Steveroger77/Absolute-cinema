import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { DEFAULT_AMBIENT_STOPS, harmonizePosterPalette } from "../lib/colorHarmony";
import type { MovieSummary } from "../types/cinema";

export interface AmbientPalette {
  c1: string;
  c2: string;
  c3: string;
  glow: string;
}

interface AmbientContextValue {
  palette: AmbientPalette;
  setFromMovie: (
    movie?: Pick<MovieSummary, "dominant_color" | "accent_color" | "shadow_color"> | null
  ) => void;
  resetDefault: () => void;
}

const AmbientContext = createContext<AmbientContextValue | undefined>(undefined);

export function AmbientProvider({ children }: { children: ReactNode }) {
  const [palette, setPalette] = useState<AmbientPalette>(DEFAULT_AMBIENT_STOPS);

  const setFromMovie = useCallback(
    (movie?: Pick<MovieSummary, "dominant_color" | "accent_color" | "shadow_color"> | null) => {
      if (!movie) {
        setPalette(DEFAULT_AMBIENT_STOPS);
        return;
      }
      const next = harmonizePosterPalette(
        movie.dominant_color,
        movie.accent_color,
        movie.shadow_color
      );
      setPalette(next);
    },
    []
  );

  const resetDefault = useCallback(() => {
    setPalette(DEFAULT_AMBIENT_STOPS);
  }, []);

  const value = useMemo(
    () => ({ palette, setFromMovie, resetDefault }),
    [palette, setFromMovie, resetDefault]
  );

  return <AmbientContext.Provider value={value}>{children}</AmbientContext.Provider>;
}

export function useAmbient(): AmbientContextValue {
  const ctx = useContext(AmbientContext);
  if (!ctx) throw new Error("useAmbient must be used inside AmbientProvider");
  return ctx;
}
