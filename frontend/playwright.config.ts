import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration.
 *
 * In CI: Playwright builds and starts `vite preview` (stable, no HMR overhead).
 * Locally: Playwright starts `vite dev` and reuses an existing server if running.
 *
 * Run locally:  npx playwright test
 * Run in CI:    npx playwright test  (CI=true)
 */

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173';
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
    viewport: { width: 1280, height: 800 },
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

  // CI: build then serve via `vite preview` (no HMR, deterministic).
  // Local: use `vite dev` and reuse an already-running server.
  webServer: {
    command: IS_CI
      ? 'npm run build && npm run preview -- --host 127.0.0.1 --port 5173'
      : 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: BASE_URL,
    reuseExistingServer: !IS_CI,
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
