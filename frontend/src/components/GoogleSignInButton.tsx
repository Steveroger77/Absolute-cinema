import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";

interface GoogleSignInButtonProps {
  onSuccess?: (onboardingCompleted: boolean) => void;
  onError?: (message: string) => void;
  enableOneTap?: boolean;
}

const GIS_SCRIPT_ID = "google-identity-services-script";
const GIS_SRC = "https://accounts.google.com/gsi/client";

export function GoogleSignInButton({
  onSuccess,
  onError,
  enableOneTap = false,
}: GoogleSignInButtonProps) {
  const clientId = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined)?.trim() || "";
  const { googleLogin } = useAuth();
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!clientId) {
      return;
    }

    const markReady = () => {
      if (window.google?.accounts?.id) {
        setReady(true);
      }
    };

    if (window.google?.accounts?.id) {
      setReady(true);
      return;
    }

    let script = document.getElementById(GIS_SCRIPT_ID) as HTMLScriptElement | null;
    if (!script) {
      script = document.createElement("script");
      script.id = GIS_SCRIPT_ID;
      script.src = GIS_SRC;
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }

    script.addEventListener("load", markReady);
    return () => {
      script?.removeEventListener("load", markReady);
    };
  }, [clientId]);

  useEffect(() => {
    if (!clientId || !ready || !window.google?.accounts?.id) return;

    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: async (response) => {
        if (!response.credential) {
          onError?.("Google did not return a credential.");
          return;
        }
        setBusy(true);
        try {
          const user = await googleLogin(response.credential);
          onSuccess?.(user.onboarding_completed);
        } catch (err) {
          onError?.(err instanceof Error ? err.message : "Google Sign-In failed");
        } finally {
          setBusy(false);
        }
      },
      cancel_on_tap_outside: true,
    });

    if (overlayRef.current && wrapperRef.current) {
      overlayRef.current.innerHTML = "";
      const width = Math.max(220, Math.min(400, Math.round(wrapperRef.current.clientWidth)));
      window.google.accounts.id.renderButton(overlayRef.current, {
        theme: "filled_black",
        size: "large",
        text: "continue_with",
        shape: "pill",
        width,
      });
    }

    if (enableOneTap && sessionStorage.getItem("ac_onetap_dismissed") !== "1") {
      window.google.accounts.id.prompt((notification) => {
        if (notification.isSkippedMoment?.() || notification.isNotDisplayed?.()) {
          sessionStorage.setItem("ac_onetap_dismissed", "1");
        }
      });
    }
  }, [clientId, enableOneTap, googleLogin, onError, onSuccess, ready]);

  if (!clientId) {
    return null;
  }

  return (
    <div ref={wrapperRef} className="relative w-full overflow-hidden rounded-full">
      <div
        aria-hidden="true"
        className="cinema-btn cinema-btn-secondary w-full pointer-events-none select-none"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <path
            fill="currentColor"
            d="M21.8 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.5c-.2 1.2-1 2.3-2.1 3v2.5h3.4c2-1.8 3-4.6 3-7.4Z"
          />
          <path
            fill="currentColor"
            d="M12 22c2.8 0 5.1-.9 6.8-2.5l-3.4-2.5c-.9.6-2.1 1-3.4 1-2.6 0-4.9-1.8-5.7-4.2H2.8v2.6C4.5 19.8 8 22 12 22Z"
          />
          <path
            fill="currentColor"
            d="M6.3 13.8c-.2-.6-.3-1.2-.3-1.8s.1-1.2.3-1.8V7.6H2.8C2.1 9 1.7 10.5 1.7 12s.4 3 1.1 4.4l3.5-2.6Z"
          />
          <path
            fill="currentColor"
            d="M12 5.9c1.5 0 2.9.5 4 1.6l3-3C17.1 2.8 14.8 2 12 2 8 2 4.5 4.2 2.8 7.6l3.5 2.6c.8-2.4 3.1-4.3 5.7-4.3Z"
          />
        </svg>
        <span>{busy ? "Signing in with Google…" : "Continue with Google"}</span>
      </div>

      {/* Real accessible GIS iframe trigger sits transparently aligned above themed glass surface */}
      <div
        ref={overlayRef}
        aria-label="Continue with Google"
        className="absolute inset-0 flex items-center justify-center overflow-hidden"
        style={{ opacity: 0.005 }}
      />
    </div>
  );
}
