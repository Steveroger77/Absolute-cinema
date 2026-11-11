export type Industry = "hollywood" | "bollywood" | "tollywood";
export type LuminanceFlag = "dark" | "mid" | "light";
export type CapabilityTier = "high" | "mid" | "low";

export interface User {
  id: number;
  email: string;
  username: string;
  role: "user" | "admin";
  avatar_url?: string | null;
  auth_provider?: string;
  preferred_genres: string[];
  preferred_industries: Industry[];
  onboarding_completed: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface MovieSummary {
  id: number;
  title: string;
  year: number | null;
  industry: Industry;
  language: string;
  poster_url: string | null;
  backdrop_url: string | null;
  runtime: number | null;
  tmdb_rating: number | null;
  genres: string[];
  dominant_color: string;
  accent_color: string;
  shadow_color: string;
  color_luminance: LuminanceFlag;
  rating_avg: number;
  rating_count: number;
}

export interface MovieDetail extends MovieSummary {
  imdb_id: string | null;
  tmdb_id: number | null;
  overview: string | null;
  release_date: string | null;
  director: string | null;
  cast: string | null;
  user_rating: number | null;
  in_watchlist: boolean;
}

export interface MoviePage {
  items: MovieSummary[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface GenreInfo {
  id: number;
  name: string;
  slug: string;
  movie_count: number;
}

export interface RecommendationReason {
  type: string;
  movie_id?: number | null;
  title?: string | null;
  user_rating?: number | null;
  weight?: number | null;
  label?: string | null;
}

export interface RecommendedMovie {
  movie: MovieSummary;
  score: number;
  source: string;
  reasons: RecommendationReason[];
}

export interface RecommendationsResponse {
  strategy: string;
  model_version: string;
  items: RecommendedMovie[];
}

export interface TasteProfileResponse {
  genre_order: string[];
  industry_order: string[];
  genre_scores: Record<string, number>;
  industry_scores: Record<string, number>;
}

export interface BecauseRatedRow {
  anchor: MovieSummary;
  user_rating: number;
  items: RecommendedMovie[];
}

export interface BecauseRatedResponse {
  model_version: string;
  genre_order: string[];
  industry_order: string[];
  rows: BecauseRatedRow[];
}

export interface ExplainMovieResponse {
  movie_id: number;
  reasons: RecommendationReason[];
}

export interface UserRatingItem {
  movie_id: number;
  rating: number;
  source: string;
  rated_at: string;
  movie: MovieSummary;
}

export interface WatchlistItem {
  movie_id: number;
  added_at: string;
  movie: MovieSummary;
}

export interface ModelInfo {
  loaded: boolean;
  version: string | null;
  sha256: string | null;
  metrics: Record<string, unknown>;
}
