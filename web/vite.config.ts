import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FastAPI serves the built dist from /static; API endpoints live at the root.
const API_PREFIXES = [
  "/health",
  "/models",
  "/predict",
  "/runs",
  "/agent",
  "/datasets",
  "/eda",
  "/experiment",
  "/experiments",
  "/jobs",
  "/train",
  "/sandbox",
  "/proposals",
  "/agent-sessions",
  "/benchmarks",
];

const proxy = Object.fromEntries(
  API_PREFIXES.map((prefix) => [
    prefix,
    { target: "http://127.0.0.1:8000", changeOrigin: true },
  ]),
);

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "../thelab/model_service/static",
    emptyOutDir: false, // build_ui.sh clears everything except .gitkeep
  },
  server: { proxy },
});
