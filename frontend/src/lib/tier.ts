import type { CapabilityTier } from "../types/cinema";

export function detectCapabilityTier(): CapabilityTier {
  if (typeof window === "undefined") return "mid";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) {
    document.documentElement.dataset.tier = "low";
    return "low";
  }

  const cores = navigator.hardwareConcurrency ?? 4;
  const mem = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  const coarsePointer = window.matchMedia("(pointer: coarse)").matches;

  let tier: CapabilityTier = "high";
  if (cores <= 2 || mem <= 2) {
    tier = "low";
  } else if (coarsePointer || cores <= 4 || mem <= 4) {
    tier = "mid";
  }

  // Probe CSS backdrop-filter support
  const supportsBackdrop =
    typeof CSS !== "undefined" &&
    (CSS.supports("backdrop-filter", "blur(10px)") ||
      CSS.supports("-webkit-backdrop-filter", "blur(10px)"));
  if (!supportsBackdrop && tier === "high") {
    tier = "mid";
  }

  document.documentElement.dataset.tier = tier;
  return tier;
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
