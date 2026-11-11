import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useLocation, useNavigate } from "react-router-dom";
import gsap from "gsap";
import {
  Bookmark,
  ChevronDown,
  Compass,
  Cpu,
  Home,
  LogOut,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { prefersReducedMotion } from "../lib/tier";
import { LiquidGlassSurface } from "./LiquidGlassSurface";
import { SearchOverlay } from "./SearchOverlay";

interface AppShellProps {
  children: ReactNode;
  activeIndustry?: string;
  onSelectIndustry?: (industry: string | undefined) => void;
}

interface NavTabItem {
  id: string;
  label: string;
  to?: string;
  active: boolean;
  onClick?: () => void;
}

function SlidingNavTabs({ items, ariaLabel }: { items: NavTabItem[]; ariaLabel: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pillRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Map<string, HTMLElement>>(new Map());
  const firstRenderRef = useRef(true);

  const activeId = items.find((i) => i.active)?.id;

  useLayoutEffect(() => {
    const container = containerRef.current;
    const pill = pillRef.current;
    const target = activeId ? itemRefs.current.get(activeId) : undefined;
    if (!container || !pill || !target) {
      if (pill) pill.style.opacity = "0";
      return;
    }

    const x = target.offsetLeft;
    const width = target.offsetWidth;
    if (firstRenderRef.current || prefersReducedMotion()) {
      firstRenderRef.current = false;
      gsap.set(pill, { x, width, opacity: 1 });
    } else {
      gsap.to(pill, {
        x,
        width,
        opacity: 1,
        duration: 0.5,
        ease: "expo.out",
      });
    }
  }, [activeId, items.length]);

  return (
    <nav aria-label={ariaLabel} className="hidden lg:block">
      <div ref={containerRef} className="relative flex items-center gap-1">
        <div ref={pillRef} aria-hidden="true" className="nav-sliding-pill" style={{ opacity: 0 }} />
        {items.map((item) => {
          const baseClasses = `cinema-btn relative z-10 border-transparent ${
            item.active
              ? "text-[var(--soft-amber)]"
              : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
          }`;
          if (item.to) {
            return (
              <Link
                key={item.id}
                ref={(el) => {
                  if (el) itemRefs.current.set(item.id, el);
                  else itemRefs.current.delete(item.id);
                }}
                to={item.to}
                aria-current={item.active ? "page" : undefined}
                className={baseClasses}
                style={{ backgroundColor: "transparent", boxShadow: "none" }}
              >
                {item.label}
              </Link>
            );
          }
          return (
            <button
              key={item.id}
              ref={(el) => {
                if (el) itemRefs.current.set(item.id, el);
                else itemRefs.current.delete(item.id);
              }}
              type="button"
              onClick={item.onClick}
              aria-pressed={item.active}
              className={baseClasses}
              style={{ backgroundColor: "transparent", boxShadow: "none" }}
            >
              {item.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

export function AppShell({ children, activeIndustry, onSelectIndustry }: AppShellProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [menuHoverIdx, setMenuHoverIdx] = useState(-1);
  const [menuHighlightRect, setMenuHighlightRect] = useState<{ top: number; height: number }>({
    top: 0,
    height: 38,
  });
  const [menuAnchor, setMenuAnchor] = useState<{ top: number; right: number }>({
    top: 72,
    right: 24,
  });

  const profileTriggerRef = useRef<HTMLButtonElement | null>(null);
  const profilePanelRef = useRef<HTMLDivElement | null>(null);
  const profileItemRefs = useRef<Array<HTMLElement | null>>([]);

  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    setProfileMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!profileMenuOpen) return;
    const syncPos = () => {
      const r = profileTriggerRef.current?.getBoundingClientRect();
      if (!r) return;
      setMenuAnchor({
        top: r.bottom + 8,
        right: Math.max(12, window.innerWidth - r.right),
      });
    };
    syncPos();

    const onOutside = (e: MouseEvent) => {
      const t = e.target as Node;
      if (profilePanelRef.current?.contains(t) || profileTriggerRef.current?.contains(t)) return;
      setProfileMenuOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setProfileMenuOpen(false);
        profileTriggerRef.current?.focus();
      }
    };
    window.addEventListener("mousedown", onOutside);
    window.addEventListener("keydown", onEsc);
    window.addEventListener("resize", syncPos, { passive: true });
    return () => {
      window.removeEventListener("mousedown", onOutside);
      window.removeEventListener("keydown", onEsc);
      window.removeEventListener("resize", syncPos);
    };
  }, [profileMenuOpen]);

  useLayoutEffect(() => {
    if (!profileMenuOpen || !profilePanelRef.current || prefersReducedMotion()) return;
    const panel = profilePanelRef.current;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        panel,
        { opacity: 0, scale: 0.96, y: -6 },
        { opacity: 1, scale: 1, y: 0, duration: 0.26, ease: "power3.out" }
      );
      const items = profileItemRefs.current.filter((x): x is HTMLElement => Boolean(x));
      if (items.length) {
        gsap.fromTo(
          items,
          { opacity: 0, y: 5 },
          { opacity: 1, y: 0, duration: 0.2, stagger: 0.025, ease: "power2.out" }
        );
      }
    }, panel);
    return () => ctx.revert();
  }, [profileMenuOpen]);

  useLayoutEffect(() => {
    if (!profileMenuOpen || menuHoverIdx < 0) return;
    const row = profileItemRefs.current[menuHoverIdx];
    if (row) {
      setMenuHighlightRect({ top: row.offsetTop, height: row.offsetHeight });
    }
  }, [menuHoverIdx, profileMenuOpen]);

  const homeTabs: NavTabItem[] = [
    {
      id: "all",
      label: "All cinema",
      active: !activeIndustry,
      onClick: () => onSelectIndustry?.(undefined),
    },
    {
      id: "hollywood",
      label: "Hollywood",
      active: activeIndustry === "hollywood",
      onClick: () => onSelectIndustry?.("hollywood"),
    },
    {
      id: "bollywood",
      label: "Bollywood",
      active: activeIndustry === "bollywood",
      onClick: () => onSelectIndustry?.("bollywood"),
    },
    {
      id: "tollywood",
      label: "Tollywood",
      active: activeIndustry === "tollywood",
      onClick: () => onSelectIndustry?.("tollywood"),
    },
  ];

  const routeTabs: NavTabItem[] = [
    { id: "discover", label: "Discover", to: "/", active: pathname === "/" },
    { id: "catalogue", label: "Catalogue", to: "/explore", active: pathname === "/explore" },
    { id: "vault", label: "My Vault", to: "/library", active: pathname === "/library" },
  ];

  const isHomeWithFilter = pathname === "/" && Boolean(onSelectIndustry);
  const initialLetter = (user?.username?.[0] || "C").toUpperCase();

  return (
    <div className="relative min-h-dvh flex flex-col">
      {/* Top glass header */}
      <header className="sticky top-0 pt-3 pb-2" style={{ zIndex: "var(--z-sticky-nav)" }}>
        <div className="cinema-container">
          <LiquidGlassSurface
            enableRefraction
            glassZIndex={290}
            radius={22}
            blur={14}
            className="px-3 sm:px-5 py-2 flex items-center justify-between gap-3"
          >
            <div className="flex items-center gap-4 min-w-0">
              <Link
                to="/"
                aria-label="Absolute Cinema home"
                className="flex items-center gap-2.5 shrink-0 rounded-xl p-1"
              >
                <picture>
                  <source srcSet="/brand/logo-nav.avif" type="image/avif" />
                  <source srcSet="/brand/logo-nav.webp" type="image/webp" />
                  <img
                    src="/brand/logo-nav.png"
                    alt="Absolute Cinema"
                    width={36}
                    height={38}
                    className="h-9 w-auto block"
                  />
                </picture>
                <span
                  className="hidden sm:inline font-semibold tracking-tight"
                  style={{ fontFamily: "var(--font-display)", fontSize: "1.15rem" }}
                >
                  Absolute Cinema
                </span>
              </Link>

              {isHomeWithFilter ? (
                <SlidingNavTabs items={homeTabs} ariaLabel="Industry filter" />
              ) : (
                <SlidingNavTabs items={routeTabs} ariaLabel="Primary navigation" />
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => setSearchOpen(true)}
                aria-label="Open search"
                className="cinema-btn cinema-btn-secondary"
              >
                <Search size={16} aria-hidden="true" />
                <span className="hidden sm:inline">Search</span>
              </button>

              {isHomeWithFilter && (
                <Link to="/explore" className="hidden xl:inline-flex cinema-btn cinema-btn-ghost">
                  Catalogue
                </Link>
              )}

              {user ? (
                <>
                  <button
                    ref={profileTriggerRef}
                    type="button"
                    aria-haspopup="menu"
                    aria-expanded={profileMenuOpen}
                    onClick={() => {
                      setMenuHoverIdx(0);
                      setProfileMenuOpen((o) => !o);
                    }}
                    className="cinema-btn cinema-btn-secondary pl-2 pr-3 gap-2"
                  >
                    {user.avatar_url ? (
                      <img
                        src={user.avatar_url}
                        alt=""
                        referrerPolicy="no-referrer"
                        className="w-7 h-7 rounded-full object-cover border"
                        style={{ borderColor: "var(--glass-accent-border)" }}
                      />
                    ) : (
                      <span
                        aria-hidden="true"
                        className="w-7 h-7 rounded-full inline-flex items-center justify-center text-xs font-semibold"
                        style={{
                          background: "var(--glass-accent-bg)",
                          border: "1px solid var(--glass-accent-border)",
                          color: "var(--soft-amber)",
                        }}
                      >
                        {initialLetter}
                      </span>
                    )}
                    <span className="hidden sm:inline truncate max-w-[120px]">{user.username}</span>
                    <ChevronDown
                      size={15}
                      aria-hidden="true"
                      style={{
                        transform: profileMenuOpen ? "rotate(180deg)" : "rotate(0deg)",
                        transition: "transform 350ms var(--ease-cinema)",
                      }}
                    />
                  </button>

                  {profileMenuOpen &&
                    createPortal(
                      <div
                        ref={profilePanelRef}
                        role="menu"
                        aria-label="Account menu"
                        className="glass-select-panel fixed w-56"
                        style={{
                          zIndex: 550,
                          top: `${menuAnchor.top}px`,
                          right: `${menuAnchor.right}px`,
                          transformOrigin: "top right",
                        }}
                        onMouseLeave={() => setMenuHoverIdx(-1)}
                      >
                        <div
                          className="px-3 py-2 mb-1 border-b"
                          style={{ borderColor: "var(--color-rule)" }}
                        >
                          <div
                            className="text-xs font-medium truncate"
                            style={{ color: "var(--color-ink)" }}
                          >
                            {user.username}
                          </div>
                          <div
                            className="text-xs truncate"
                            style={{ color: "var(--color-ink-subtle)" }}
                          >
                            {user.email}
                          </div>
                        </div>

                        <div className="relative flex flex-col">
                          {menuHoverIdx >= 0 && (
                            <div
                              aria-hidden="true"
                              className="glass-select-highlight"
                              style={{
                                top: 0,
                                transform: `translate3d(0, ${menuHighlightRect.top}px, 0)`,
                                height: `${menuHighlightRect.height}px`,
                              }}
                            />
                          )}

                          <Link
                            ref={(el) => {
                              profileItemRefs.current[0] = el;
                            }}
                            role="menuitem"
                            to="/onboarding"
                            onMouseEnter={() => setMenuHoverIdx(0)}
                            onClick={() => setProfileMenuOpen(false)}
                            className="glass-select-option"
                            data-highlighted={menuHoverIdx === 0 ? "true" : "false"}
                          >
                            <span className="inline-flex items-center gap-2">
                              <SlidersHorizontal size={14} aria-hidden="true" />
                              Taste preferences
                            </span>
                          </Link>

                          <Link
                            ref={(el) => {
                              profileItemRefs.current[1] = el;
                            }}
                            role="menuitem"
                            to="/library"
                            onMouseEnter={() => setMenuHoverIdx(1)}
                            onClick={() => setProfileMenuOpen(false)}
                            className="glass-select-option"
                            data-highlighted={menuHoverIdx === 1 ? "true" : "false"}
                          >
                            <span className="inline-flex items-center gap-2">
                              <Bookmark size={14} aria-hidden="true" />
                              My Vault
                            </span>
                          </Link>

                          <Link
                            ref={(el) => {
                              profileItemRefs.current[2] = el;
                            }}
                            role="menuitem"
                            to="/model"
                            onMouseEnter={() => setMenuHoverIdx(2)}
                            onClick={() => setProfileMenuOpen(false)}
                            className="glass-select-option"
                            data-highlighted={menuHoverIdx === 2 ? "true" : "false"}
                          >
                            <span className="inline-flex items-center gap-2">
                              <Cpu size={14} aria-hidden="true" />
                              Engine & metrics
                            </span>
                          </Link>

                          <button
                            ref={(el) => {
                              profileItemRefs.current[3] = el;
                            }}
                            type="button"
                            role="menuitem"
                            onMouseEnter={() => setMenuHoverIdx(3)}
                            onClick={async () => {
                              setProfileMenuOpen(false);
                              await logout();
                              navigate("/");
                            }}
                            className="glass-select-option"
                            data-highlighted={menuHoverIdx === 3 ? "true" : "false"}
                          >
                            <span className="inline-flex items-center gap-2">
                              <LogOut size={14} aria-hidden="true" />
                              Sign out
                            </span>
                          </button>
                        </div>
                      </div>,
                      document.body
                    )}
                </>
              ) : (
                <Link to="/auth" className="cinema-btn cinema-btn-primary">
                  Sign in
                </Link>
              )}
            </div>
          </LiquidGlassSurface>
        </div>
      </header>

      {/* Main content stage targeted by shared-element transitions */}
      <main
        id="cinema-page-stage"
        className="relative flex-1 pb-24 md:pb-8"
        style={{ zIndex: "var(--z-base)" }}
      >
        {children}
      </main>

      {/* Minimal footer with logo lockup, quiet TMDB attribution, and key links */}
      <footer
        className="relative border-t py-7 mt-8"
        style={{ zIndex: "var(--z-base)", borderColor: "var(--color-rule)" }}
      >
        <div className="cinema-container flex flex-col sm:flex-row items-start sm:items-center justify-between gap-5">
          <div className="flex flex-col gap-1.5">
            <Link to="/" className="flex items-center gap-2.5 w-fit">
              <picture>
                <source srcSet="/brand/logo-nav.avif" type="image/avif" />
                <source srcSet="/brand/logo-nav.webp" type="image/webp" />
                <img
                  src="/brand/logo-nav.png"
                  alt="Absolute Cinema"
                  width={28}
                  height={30}
                  className="h-7 w-auto block"
                />
              </picture>
              <span style={{ fontFamily: "var(--font-display)", fontSize: "1.1rem" }}>
                Absolute Cinema
              </span>
            </Link>
            <p className="text-xs" style={{ color: "var(--color-ink-subtle)" }}>
              Film data and images courtesy of TMDB.
            </p>
          </div>

          <div
            className="flex flex-wrap items-center gap-5 text-sm"
            style={{ color: "var(--color-ink-muted)" }}
          >
            <Link to="/explore" className="hover:text-[var(--soft-amber)]">
              Browse catalogue
            </Link>
            <Link to="/library" className="hover:text-[var(--soft-amber)]">
              Ratings & watchlist
            </Link>
            <Link to="/model" className="hover:text-[var(--soft-amber)]">
              Model & metrics
            </Link>
          </div>
        </div>
      </footer>

      {/* Mobile bottom glass tab bar */}
      <nav
        aria-label="Mobile navigation"
        className="md:hidden fixed bottom-3 left-3 right-3 glass-surface rounded-2xl px-2 py-1.5 flex items-center justify-around"
        style={{
          zIndex: "var(--z-sticky-nav)",
          paddingBottom: "max(0.375rem, env(safe-area-inset-bottom))",
        }}
      >
        <Link to="/" className="cinema-btn cinema-btn-ghost flex-col gap-0.5 py-1 px-3 text-xs">
          <Home size={18} aria-hidden="true" />
          Home
        </Link>
        <Link
          to="/explore"
          className="cinema-btn cinema-btn-ghost flex-col gap-0.5 py-1 px-3 text-xs"
        >
          <Compass size={18} aria-hidden="true" />
          Explore
        </Link>
        <button
          type="button"
          onClick={() => setSearchOpen(true)}
          className="cinema-btn cinema-btn-ghost flex-col gap-0.5 py-1 px-3 text-xs"
        >
          <Search size={18} aria-hidden="true" />
          Search
        </button>
        <Link
          to={user ? "/library" : "/auth"}
          className="cinema-btn cinema-btn-ghost flex-col gap-0.5 py-1 px-3 text-xs"
        >
          <Bookmark size={18} aria-hidden="true" />
          {user ? "Vault" : "Sign in"}
        </Link>
      </nav>

      <SearchOverlay open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
