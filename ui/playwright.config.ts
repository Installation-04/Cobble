import { defineConfig } from "@playwright/test";
import { STORAGE_STATE } from "./e2e/scenario";

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
  // Order matters on a fresh stack: setup activates the admin and saves the session, the plan
  // spec runs next, then the build spec (needs COBBLE_PACK_MODE=fake), then the store spec, and the shell spec goes
  // last because it logs out and changes preferences.
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "plan",
      testMatch: /plan\.spec\.ts/,
      dependencies: ["setup"],
      use: { storageState: STORAGE_STATE },
    },
    {
      name: "build",
      testMatch: /build\.spec\.ts/,
      dependencies: ["plan"],
      use: { storageState: STORAGE_STATE },
    },
    {
      // The module-manager is not part of the e2e stack (it needs the Docker socket): this spec
      // mocks the modules API in the browser. Real installs are covered by `make smoke-modules`.
      name: "store",
      testMatch: /store\.spec\.ts/,
      dependencies: ["build"],
      use: { storageState: STORAGE_STATE },
    },
    {
      name: "shell",
      testMatch: /shell\.spec\.ts/,
      dependencies: ["store"],
      use: { storageState: STORAGE_STATE },
    },
  ],
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
