/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  // Relative asset URLs: the page also works under a prefix (the milestone previews).
  base: "./",
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "jsdom", globals: true },
});
