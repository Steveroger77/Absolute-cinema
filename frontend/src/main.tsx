import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tailwind.css";
import "./styles/base.css";
import { detectCapabilityTier } from "./lib/tier";
import { App } from "./App";

detectCapabilityTier();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
