import { Link } from "react-router-dom";
import { AppShell } from "../components/AppShell";

export function NotFoundPage() {
  return (
    <AppShell>
      <div className="cinema-container py-24 text-center flex flex-col items-center gap-4">
        <h1 style={{ fontSize: "var(--text-display)" }}>Reel missing</h1>
        <p style={{ color: "var(--color-ink-muted)" }}>
          The page you requested is outside the projection booth.
        </p>
        <Link to="/" className="cinema-btn cinema-btn-primary">
          Back to Absolute Cinema
        </Link>
      </div>
    </AppShell>
  );
}
