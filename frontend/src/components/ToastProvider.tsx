import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface ToastItem {
  id: number;
  message: string;
  tone: "error" | "info";
}

interface ToastContextValue {
  notify: (message: string, tone?: "error" | "info") => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const notify = useCallback((message: string, tone: "error" | "info" = "info") => {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev.slice(-2), { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3600);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="fixed bottom-20 md:bottom-6 right-6 flex flex-col gap-2 pointer-events-none"
        style={{ zIndex: "var(--z-toast)" }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className="glass-surface toast-slide-in px-4 py-2.5 text-sm rounded-xl pointer-events-auto"
            style={{
              borderColor:
                t.tone === "error" ? "var(--color-danger)" : "var(--glass-accent-border)",
              color: "var(--color-ink)",
            }}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
