/**
 * E2E test helpers — shared utilities for Playwright tests.
 */

import { type Page, expect } from '@playwright/test';

export const TEST_USER = {
  email:    process.env.E2E_USER_EMAIL    ?? 'test@hopefx.com',
  password: process.env.E2E_USER_PASSWORD ?? 'TestPass123!',
  username: 'e2e_tester',
};

export const ADMIN_USER = {
  email:    process.env.E2E_ADMIN_EMAIL    ?? 'admin@hopefx.com',
  password: process.env.E2E_ADMIN_PASSWORD ?? 'AdminPass123!',
};

/**
 * Log in via the UI login form and wait for the dashboard to load.
 * Stores auth state in the page's localStorage via the Zustand persist middleware.
 */
export async function loginAs(page: Page, user = TEST_USER): Promise<void> {
  await page.goto('/login');
  await page.waitForSelector('input[type="email"]', { timeout: 10_000 });

  await page.fill('input[type="email"]',    user.email);
  await page.fill('input[type="password"]', user.password);
  await page.click('button[type="submit"]');

  // Wait for redirect to dashboard
  await page.waitForURL('**/dashboard', { timeout: 15_000 });
  await expect(page.locator('text=Dashboard')).toBeVisible({ timeout: 10_000 });
}

/**
 * Log out via the sidebar Sign out button.
 */
export async function logout(page: Page): Promise<void> {
  const signOutBtn = page.locator('button', { hasText: 'Sign out' });
  if (await signOutBtn.isVisible()) {
    await signOutBtn.click();
    await page.waitForURL('**/', { timeout: 5_000 });
  }
}

/**
 * Wait for the page to finish loading (no spinner visible).
 */
export async function waitForLoad(page: Page): Promise<void> {
  // Wait for network idle
  await page.waitForLoadState('networkidle', { timeout: 15_000 });
}

/**
 * Capture browser console errors, filtering out known-benign noise.
 *
 * Filtered automatically:
 *   - ResizeObserver loop errors (browser quirk, not app errors)
 *   - favicon 404s
 *   - net::ERR_* network errors (backend not running in CI)
 *   - HTTP 401/403/500 resource failures (expected when backend is absent)
 */
export function captureConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (
        text.includes('ResizeObserver') ||
        text.includes('favicon') ||
        text.includes('net::ERR_') ||
        text.includes('401') ||
        text.includes('403') ||
        text.includes('500') ||
        text.includes('Failed to load resource')
      ) return;
      errors.push(text);
    }
  });
  return errors;
}
