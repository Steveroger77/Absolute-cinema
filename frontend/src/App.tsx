import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import gsap from "gsap";
import { AmbientBackdrop } from "./components/AmbientBackdrop";
import { SplashScreen } from "./components/SplashScreen";
import { ToastProvider } from "./components/ToastProvider";
import { AmbientProvider } from "./context/AmbientContext";
import { AuthProvider } from "./context/AuthContext";
import { LenisProvider } from "./context/LenisProvider";
import { TransitionProvider } from "./context/TransitionContext";
import { prefersReducedMotion } from "./lib/tier";
import { HomePage } from "./pages/HomePage";

const MovieDetailPage = lazy(() =>
  import("./pages/MovieDetailPage").then((m) => ({ default: m.MovieDetailPage }))
);
const ExplorePage = lazy(() =>
  import("./pages/ExplorePage").then((m) => ({ default: m.ExplorePage }))
);
const LibraryPage = lazy(() =>
  import("./pages/LibraryPage").then((m) => ({ default: m.LibraryPage }))
);
const AuthPage = lazy(() => import("./pages/AuthPage").then((m) => ({ default: m.AuthPage })));
const OnboardingPage = lazy(() =>
  import("./pages/OnboardingPage").then((m) => ({ default: m.OnboardingPage }))
);
const ModelInfoPage = lazy(() =>
  import("./pages/ModelInfoPage").then((m) => ({ default: m.ModelInfoPage }))
);
const NotFoundPage = lazy(() =>
  import("./pages/NotFoundPage").then((m) => ({ default: m.NotFoundPage }))
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60_000,
      gcTime: 30 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function RouteFallback() {
  return (
    <div className="cinema-container py-12 flex flex-col gap-6">
      <div className="skeleton-block h-12 w-48" />
      <div className="skeleton-block h-80 w-full" />
    </div>
  );
}

export function App() {
  const [showSplash, setShowSplash] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    if (prefersReducedMotion()) return false;
    return sessionStorage.getItem("ac_splash_seen") !== "1";
  });
  const [appRevealed, setAppRevealed] = useState<boolean>(() => !showSplash);
  const appBloomRef = useRef<HTMLDivElement | null>(null);

  const handleRevealApp = useCallback(() => {
    setAppRevealed(true);
  }, []);

  const handleSplashDone = useCallback(() => {
    setAppRevealed(true);
    setShowSplash(false);
  }, []);

  useEffect(() => {
    if (!appRevealed || !appBloomRef.current) return;
    if (prefersReducedMotion() || sessionStorage.getItem("ac_bloom_done") === "1") {
      gsap.set(appBloomRef.current, { opacity: 1, scale: 1, clearProps: "transform" });
      return;
    }
    sessionStorage.setItem("ac_bloom_done", "1");
    const tween = gsap.fromTo(
      appBloomRef.current,
      { opacity: 0.01, scale: 0.965 },
      {
        opacity: 1,
        scale: 1,
        duration: 0.95,
        ease: "expo.out",
        clearProps: "transform",
      }
    );
    return () => {
      tween.kill();
    };
  }, [appRevealed]);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AmbientProvider>
            <ToastProvider>
              <LenisProvider>
                <TransitionProvider>
                  <AmbientBackdrop />
                  {showSplash && (
                    <SplashScreen onRevealApp={handleRevealApp} onComplete={handleSplashDone} />
                  )}
                  <div
                    ref={appBloomRef}
                    style={{ opacity: appRevealed ? 1 : 0, transformOrigin: "50% 25%" }}
                  >
                    <Suspense fallback={<RouteFallback />}>
                      <Routes>
                        <Route path="/" element={<HomePage />} />
                        <Route path="/movie/:id" element={<MovieDetailPage />} />
                        <Route path="/explore" element={<ExplorePage />} />
                        <Route path="/library" element={<LibraryPage />} />
                        <Route path="/auth" element={<AuthPage />} />
                        <Route path="/onboarding" element={<OnboardingPage />} />
                        <Route path="/model" element={<ModelInfoPage />} />
                        <Route path="*" element={<NotFoundPage />} />
                      </Routes>
                    </Suspense>
                  </div>
                </TransitionProvider>
              </LenisProvider>
            </ToastProvider>
          </AmbientProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
