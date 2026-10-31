import { defineConfig } from "@playwright/test";

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;
// Chromium refuses to start its sandbox as root (typical in containers and CI).
const isRoot = typeof process.getuid === "function" && process.getuid() === 0;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    colorScheme: "light",
    locale: "en-US",
    trace: "retain-on-failure",
    launchOptions: {
      executablePath,
      args: isRoot ? ["--no-sandbox"] : [],
    },
  },
});
