import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidate all user-reactive rating & recommendation caches immediately
 * whenever a viewer rates, re-rates, deletes a rating, or updates preferences.
 */
export function invalidateRecommendationQueries(queryClient: QueryClient, movieId?: number): void {
  if (movieId !== undefined) {
    void queryClient.invalidateQueries({ queryKey: ["movie", movieId] });
    void queryClient.invalidateQueries({ queryKey: ["explain", movieId] });
  } else {
    void queryClient.invalidateQueries({ queryKey: ["explain"] });
  }
  void queryClient.invalidateQueries({ queryKey: ["my-ratings"] });
  void queryClient.invalidateQueries({ queryKey: ["recs"] });
  void queryClient.invalidateQueries({ queryKey: ["because"] });
  void queryClient.invalidateQueries({ queryKey: ["superheroes"] });
}
