import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for the Phase 1 acceptance test.
 *
 * `@playwright/test` is intentionally *not* a dependency of the default install
 * (the browser download is large and the unit suite does not need it). Install it
 * on demand:
 *
 *   npm install -D @playwright/test && npx playwright install chromium
 *   npm run test:e2e
 *
 * Both servers are started by Playwright. If you already have them running,
 * `reuseExistingServer` will use them instead.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "only-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "cd ../backend && .venv/bin/uvicorn app.main:app --port 8000",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: true,
      timeout: 300_000,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 300_000,
    },
  ],
});
