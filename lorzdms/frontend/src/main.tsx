import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// Dark Mode: Home-Assistant-Thema übernehmen (Ingress-iframe ist same-origin),
// sonst Systemeinstellung.
function applyTheme() {
  let dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  try {
    const ha = window.parent?.document?.querySelector("home-assistant") as unknown as { hass?: { themes?: { darkMode?: boolean } } } | null;
    if (ha?.hass?.themes && typeof ha.hass.themes.darkMode === "boolean") dark = ha.hass.themes.darkMode;
  } catch {
    /* nicht im HA-Frame */
  }
  document.documentElement.classList.toggle("dark", dark);
}
applyTheme();
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme);
setInterval(applyTheme, 5000);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
