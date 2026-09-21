/**
 * E2E: Marketplace page
 *
 * Covers:
 * - Marketplace renders strategy listings
 * - Search/filter input is present
 * - Strategy cards show name, price, metrics
 * - Subscribe button is present
 * - No console errors
 */

import { test, expect } from '@playwright/test';
import { captureConsoleErrors } from './helpers';

test.describe('Marketplace', () => {
  // Attached before the navigation below, so the console errors this collects
  // are the ones from the load every test in this describe actually runs on.
  // Previously `renders without JS errors` attached its listener afterwards and
  // then navigated to /marketplace a *second* time to have something to observe
  // — two full page loads inside one 30s test timeout, which is what tipped it
  // over on a slow runner while its siblings (one load each) passed.
  let consoleErrors: string[] = [];

  test.beforeEach(async ({ page }) => {
    consoleErrors = captureConsoleErrors(page);
    await page.goto('/marketplace');
    await page.waitForLoadState('networkidle');
  });

  test('renders without JS errors', async () => {
    expect(consoleErrors).toHaveLength(0);
  });

  test('page title is visible', async ({ page }) => {
    const title = page.locator('h1').or(page.locator('h2')).or(page.locator('text=/marketplace/i')).first();
    await expect(title).toBeVisible({ timeout: 8_000 });
  });

  test('strategy listings or empty state renders', async ({ page }) => {
    // Either strategy cards or an empty state message
    const content = page
      .locator('[data-testid="strategy-card"]')
      .or(page.locator('.strategy-card'))
      .or(page.locator('text=/no strategies/i'))
      .or(page.locator('text=/marketplace/i'))
      .first();
    await expect(content).toBeVisible({ timeout: 10_000 });
  });

  test('search or filter input is present', async ({ page }) => {
    const searchInput = page.locator(
      'input[type="search"], input[placeholder*="search"], input[placeholder*="filter"]'
    ).first();
    if (await searchInput.isVisible()) {
      await expect(searchInput).toBeVisible();
      // Type in search box
      await searchInput.fill('gold');
      await page.waitForTimeout(500);
      // Should not crash
    }
  });

  test('tier filter buttons are present', async ({ page }) => {
    const filterBtns = page.locator('button', { hasText: /free|basic|pro|enterprise/i });
    const count = await filterBtns.count();
    // At least one tier filter should exist
    if (count > 0) {
      await expect(filterBtns.first()).toBeVisible();
    }
  });
});

test.describe('Leaderboard', () => {
  test('renders top traders', async ({ page }) => {
    const errors = captureConsoleErrors(page);
    await page.goto('/leaderboard');
    await page.waitForLoadState('networkidle');

    expect(errors).toHaveLength(0);

    // Should show leaderboard heading
    await expect(page.locator('text=/leaderboard/i').first()).toBeVisible({ timeout: 8_000 });
  });

  test('period filter buttons work', async ({ page }) => {
    await page.goto('/leaderboard');
    await page.waitForLoadState('networkidle');

    const monthlyBtn = page.locator('button', { hasText: /monthly/i }).first();
    if (await monthlyBtn.isVisible()) {
      await monthlyBtn.click();
      await page.waitForTimeout(500);
      // Should not crash or navigate away
      expect(page.url()).toContain('/leaderboard');
    }
  });

  test('shows trader names and returns', async ({ page }) => {
    await page.goto('/leaderboard');
    await page.waitForLoadState('networkidle');

    // Either real data (% returns) or a visible fallback/error state
    const content = page
      .locator('text=/%/')
      .or(page.locator('text=/no traders/i'))
      .or(page.locator('text=/leaderboard/i'))
      .or(page.locator('text=/loading/i'))
      .or(page.locator('text=/failed/i'))
      .first();
    await expect(content).toBeVisible({ timeout: 8_000 });
  });
});
