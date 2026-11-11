import { useEffect, useState } from "react";
import { useAmbient } from "../context/AmbientContext";

export function AmbientBackdrop() {
  const { palette } = useAmbient();
  const [activeLayer, setActiveLayer] = useState<"a" | "b">("a");
  const [layerA, setLayerA] = useState(palette);
  const [layerB, setLayerB] = useState(palette);

  useEffect(() => {
    const root = document.documentElement.style;
    root.setProperty("--ambient-1", palette.c1);
    root.setProperty("--ambient-2", palette.c2);
    root.setProperty("--ambient-3", palette.c3);

    if (activeLayer === "a") {
      setLayerB(palette);
      setActiveLayer("b");
    } else {
      setLayerA(palette);
      setActiveLayer("a");
    }
    // Intentionally trigger only when palette values change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [palette.c1, palette.c2, palette.c3]);

  const buildGradient = (p: typeof palette) =>
    `radial-gradient(62% 54% at 20% 8%, ${p.c2}54 0%, transparent 72%), ` +
    `radial-gradient(58% 48% at 78% 18%, ${p.c1}60 0%, transparent 74%), ` +
    `radial-gradient(80% 55% at 50% 92%, ${p.c3}70 0%, transparent 78%)`;

  return (
    <div id="ambient-backdrop" className="ambient-backdrop-root" aria-hidden="true">
      <div
        className="ambient-layer"
        style={{
          backgroundImage: buildGradient(layerA),
          opacity: activeLayer === "a" ? 1 : 0,
        }}
      />
      <div
        className="ambient-layer"
        style={{
          backgroundImage: buildGradient(layerB),
          opacity: activeLayer === "b" ? 1 : 0,
        }}
      />
      <div className="ambient-grain" />
    </div>
  );
}
