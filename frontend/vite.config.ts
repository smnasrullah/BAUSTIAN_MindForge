import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { codeSplitting, firstLoadGraph } from "./vite.chunks.ts";

export default defineConfig({
  plugins: [react(), tailwindcss(), firstLoadGraph()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    rolldownOptions: { output: { codeSplitting } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
