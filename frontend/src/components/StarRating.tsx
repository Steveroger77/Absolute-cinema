import { useState } from "react";
import { Star } from "lucide-react";

interface StarRatingProps {
  value: number | null;
  onChange: (rating: number) => void;
  disabled?: boolean;
  size?: number;
}

export function StarRating({ value, onChange, disabled = false, size = 22 }: StarRatingProps) {
  const [hoverVal, setHoverVal] = useState<number | null>(null);
  const [poppedStar, setPoppedStar] = useState<number | null>(null);
  const displayVal = hoverVal ?? value ?? 0;

  const triggerSelect = (score: number, starIdx: number) => {
    setPoppedStar(starIdx);
    window.setTimeout(() => setPoppedStar(null), 260);
    onChange(score);
  };

  return (
    <div
      role="radiogroup"
      aria-label="Rate this film out of 5 stars"
      className="inline-flex items-center gap-1"
      onMouseLeave={() => setHoverVal(null)}
    >
      {[1, 2, 3, 4, 5].map((star) => {
        const halfScore = star - 0.5;
        const fullScore = star;
        const fillPercent = displayVal >= fullScore ? 100 : displayVal >= halfScore ? 50 : 0;
        const isPopped = poppedStar === star;

        return (
          <div
            key={star}
            className="relative inline-flex items-center"
            style={{ width: size + 8, height: size + 12 }}
          >
            {/* Left half-star hit target */}
            <button
              type="button"
              disabled={disabled}
              role="radio"
              aria-checked={value === halfScore}
              aria-label={`${halfScore} stars`}
              onMouseEnter={() => setHoverVal(halfScore)}
              onClick={() => triggerSelect(halfScore, star)}
              className="absolute left-0 top-0 bottom-0 w-1/2 z-10 cursor-pointer bg-transparent border-0 p-0"
            />
            {/* Right full-star hit target */}
            <button
              type="button"
              disabled={disabled}
              role="radio"
              aria-checked={value === fullScore}
              aria-label={`${fullScore} stars`}
              onMouseEnter={() => setHoverVal(fullScore)}
              onClick={() => triggerSelect(fullScore, star)}
              className="absolute right-0 top-0 bottom-0 w-1/2 z-10 cursor-pointer bg-transparent border-0 p-0"
            />

            <div
              className="relative pointer-events-none mx-auto"
              style={{
                width: size,
                height: size,
                transform: isPopped ? "scale(1.24)" : "scale(1)",
                transition: "transform 240ms var(--ease-cinema)",
              }}
            >
              <Star
                size={size}
                strokeWidth={1.6}
                style={{ color: "var(--color-ink-subtle)" }}
                aria-hidden="true"
              />
              {fillPercent > 0 && (
                <div
                  className="absolute inset-0 overflow-hidden transition-opacity duration-150"
                  style={{ clipPath: `inset(0 ${100 - fillPercent}% 0 0)` }}
                >
                  <Star
                    size={size}
                    strokeWidth={1.6}
                    fill="currentColor"
                    style={{ color: "var(--color-accent)" }}
                    aria-hidden="true"
                  />
                </div>
              )}
            </div>
          </div>
        );
      })}
      <span
        className="tabular-figure ml-2 text-sm"
        style={{ color: "var(--color-ink-muted)", minWidth: "3ch" }}
      >
        {displayVal > 0 ? displayVal.toFixed(1) : "Rate"}
      </span>
    </div>
  );
}
