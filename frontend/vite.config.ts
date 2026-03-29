import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load .env* from repo root (same as backend) so VITE_API_URL can live next to Fly secrets.
const envDir = path.resolve(__dirname, "..");

// GitHub Pages project site: https://<user>.github.io/<repo>/  → set VITE_BASE_PATH=/<repo>/
const rawBase = process.env.VITE_BASE_PATH ?? "/";
const base =
  rawBase === "/" ? "/" : rawBase.endsWith("/") ? rawBase : `${rawBase}/`;

export default defineConfig({
  envDir,
  base,
  plugins: [react()],
  server: {
    port: 5173,
  },
});
