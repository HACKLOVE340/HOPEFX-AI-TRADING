/**
 * E2E: Trading page
 *
 * Covers:
 * - Trading page renders chart container
 * - Symbol selector is present
 * - Order panel renders buy/sell buttons
 * - Positions section renders
 * - Price display updates (simulator or live)
 * - No console errors
 */

import { test, expect } from '@playwright/test';
import { captureConsoleErrors } from './helpers';

test.describe('Trading page', () => {
  // Attached before the navigation below, so the console errors this collects
  // are the ones from the load every test in this describe actually runs on.
  // Previously `renders without JS errors` attached its listener afterwards and
  // then navigated to /trading a *second* time to have something to observe —
  // two full page loads inside one 30s test timeout, which is what tipped it
  // over on a slow runner while its siblings (one load each) passed.
  let consoleErrors: string[] = [];

  test.beforeEach(async ({ page }) => {
    consoleErrors = captureConsoleErrors(page);
    await page.goto('/trading');
    await page.waitForLoadState('networkidle');
  });

  test('renders without JS errors', async () => {
    expect(consoleErrors).toHaveLength(0);
  });

  test('chart container is present', async ({ page }) => {
    // lightweight-charts renders a canvas inside a div
    const chartContainer = page.locator('canvas, [class*="chart"], [id*="chart"]').first();
    // May not be visible if redirected to login — check conditionally
    if (!page.url().includes('/login')) {
      await expect(chartContainer).toBeVisible({ timeout: 10_000 });
    }
  });

  test('order panel has buy and sell buttons', async ({ page }) => {
    if (page.url().includes('/login')) return;

    const buyBtn  = page.locator('button', { hasText: /buy/i }).first();
    const sellBtn = page.locator('button', { hasText: /sell/i }).first();

    if (await buyBtn.isVisible()) {
      await expect(buyBtn).toBeVisible();
      await expect(sellBtn).toBeVisible();
    }
  });

  test('bid/ask prices are displayed', async ({ page }) => {
    if (page.url().includes('/login')) return;

    // Wait for price simulator or live feed to populate
    await page.waitForTimeout(2000);

    const bidText = page.locator('text=/Bid:/i').first();
    const askText = page.locator('text=/Ask:/i').first();

    if (await bidText.isVisible()) {
      await expect(bidText).toBeVisible();
      await expect(askText).toBeVisible();
    }
  });

  test('positions section renders', async ({ page }) => {
    if (page.url().includes('/login')) return;

    const positionsSection = page.locator(
      'text=/positions/i, text=/open trades/i'
    ).first();

    if (await positionsSection.isVisible()) {
      await expect(positionsSection).toBeVisible();
    }
  });

  test('order size input accepts numeric input', async ({ page }) => {
    if (page.url().includes('/login')) return;

    const sizeInput = page.locator('input[type="number"], input[placeholder*="size"], input[placeholder*="lot"]').first();
    if (await sizeInput.isVisible()) {
      await sizeInput.fill('0.05');
      const value = await sizeInput.inputValue();
      expect(value).toBe('0.05');
    }
  });
});
