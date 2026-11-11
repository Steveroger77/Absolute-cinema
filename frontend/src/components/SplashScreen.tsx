import { useCallback, useEffect, useRef } from "react";
import gsap from "gsap";
import { prefersReducedMotion } from "../lib/tier";

export const SPLASH = {
  entranceDur: 1.35,
  breathDur: 1.8,
  exitDur: 1.05,
  skipDur: 0.36,
  revealOffset: 2.35,
};

interface SplashScreenProps {
  onComplete: () => void;
  onRevealApp?: () => void;
}

export function SplashScreen({ onComplete, onRevealApp }: SplashScreenProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const sharpLogoRef = useRef<HTMLDivElement | null>(null);
  const softEchoRef = useRef<HTMLDivElement | null>(null);
  const sweepRef = useRef<HTMLDivElement | null>(null);
  const coreGlowRef = useRef<HTMLDivElement | null>(null);
  const skippingRef = useRef(false);
  const tlRef = useRef<gsap.core.Timeline | null>(null);

  const runGracefulSkip = useCallback(() => {
    if (skippingRef.current) return;
    skippingRef.current = true;
    sessionStorage.setItem("ac_splash_seen", "1");
    onRevealApp?.();
    tlRef.current?.kill();

    if (prefersReducedMotion() || !rootRef.current) {
      onComplete();
      return;
    }

    gsap.to(rootRef.current, {
      opacity: 0,
      scale: 1.03,
      duration: SPLASH.skipDur,
      ease: "power2.out",
      onComplete,
    });
  }, [onComplete, onRevealApp]);

  useEffect(() => {
    if (prefersReducedMotion()) {
      onRevealApp?.();
      onComplete();
      return;
    }

    const lowTier = document.documentElement.dataset.tier === "low";
    const ctx = gsap.context(() => {
      let revealTriggered = false;
      const fireReveal = () => {
        if (!revealTriggered) {
          revealTriggered = true;
          onRevealApp?.();
        }
      };

      const tl = gsap.timeline({
        onComplete: () => {
          sessionStorage.setItem("ac_splash_seen", "1");
          fireReveal();
          onComplete();
        },
      });
      tlRef.current = tl;

      // Phase A: Organic emergence from darkness (soft depth echo fades into crisp foreground lockup)
      tl.fromTo(
        sharpLogoRef.current,
        { opacity: 0, scale: 0.92 },
        { opacity: 1, scale: 1, duration: SPLASH.entranceDur, ease: "expo.out" },
        0
      )
        .fromTo(
          softEchoRef.current,
          { opacity: lowTier ? 0 : 0.72, scale: 0.89 },
          { opacity: 0, scale: 1.02, duration: SPLASH.entranceDur * 0.9, ease: "expo.out" },
          0
        )
        .fromTo(
          coreGlowRef.current,
          { opacity: 0, scale: 0.76 },
          { opacity: 0.72, scale: 1.04, duration: SPLASH.entranceDur * 0.85, ease: "power3.out" },
          0.18
        )
        .fromTo(
          sweepRef.current,
          { xPercent: -130, opacity: 0 },
          { xPercent: 145, opacity: 0.78, duration: 1.15, ease: "power2.inOut" },
          0.42
        )
        // Phase B: Overlapping organic breathing swell (starts around ~65% of entrance)
        .to(
          sharpLogoRef.current,
          {
            scale: 1.016,
            duration: SPLASH.breathDur * 0.5,
            ease: "sine.inOut",
            yoyo: true,
            repeat: 1,
          },
          0.95
        )
        .to(
          coreGlowRef.current,
          {
            opacity: 0.92,
            scale: 1.12,
            duration: SPLASH.breathDur * 0.5,
            ease: "sine.inOut",
            yoyo: true,
            repeat: 1,
          },
          0.95
        )
        // Phase C: Overlapping zoom-through forward drift while triggering app bloom underneath
        .add(() => fireReveal(), SPLASH.revealOffset)
        .to(
          sharpLogoRef.current,
          {
            scale: 14,
            opacity: 0,
            duration: SPLASH.exitDur,
            ease: "expo.inOut",
          },
          2.25
        )
        .to(
          softEchoRef.current,
          {
            scale: 15,
            opacity: lowTier ? 0 : 0.42,
            duration: SPLASH.exitDur * 0.72,
            ease: "power2.in",
          },
          2.28
        )
        .to(
          coreGlowRef.current,
          { scale: 3.8, opacity: 0, duration: SPLASH.exitDur * 0.88, ease: "power2.inOut" },
          2.3
        )
        .to(
          rootRef.current,
          { opacity: 0, duration: 0.65, ease: "power2.out" },
          SPLASH.revealOffset + 0.12
        );
    }, rootRef);

    const handleKey = (e: KeyboardEvent) => {
      if (["Escape", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        runGracefulSkip();
      }
    };

    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("keydown", handleKey);
      ctx.revert();
    };
  }, [onComplete, onRevealApp, runGracefulSkip]);

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-label="Absolute Cinema intro"
      onClick={runGracefulSkip}
      className="fixed inset-0 flex items-center justify-center overflow-hidden cursor-pointer"
      style={{
        zIndex: "var(--z-splash)",
        backgroundColor: "var(--rich-espresso)",
      }}
    >
      <div
        ref={coreGlowRef}
        aria-hidden="true"
        className="pointer-events-none absolute rounded-full"
        style={{
          width: "min(64vw, 500px)",
          height: "min(64vw, 500px)",
          background:
            "radial-gradient(circle, var(--burnt-sienna) 0%, var(--deep-amber) 45%, transparent 74%)",
          filter: "blur(58px)",
          opacity: 0,
          willChange: "transform, opacity",
        }}
      />

      {/* Pre-softened depth echo layer for buttery entrance/exit depth without per-frame filter animation */}
      <div
        ref={softEchoRef}
        aria-hidden="true"
        className="pointer-events-none absolute flex items-center justify-center"
        style={{
          width: "min(72vw, 340px)",
          filter: "blur(14px)",
          opacity: 0,
          willChange: "transform, opacity",
        }}
      >
        <img
          src="/brand/logo-splash.png"
          alt=""
          width={754}
          height={780}
          className="w-full h-auto block"
        />
      </div>

      <div
        ref={sharpLogoRef}
        className="relative flex flex-col items-center justify-center overflow-hidden"
        style={{ width: "min(72vw, 340px)", willChange: "transform, opacity" }}
      >
        <picture>
          <source srcSet="/brand/logo-splash.avif" type="image/avif" />
          <source srcSet="/brand/logo-splash.webp" type="image/webp" />
          <img
            src="/brand/logo-splash.png"
            alt="Absolute Cinema"
            width={754}
            height={780}
            className="w-full h-auto block select-none"
            decoding="sync"
            fetchPriority="high"
          />
        </picture>

        <div
          ref={sweepRef}
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 w-1/2"
          style={{
            background: "var(--glass-specular-sheen)",
            mixBlendMode: "screen",
          }}
        />
      </div>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          runGracefulSkip();
        }}
        className="cinema-btn cinema-btn-ghost absolute bottom-6 right-6 text-sm"
      >
        Skip intro
      </button>
    </div>
  );
}
