import type {
  AuthResponse,
  BecauseRatedResponse,
  ExplainMovieResponse,
  GenreInfo,
  Industry,
  ModelInfo,
  MovieDetail,
  MoviePage,
  MovieSummary,
  RecommendationsResponse,
  TasteProfileResponse,
  User,
  UserRatingItem,
  WatchlistItem,
} from "../types/cinema";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "/api";

let accessToken: string | null = null;
let refreshPromise: Promise<AuthResponse | null> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function performSingleFlightRefresh(): Promise<AuthResponse | null> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          credentials: "include",
        });
        if (!res.ok) {
          setAccessToken(null);
          return null;
        }
        const data = (await res.json()) as AuthResponse;
        setAccessToken(data.access_token);
        return data;
      } catch {
        setAccessToken(null);
        return null;
      } finally {
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

async function attemptRefresh(): Promise<string | null> {
  const data = await performSingleFlightRefresh();
  return data ? data.access_token : null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function fetchWithColdStartRetry(
  url: string,
  init: RequestInit,
  method: string
): Promise<Response> {
  const isSafeRetry = method.toUpperCase() === "GET" || url.endsWith("/auth/session");
  const maxAttempts = isSafeRetry ? 4 : 2;
  let lastErr: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const res = await fetch(url, init);
      if (res.status >= 502 && res.status <= 504 && attempt < maxAttempts - 1) {
        await sleep(1200 * (attempt + 1));
        continue;
      }
      return res;
    } catch (err) {
      lastErr = err;
      if (attempt < maxAttempts - 1) {
        await sleep(1200 * (attempt + 1));
        continue;
      }
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("Unable to reach server");
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  retryOnAuth = true
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  const res = await fetchWithColdStartRetry(
    `${API_BASE}${path}`,
    {
      ...options,
      headers,
      credentials: "include",
    },
    options.method || "GET"
  );

  if (res.status === 401 && retryOnAuth && !path.startsWith("/auth/")) {
    const newToken = await attemptRefresh();
    if (newToken) {
      return apiFetch<T>(path, options, false);
    }
    window.dispatchEvent(new CustomEvent("ac:auth-expired"));
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const firstDetail =
      Array.isArray(body?.error?.details) && body.error.details[0]?.msg
        ? `: ${String(body.error.details[0].msg)}`
        : "";
    const errMsg = `${body?.error?.message || body?.detail || `Request failed (${res.status})`}${firstDetail}`;
    const errCode = body?.error?.code || `http_${res.status}`;
    throw new ApiError(res.status, errCode, errMsg);
  }
  if (body === null) {
    throw new ApiError(
      502,
      "invalid_api_response",
      "Backend returned non-JSON content. Check that VITE_API_BASE_URL points to the FastAPI API URL, not the static frontend URL."
    );
  }
  return body as T;
}

export const api = {
  posterFallbackUrl: (movieId: number) => `${API_BASE}/posters/${movieId}.svg`,

  register: (payload: { email: string; username: string; password: string }) =>
    apiFetch<AuthResponse>(
      "/auth/register",
      { method: "POST", body: JSON.stringify(payload) },
      false
    ),

  login: (payload: { email: string; password: string }) =>
    apiFetch<AuthResponse>("/auth/login", { method: "POST", body: JSON.stringify(payload) }, false),

  googleSignIn: (credential: string) =>
    apiFetch<AuthResponse>(
      "/auth/google",
      { method: "POST", body: JSON.stringify({ credential }) },
      false
    ),

  hasSession: () => apiFetch<{ has_session: boolean }>("/auth/session", {}, false),

  refresh: async (): Promise<AuthResponse> => {
    const data = await performSingleFlightRefresh();
    if (!data) {
      throw new ApiError(401, "refresh_failed", "Session expired");
    }
    return data;
  },

  logout: () => apiFetch<void>("/auth/logout", { method: "POST" }, false),

  me: () => apiFetch<User>("/auth/me"),

  saveOnboarding: (payload: { preferred_genres: string[]; preferred_industries: Industry[] }) =>
    apiFetch<User>("/auth/onboarding", { method: "PUT", body: JSON.stringify(payload) }),

  getMovies: (params: {
    page?: number;
    page_size?: number;
    genre?: string;
    industry?: string;
    sort?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params.page) qs.set("page", String(params.page));
    if (params.page_size) qs.set("page_size", String(params.page_size));
    if (params.genre) qs.set("genre", params.genre);
    if (params.industry) qs.set("industry", params.industry);
    if (params.sort) qs.set("sort", params.sort);
    return apiFetch<MoviePage>(`/movies?${qs.toString()}`);
  },

  getTrending: (industry?: string, limit = 16) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (industry) qs.set("industry", industry);
    return apiFetch<MovieSummary[]>(`/movies/trending?${qs.toString()}`);
  },

  searchMovies: (q: string, limit = 18) => {
    const qs = new URLSearchParams({ q, limit: String(limit) });
    return apiFetch<MovieSummary[]>(`/movies/search?${qs.toString()}`);
  },

  getMovieDetail: (movieId: number) => apiFetch<MovieDetail>(`/movies/${movieId}`),

  getGenres: () => apiFetch<GenreInfo[]>("/genres"),

  getMyRatings: () => apiFetch<UserRatingItem[]>("/ratings/me"),

  upsertRating: (movieId: number, rating: number) =>
    apiFetch<UserRatingItem>(`/ratings/${movieId}`, {
      method: "PUT",
      body: JSON.stringify({ rating }),
    }),

  deleteRating: (movieId: number) => apiFetch<void>(`/ratings/${movieId}`, { method: "DELETE" }),

  getWatchlist: () => apiFetch<WatchlistItem[]>("/watchlist/me"),

  addWatchlist: (movieId: number) =>
    apiFetch<WatchlistItem>(`/watchlist/${movieId}`, { method: "POST" }),

  removeWatchlist: (movieId: number) =>
    apiFetch<void>(`/watchlist/${movieId}`, { method: "DELETE" }),

  getRecommendationsMe: (params: { k?: number; genre?: string; industry?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.k) qs.set("k", String(params.k));
    if (params.genre) qs.set("genre", params.genre);
    if (params.industry) qs.set("industry", params.industry);
    return apiFetch<RecommendationsResponse>(`/recommendations/me?${qs.toString()}`);
  },

  getSimilarMovies: (movieId: number, k = 12) =>
    apiFetch<RecommendationsResponse>(`/recommendations/similar/${movieId}?k=${k}`),

  getGenreRecommendations: (genre: string, k = 18, industry?: string) => {
    const qs = new URLSearchParams({ k: String(k) });
    if (industry) qs.set("industry", industry);
    return apiFetch<RecommendationsResponse>(
      `/recommendations/genre/${encodeURIComponent(genre)}?${qs.toString()}`
    );
  },

  getIndustryRecommendations: (industry: string, k = 16) =>
    apiFetch<RecommendationsResponse>(
      `/recommendations/industry/${encodeURIComponent(industry)}?k=${k}`
    ),

  getSuperheroRecommendations: (k = 100, industry?: string) => {
    const qs = new URLSearchParams({ k: String(k) });
    if (industry) qs.set("industry", industry);
    return apiFetch<RecommendationsResponse>(`/recommendations/superheroes?${qs.toString()}`);
  },

  getTasteProfile: () => apiFetch<TasteProfileResponse>("/recommendations/profile"),

  getBecauseYouRated: (industry?: string, limitRows = 3, k = 16) => {
    const qs = new URLSearchParams({ limit_rows: String(limitRows), k: String(k) });
    if (industry) qs.set("industry", industry);
    return apiFetch<BecauseRatedResponse>(`/recommendations/because?${qs.toString()}`);
  },

  getMovieExplain: (movieId: number) =>
    apiFetch<ExplainMovieResponse>(`/recommendations/explain/${movieId}`),

  getModelInfo: () => apiFetch<ModelInfo>("/model/info"),
};
