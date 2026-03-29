import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration.
 *
 * In CI (CI=true) the frontend dev server is NOT started automatically —
 * the CI job starts it separately. Locally, Playwright starts it via webServer.
 *
 * Run locally:  npx playwright test
 * Run in CI:    npx playwright test  (CI=true, server already running on 5173)
 */

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173';
const IS_CI    = !!process.env.CI;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: IS_CI,
  retries: IS_CI ? 2 : 0,
  workers: IS_CI ? 1 : undefined,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Consistent viewport
    viewport: { width: 1280, height: 800 },
    // Ignore HTTPS errors in dev/CI
    ignoreHTTPSErrors: true,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Uncomment to add more browsers in CI:
    // { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    // { name: 'webkit',  use: { ...devices['Desktop Safari']  } },
  ],

  // Start the Vite dev server locally (skipped in CI where it's pre-started)
  webServer: IS_CI
    ? undefined
    : {
        command: 'npm run dev',
        url: BASE_URL,
        reuseExistingServer: true,
        timeout: 60_000,
      },
});
