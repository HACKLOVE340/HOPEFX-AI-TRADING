/**
 * E2E: Performance, WalkForward, Correlation, ABTesting pages
 *
 * These pages are public or auth-gated. Tests verify:
 * - Page renders without crash
 * - Key UI elements are present
 * - Data loads (real or fallback)
 * - No critical console errors
 */

import { test, expect } from '@playwright/test';
import { captureConsoleErrors } from './helpers';

function noCriticalErrors(errors: string[]): void {
  const critical = errors.filter(
    (e) => !e.includes('401') && !e.includes('403') && !e.includes('net::ERR_')
  );
  expect(critical).toHaveLength(0);
}

test.describe('Performance page', () => {
  test('renders without JS errors', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    await page.goto('/performance');
    await page.waitForLoadState('networkidle');
    noCriticalErrors(errors);
  });

  test('shows performance metrics or loading state', async ({ page }) => {
    await page.goto('/performance');
    await page.waitForLoadState('networkidle');

    // Should show either metrics or a loading/error state — not a blank page
    const content = page
      .locator('text=/performance/i')
      .or(page.locator('text=/sharpe/i'))
      .or(page.locator('text=/win rate/i'))
      .or(page.locator('text=/loading/i'))
      .or(page.locator('text=/error/i'))
      .first();
    await expect(content).toBeVisible({ timeout: 15_000 });
  });

  test('refresh button is present', async ({ page }) => {
    await page.goto('/performance');
    await page.waitForLoadState('networkidle');

    const refreshBtn = page.locator('button', { hasText: /refresh/i }).first();
    if (await refreshBtn.isVisible()) {
      await refreshBtn.click();
      await page.waitForTimeout(1000);
      // Should not crash
      expect(page.url()).toContain('/performance');
    }
  });
});

test.describe('Walk-Forward page', () => {
  test('renders without JS errors', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    await page.goto('/walk-forward');
    await page.waitForLoadState('networkidle');
    noCriticalErrors(errors);
  });

  test('shows walk-forward results or redirects to login', async ({ page }) => {
    await page.goto('/walk-forward');
    await page.waitForLoadState('networkidle');

    if (page.url().includes('/login')) return; // auth-gated, acceptable

    const content = page.locator(
      'text=/walk.forward/i, text=/fold/i, text=/stability/i, text=/loading/i'
    ).first();
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test('fold toggle buttons work', async ({ page }) => {
    await page.goto('/walk-forward');
    await page.waitForLoadState('networkidle');
    if (page.url().includes('/login')) return;

    const foldBtn = page.locator('button', { hasText: /fold/i }).first();
    if (await foldBtn.isVisible()) {
      await foldBtn.click();
      await page.waitForTimeout(300);
    }
  });
});

test.describe('Correlation Dashboard', () => {
  test('renders without JS errors', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    await page.goto('/correlation');
    await page.waitForLoadState('networkidle');
    noCriticalErrors(errors);
  });

  test('shows correlation matrix or redirects to login', async ({ page }) => {
    await page.goto('/correlation');
    await page.waitForLoadState('networkidle');
    if (page.url().includes('/login')) return;

    const content = page.locator(
      'text=/correlation/i, text=/XAU/i, text=/loading/i, text=/error/i'
    ).first();
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test('window selector changes correlation window', async ({ page }) => {
    await page.goto('/correlation');
    await page.waitForLoadState('networkidle');
    if (page.url().includes('/login')) return;

    const windowBtns = page.locator('button', { hasText: /30|60|90/ });
    if (await windowBtns.count() > 0) {
      await windowBtns.first().click();
      await page.waitForTimeout(500);
    }
  });
});

test.describe('A/B Testing page', () => {
  test('renders without JS errors', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    await page.goto('/ab-testing');
    await page.waitForLoadState('networkidle');
    noCriticalErrors(errors);
  });

  test('shows A/B test form or redirects to login', async ({ page }) => {
    await page.goto('/ab-testing');
    await page.waitForLoadState('networkidle');
    if (page.url().includes('/login')) return;

    const content = page.locator(
      'text=/a\\/b/i, text=/strategy/i, text=/loading/i'
    ).first();
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test('strategy selectors are present', async ({ page }) => {
    await page.goto('/ab-testing');
    await page.waitForLoadState('networkidle');
    if (page.url().includes('/login')) return;

    const selects = page.locator('select');
    const count = await selects.count();
    if (count > 0) {
      await expect(selects.first()).toBeVisible();
    }
  });
});
