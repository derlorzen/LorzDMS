import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./": alle Pfade relativ, damit die Oberfläche unter jedem Ingress-Pfad läuft.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "../app/lorzdms/static", emptyOutDir: true, sourcemap: false },
  server: { proxy: { "/api": "http://127.0.0.1:8099" } },
});
