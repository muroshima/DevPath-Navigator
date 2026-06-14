import { defineConfig, devices } from "@playwright/test";

// Single browser (chromium) keeps CI time predictable on the free tier;
// adding firefox/webkit would triple install + run time without buying
// much for a Next.js SPA that targets evergreen browsers.
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "line" : "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  // Boot a dev server before tests run. `npm run dev` is what humans use;
  // `npm run build && npm run start` would be closer to prod but doubles
  // CI time. The tests mock both API routes, so server-side env vars
  // (AGENT_URL, etc.) don't matter.
  webServer: {
    // Production build under `next start` rather than `next dev`. The dev
    // server runs React in Strict Mode (double-mount) and serves an
    // unoptimized bundle; for an e2e test we want the same artifact CI
    // produces, not a hot-reload-friendly variant. Also avoids a known
    // dev-only issue where `next dev`'s Fast Refresh wrapper can swallow
    // synthetic input events fired from outside React.
    command: "npm run build && npm run start",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 180 * 1000,
  },
});
