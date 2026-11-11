import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import gsap from "gsap";
import { Check, ChevronDown } from "lucide-react";
import { useLenisScroll } from "../context/LenisProvider";
import { prefersReducedMotion } from "../lib/tier";

export interface GlassSelectOption {
  value: string;
  label: string;
  count?: number;
}

interface GlassSelectProps {
  value: string;
  options: GlassSelectOption[];
  onChange: (value: string) => void;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
}

export function GlassSelect({
  value,
  options,
  onChange,
  ariaLabel,
  placeholder = "Select…",
  className = "",
}: GlassSelectProps) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [highlightedIdx, setHighlightedIdx] = useState(0);
  const [anchorStyle, setAnchorStyle] = useState<{
    top: number;
    left: number;
    width: number;
    openUp: boolean;
    maxHeight: number;
  }>({ top: 0, left: 0, width: 200, openUp: false, maxHeight: 300 });
  const [highlightRect, setHighlightRect] = useState<{
    top: number;
    height: number;
    visible: boolean;
  }>({
    top: 0,
    height: 36,
    visible: false,
  });

  const listboxId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listWrapRef = useRef<HTMLDivElement | null>(null);
  const typeAheadRef = useRef<{ buffer: string; timer: number | null }>({
    buffer: "",
    timer: null,
  });
  const closeTimerRef = useRef<number | null>(null);
  const { pauseScroll, resumeScroll } = useLenisScroll();

  const selectedIndex = useMemo(
    () =>
      Math.max(
        0,
        options.findIndex((opt) => opt.value === value)
      ),
    [options, value]
  );
  const selectedOption = options.find((opt) => opt.value === value) ?? options[0];

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 639px)");
    const sync = () => setIsMobile(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  const updatePosition = useCallback(() => {
    const trig = triggerRef.current;
    if (!trig) return;
    const rect = trig.getBoundingClientRect();
    const gap = 8;
    const estPanelHeight = Math.min(320, options.length * 40 + 16);
    const spaceBelow = window.innerHeight - rect.bottom - gap - 12;
    const spaceAbove = rect.top - gap - 12;
    const openUp = spaceBelow < Math.min(220, estPanelHeight) && spaceAbove > spaceBelow;
    const maxHeight = Math.max(160, Math.min(320, openUp ? spaceAbove : spaceBelow));
    const width = Math.max(rect.width, 200);
    const left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
    const top = openUp ? rect.top - gap : rect.bottom + gap;
    setAnchorStyle({ top, left, width, openUp, maxHeight });
  }, [options.length]);

  const finishClose = useCallback(
    (restoreFocus = false) => {
      if (!open || closing) return;
      const finish = () => {
        setOpen(false);
        setClosing(false);
        resumeScroll();
        if (restoreFocus) {
          triggerRef.current?.focus();
        }
      };

      const panel = panelRef.current;
      if (prefersReducedMotion() || !panel) {
        finish();
        return;
      }

      setClosing(true);
      gsap.to(panel, {
        opacity: 0,
        scale: isMobile ? 1 : 0.96,
        y: isMobile ? 22 : anchorStyle.openUp ? 6 : -6,
        duration: 0.18,
        ease: "power2.in",
        onComplete: finish,
      });
    },
    [anchorStyle.openUp, closing, isMobile, open, resumeScroll]
  );

  const openMenu = useCallback(() => {
    if (closeTimerRef.current) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setClosing(false);
    setHighlightedIdx(selectedIndex);
    updatePosition();
    pauseScroll();
    setOpen(true);
  }, [pauseScroll, selectedIndex, updatePosition]);

  // Entrance stagger & geometry positioning
  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    const panel = panelRef.current;
    if (!panel || prefersReducedMotion()) return;

    const rows = optionRefs.current.filter((n): n is HTMLButtonElement => Boolean(n));
    const ctx = gsap.context(() => {
      if (isMobile) {
        gsap.fromTo(
          panel,
          { y: 36, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.28, ease: "power3.out" }
        );
      } else {
        gsap.fromTo(
          panel,
          {
            opacity: 0,
            scale: 0.96,
            y: anchorStyle.openUp ? 6 : -6,
          },
          {
            opacity: 1,
            scale: 1,
            y: 0,
            duration: 0.28,
            ease: "power3.out",
          }
        );
      }
      if (rows.length > 0) {
        gsap.fromTo(
          rows.slice(0, 14),
          { opacity: 0, y: 6 },
          {
            opacity: 1,
            y: 0,
            duration: 0.22,
            stagger: 0.025,
            ease: "power2.out",
          }
        );
      }
    }, panel);

    return () => ctx.revert();
  }, [anchorStyle.openUp, isMobile, open, updatePosition]);

  // Sync sliding hover/active highlight pill position
  useLayoutEffect(() => {
    if (!open) return;
    const row = optionRefs.current[highlightedIdx];
    const wrap = listWrapRef.current;
    if (!row || !wrap) {
      setHighlightRect((prev) => ({ ...prev, visible: false }));
      return;
    }
    setHighlightRect({
      top: row.offsetTop,
      height: row.offsetHeight,
      visible: true,
    });
    if (row.offsetTop < wrap.scrollTop) {
      wrap.scrollTop = row.offsetTop;
    } else if (row.offsetTop + row.offsetHeight > wrap.scrollTop + wrap.clientHeight) {
      wrap.scrollTop = row.offsetTop + row.offsetHeight - wrap.clientHeight;
    }
  }, [highlightedIdx, open]);

  // Reposition & outside click listeners
  useEffect(() => {
    if (!open) return;
    const onOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) {
        return;
      }
      finishClose(false);
    };
    const onResize = () => updatePosition();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        finishClose(true);
      }
    };
    window.addEventListener("mousedown", onOutside);
    window.addEventListener("resize", onResize, { passive: true });
    window.addEventListener("scroll", onResize, { passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onOutside);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize);
      window.removeEventListener("keydown", onKey);
    };
  }, [finishClose, open, updatePosition]);

  useEffect(() => {
    return () => {
      if (open) resumeScroll();
    };
  }, [open, resumeScroll]);

  const handleSelect = (opt: GlassSelectOption) => {
    onChange(opt.value);
    finishClose(true);
  };

  const handleTriggerKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (["Enter", " "].includes(e.key)) {
      e.preventDefault();
      if (!open) {
        openMenu();
      } else if (options[highlightedIdx]) {
        handleSelect(options[highlightedIdx]);
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        openMenu();
      } else {
        setHighlightedIdx((idx) => Math.min(options.length - 1, idx + 1));
      }
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) {
        openMenu();
      } else {
        setHighlightedIdx((idx) => Math.max(0, idx - 1));
      }
      return;
    }
    if (e.key === "Home" && open) {
      e.preventDefault();
      setHighlightedIdx(0);
      return;
    }
    if (e.key === "End" && open) {
      e.preventDefault();
      setHighlightedIdx(options.length - 1);
      return;
    }
    if (e.key === "Tab" && open) {
      finishClose(false);
      return;
    }
    if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) {
      if (typeAheadRef.current.timer) window.clearTimeout(typeAheadRef.current.timer);
      typeAheadRef.current.buffer += e.key.toLowerCase();
      const q = typeAheadRef.current.buffer;
      const found = options.findIndex((o) => o.label.toLowerCase().startsWith(q));
      if (found >= 0) {
        if (!open) openMenu();
        setHighlightedIdx(found);
      }
      typeAheadRef.current.timer = window.setTimeout(() => {
        typeAheadRef.current.buffer = "";
      }, 550);
    }
  };

  const optionListContent = (
    <div
      ref={listWrapRef}
      id={listboxId}
      role="listbox"
      aria-label={ariaLabel}
      className="relative overflow-y-auto no-scrollbar"
      style={{ maxHeight: isMobile ? "56dvh" : `${anchorStyle.maxHeight}px` }}
    >
      <div
        aria-hidden="true"
        className="glass-select-highlight"
        style={{
          top: 0,
          transform: `translate3d(0, ${highlightRect.top}px, 0)`,
          height: `${highlightRect.height}px`,
          opacity: highlightRect.visible ? 1 : 0,
        }}
      />
      {options.map((opt, idx) => {
        const isSelected = opt.value === value;
        const isHighlighted = idx === highlightedIdx;
        return (
          <button
            key={opt.value}
            id={`${listboxId}-opt-${idx}`}
            ref={(el) => {
              optionRefs.current[idx] = el;
            }}
            type="button"
            role="option"
            aria-selected={isSelected}
            data-highlighted={isHighlighted ? "true" : "false"}
            onMouseEnter={() => setHighlightedIdx(idx)}
            onClick={() => handleSelect(opt)}
            className="glass-select-option"
          >
            <span className="truncate">{opt.label}</span>
            <span className="inline-flex items-center gap-2 shrink-0">
              {typeof opt.count === "number" && (
                <span
                  className="tabular-figure text-xs"
                  style={{ color: "var(--color-ink-subtle)" }}
                >
                  {opt.count}
                </span>
              )}
              {isSelected && (
                <Check size={14} style={{ color: "var(--soft-amber)" }} aria-hidden="true" />
              )}
            </span>
          </button>
        );
      })}
    </div>
  );

  const portalContent =
    open &&
    createPortal(
      isMobile ? (
        <div className="glass-sheet-overlay" onClick={() => finishClose(true)}>
          <div ref={panelRef} className="glass-sheet-panel" onClick={(e) => e.stopPropagation()}>
            <div className="glass-sheet-handle" aria-hidden="true" />
            <div
              className="px-2 pb-1 text-xs font-medium"
              style={{ color: "var(--color-ink-muted)" }}
            >
              {ariaLabel}
            </div>
            {optionListContent}
          </div>
        </div>
      ) : (
        <div
          ref={panelRef}
          className="glass-select-panel fixed"
          style={{
            zIndex: 550,
            top: anchorStyle.openUp ? undefined : `${anchorStyle.top}px`,
            bottom: anchorStyle.openUp ? `${window.innerHeight - anchorStyle.top}px` : undefined,
            left: `${anchorStyle.left}px`,
            minWidth: `${anchorStyle.width}px`,
            maxWidth: "min(340px, calc(100vw - 24px))",
            transformOrigin: anchorStyle.openUp ? "bottom left" : "top left",
          }}
        >
          {optionListContent}
        </div>
      ),
      document.body
    );

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listboxId}
        aria-activedescendant={open ? `${listboxId}-opt-${highlightedIdx}` : undefined}
        onClick={() => (open ? finishClose(false) : openMenu())}
        onKeyDown={handleTriggerKeyDown}
        className={`cinema-btn cinema-btn-secondary justify-between gap-2.5 px-4 ${className}`.trim()}
      >
        <span className="truncate">{selectedOption?.label || placeholder}</span>
        <ChevronDown
          size={16}
          aria-hidden="true"
          style={{
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 350ms var(--ease-cinema)",
          }}
        />
      </button>
      {portalContent}
    </>
  );
}
