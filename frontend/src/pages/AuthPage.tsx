import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { GoogleSignInButton } from "../components/GoogleSignInButton";
import { LiquidGlassSurface } from "../components/LiquidGlassSurface";
import { useAuth } from "../context/AuthContext";

export function AuthPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const { login, register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        const u = await login(email.trim(), password);
        navigate(u.onboarding_completed ? "/" : "/onboarding");
      } else {
        await register(email.trim(), username.trim(), password);
        navigate("/onboarding");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="cinema-container py-10 flex justify-center">
        <LiquidGlassSurface radius={24} blur={16} className="w-full max-w-md p-6 sm:p-8">
          <div className="flex items-center gap-2 mb-6">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setError(null);
              }}
              aria-pressed={mode === "login"}
              className={`cinema-btn flex-1 ${mode === "login" ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setError(null);
              }}
              aria-pressed={mode === "register"}
              className={`cinema-btn flex-1 ${mode === "register" ? "cinema-btn-selected" : "cinema-btn-secondary"}`}
            >
              Create account
            </button>
          </div>

          <h1 style={{ fontSize: "var(--text-section)" }}>
            {mode === "login" ? "Welcome back" : "Join the screening"}
          </h1>
          <p className="text-sm mt-2 mb-6" style={{ color: "var(--color-ink-muted)" }}>
            {mode === "login"
              ? "Sign in to access your ratings, watchlist, and collaborative recommendations."
              : "Build your taste profile across Hollywood, Bollywood, and Tollywood."}
          </p>

          <GoogleSignInButton
            enableOneTap
            onSuccess={(completed) => navigate(completed ? "/" : "/onboarding")}
            onError={(msg) => setError(msg)}
          />

          <form onSubmit={handleSubmit} className="flex flex-col gap-4 mt-4" noValidate>
            <div>
              <label
                htmlFor="auth-email"
                className="block text-sm mb-1.5"
                style={{ color: "var(--color-ink-muted)" }}
              >
                Email address
              </label>
              <input
                id="auth-email"
                name="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="cinema-input"
              />
            </div>

            {mode === "register" && (
              <div>
                <label
                  htmlFor="auth-username"
                  className="block text-sm mb-1.5"
                  style={{ color: "var(--color-ink-muted)" }}
                >
                  Username
                </label>
                <input
                  id="auth-username"
                  name="username"
                  type="text"
                  required
                  minLength={3}
                  maxLength={40}
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="cinephile"
                  className="cinema-input"
                />
              </div>
            )}

            <div>
              <label
                htmlFor="auth-password"
                className="block text-sm mb-1.5"
                style={{ color: "var(--color-ink-muted)" }}
              >
                Password
              </label>
              <input
                id="auth-password"
                name="password"
                type="password"
                required
                minLength={8}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="At least 8 characters"
                className="cinema-input"
              />
            </div>

            <div style={{ minHeight: "1.4lh" }}>
              {error && (
                <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
                  {error}
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="cinema-btn cinema-btn-primary w-full"
            >
              {submitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </LiquidGlassSurface>
      </div>
    </AppShell>
  );
}
