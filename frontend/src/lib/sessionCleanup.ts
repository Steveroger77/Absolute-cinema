import type { QueryClient } from "@tanstack/react-query";

const EXACT_USER_STORAGE_KEYS = ["ac_route_scroll_v1", "ac_in_app_nav", "ac_onetap_dismissed"];

/**
 * Wipe all user-scoped React Query cache entries, transient navigation snapshots,
 * and carousel indices on login/logout so previous accounts never leak even for one frame.
 */
export function clearUserBrowserState(queryClient: QueryClient): void {
  void queryClient.cancelQueries();
  queryClient.clear();

  if (typeof window === "undefined") return;
  try {
    for (const k of EXACT_USER_STORAGE_KEYS) {
      sessionStorage.removeItem(k);
    }
    const removeKeys: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith("ac_carousel:")) {
        removeKeys.push(k);
      }
    }
    removeKeys.forEach((k) => sessionStorage.removeItem(k));

    const localRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("ac_")) {
        localRemove.push(k);
      }
    }
    localRemove.forEach((k) => localStorage.removeItem(k));
  } catch {
    // Ignore storage access errors in strict privacy modes
  }

  window.dispatchEvent(new CustomEvent("ac:session-reset"));
}
