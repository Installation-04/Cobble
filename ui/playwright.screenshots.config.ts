import { defineConfig } from "@playwright/test";

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;
const isRoot = typeof process.getuid === "function" && process.getuid() === 0;

// Documentation screenshots (`make screenshots`): a separate config so the normal e2e suite
// never runs this. It needs a FRESH stack in fake pack mode.
export default defineConfig({
  testDir: "./e2e/screenshots",
  workers: 1,
  retries: 0,
  timeout: 900_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    viewport: { width: 1280, height: 800 },
    colorScheme: "light",
    locale: "en-US",
    launchOptions: { executablePath, args: isRoot ? ["--no-sandbox"] : [] },
  },
});
