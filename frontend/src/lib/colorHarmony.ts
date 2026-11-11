/**
 * OKLCH poster-to-amber-palette harmonization.
 * Ensures dynamic backdrop colors stay harmonious with palette.png and preserve WCAG AA text contrast.
 */

interface Oklch {
  l: number;
  c: number;
  h: number;
}

const AMBER_ANCHORS: Oklch[] = [
  hexToOklch("#7A2E0B"), // Deep Amber
  hexToOklch("#C35A1A"), // Burnt Sienna
  hexToOklch("#F28B2C"), // Sunset Orange
  hexToOklch("#FFB45C"), // Golden Hour
];

export const DEFAULT_AMBIENT_STOPS = {
  c1: "#7A2E0B",
  c2: "#C35A1A",
  c3: "#351407",
  glow: "rgba(242, 139, 44, 0.42)",
};

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

export function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16);
    const g = parseInt(clean[1] + clean[1], 16);
    const b = parseInt(clean[2] + clean[2], 16);
    return [r, g, b];
  }
  const num = parseInt(clean.slice(0, 6), 16);
  if (Number.isNaN(num)) return [195, 90, 26];
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function srgbToLinear(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function linearToSrgb(v: number): number {
  const cl = clamp(v, 0, 1);
  const out = cl <= 0.0031308 ? 12.92 * cl : 1.055 * Math.pow(cl, 1 / 2.4) - 0.055;
  return Math.round(clamp(out * 255, 0, 255));
}

export function hexToOklch(hex: string): Oklch {
  const [r8, g8, b8] = hexToRgb(hex);
  const r = srgbToLinear(r8);
  const g = srgbToLinear(g8);
  const b = srgbToLinear(b8);

  const l_ = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m_ = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s_ = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);

  const L = 0.2104542553 * l_ + 0.793617785 * m_ - 0.0040720468 * s_;
  const a = 1.9779984951 * l_ - 2.428592205 * m_ + 0.4505937099 * s_;
  const bv = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.808675766 * s_;

  const C = Math.hypot(a, bv);
  let H = (Math.atan2(bv, a) * 180) / Math.PI;
  if (H < 0) H += 360;
  return { l: L, c: C, h: H };
}

function oklchToHex(ok: Oklch): string {
  const rad = (ok.h * Math.PI) / 180;
  const a = ok.c * Math.cos(rad);
  const b = ok.c * Math.sin(rad);

  const l_ = ok.l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = ok.l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = ok.l - 0.0894841775 * a - 1.291485548 * b;

  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;

  const r = linearToSrgb(+4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s);
  const g = linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s);
  const bv = linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s);

  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${bv
    .toString(16)
    .padStart(2, "0")}`;
}

function blendOklch(a: Oklch, b: Oklch, weightA: number): Oklch {
  const wB = 1 - weightA;
  // Shortest angular arc interpolation
  let dh = b.h - a.h;
  if (dh > 180) dh -= 360;
  if (dh < -180) dh += 360;
  const h = (a.h + dh * wB + 360) % 360;
  return {
    l: a.l * weightA + b.l * wB,
    c: a.c * weightA + b.c * wB,
    h,
  };
}

function nearestAmberAnchor(ok: Oklch): Oklch {
  let best = AMBER_ANCHORS[1];
  let minD = Infinity;
  for (const anc of AMBER_ANCHORS) {
    const d = Math.abs(anc.l - ok.l) * 1.4 + Math.abs(anc.c - ok.c);
    if (d < minD) {
      minD = d;
      best = anc;
    }
  }
  return best;
}

export function harmonizePosterPalette(
  dominantHex?: string | null,
  accentHex?: string | null,
  shadowHex?: string | null
): { c1: string; c2: string; c3: string; glow: string } {
  if (!dominantHex) return DEFAULT_AMBIENT_STOPS;

  const dom = hexToOklch(dominantHex);
  const acc = hexToOklch(accentHex || "#FFB45C");
  const shd = hexToOklch(shadowHex || "#291207");

  const anchorDom = nearestAmberAnchor(dom);
  const blendedDom = blendOklch(dom, anchorDom, 0.64);
  const blendedAcc = blendOklch(acc, AMBER_ANCHORS[2], 0.58);
  const blendedShd = blendOklch(shd, AMBER_ANCHORS[0], 0.45);

  // Clamp lightness and chroma so ambient blooms never impair WCAG AA text contrast
  const c1 = oklchToHex({
    l: clamp(blendedDom.l, 0.24, 0.44),
    c: clamp(blendedDom.c, 0.04, 0.13),
    h: blendedDom.h,
  });
  const c2 = oklchToHex({
    l: clamp(blendedAcc.l, 0.28, 0.48),
    c: clamp(blendedAcc.c, 0.05, 0.14),
    h: blendedAcc.h,
  });
  const c3 = oklchToHex({
    l: clamp(blendedShd.l, 0.15, 0.26),
    c: clamp(blendedShd.c, 0.02, 0.08),
    h: blendedShd.h,
  });

  const [gr, gg, gb] = hexToRgb(
    oklchToHex({
      l: clamp(blendedAcc.l, 0.36, 0.56),
      c: clamp(blendedAcc.c, 0.08, 0.16),
      h: blendedAcc.h,
    })
  );

  return {
    c1,
    c2,
    c3,
    glow: `rgba(${gr}, ${gg}, ${gb}, 0.42)`,
  };
}

/**
 * Blend poster dominant/accent color with amber in OKLCH so primary Hero CTAs
 * feel native to the scene without turning illegible or loud.
 */
export function heroCtaGlassTokens(
  dominantHex?: string | null,
  accentHex?: string | null
): { bg: string; border: string; glow: string } {
  if (!dominantHex && !accentHex) {
    return {
      bg: "var(--glass-accent-bg-strong)",
      border: "var(--glass-accent-border)",
      glow: "var(--glass-accent-glow)",
    };
  }
  const posterColor = hexToOklch(accentHex || dominantHex || "#FFB45C");
  const topTone = blendOklch(posterColor, AMBER_ANCHORS[3], 0.48);
  const bottomTone = blendOklch(posterColor, AMBER_ANCHORS[2], 0.56);
  const rimTone = blendOklch(posterColor, AMBER_ANCHORS[3], 0.3);

  const [tr, tg, tb] = hexToRgb(
    oklchToHex({
      l: clamp(topTone.l, 0.58, 0.78),
      c: clamp(topTone.c, 0.08, 0.17),
      h: topTone.h,
    })
  );
  const [br, bg_, bb] = hexToRgb(
    oklchToHex({
      l: clamp(bottomTone.l, 0.46, 0.66),
      c: clamp(bottomTone.c, 0.08, 0.18),
      h: bottomTone.h,
    })
  );
  const [rr, rg, rb] = hexToRgb(
    oklchToHex({
      l: clamp(rimTone.l, 0.72, 0.88),
      c: clamp(rimTone.c, 0.06, 0.14),
      h: rimTone.h,
    })
  );

  return {
    bg: `linear-gradient(180deg, rgb(${tr} ${tg} ${tb} / 0.36), rgb(${br} ${bg_} ${bb} / 0.18))`,
    border: `rgb(${rr} ${rg} ${rb} / 0.4)`,
    glow: `0 8px 30px -8px rgb(${br} ${bg_} ${bb} / 0.48)`,
  };
}
