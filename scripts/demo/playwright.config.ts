import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const FRONTEND_DIR = path.resolve(__dirname, "../../frontend");

// Demo recording config — distinct from the e2e CI config under
// frontend/playwright.config.ts. This one:
//   * records every test to ./output/raw/ as WebM
//   * uses a 1280x720 viewport so the video matches typical README
//     embed widths without re-encoding
//   * disables retries (a recording either succeeds first try or you
//     re-record by hand)
//   * spins up the production-built frontend (same reason as the e2e
//     config — `next dev`'s Strict Mode double-mount disrupts
//     scripted input)
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  // Demo recordings hold deliberate pauses to match TTS pacing. The
  // 90s spec runs ~95s including slowMo and expect-wait overhead, so
  // give a comfortable headroom above either spec's expected runtime.
  timeout: 180 * 1000,
  use: {
    baseURL: "http://127.0.0.1:3000",
    viewport: { width: 1280, height: 720 },
    video: {
      mode: "on",
      size: { width: 1280, height: 720 },
    },
    // Slow each scripted action down a touch. Real users don't click
    // at machine speed and the resulting video looks robotic without
    // this. 80ms is enough to read each visual change without
    // ballooning total runtime.
    launchOptions: {
      slowMo: 80,
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  outputDir: path.resolve(__dirname, "output/raw"),
  webServer: {
    command: "npm run build && npm run start",
    cwd: FRONTEND_DIR,
    url: "http://127.0.0.1:3000",
    reuseExistingServer: true,
    timeout: 180 * 1000,
  },
});
