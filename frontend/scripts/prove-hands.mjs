/**
 * npm run prove:hands — §18's evidence, produced by running it.
 *
 * Starts Vite over the real source tree, drives real Chromium at
 * `proof/index.html`, and reads back what the production `HandDetector` made of
 * MediaPipe's own photograph of a hand. The model and WASM come from this
 * origin via `scripts/fetch_hand_model.py`.
 *
 * Not a vitest test, deliberately: it needs a real browser with WebGL and a
 * 7.8 MB model on disk, and a unit suite that quietly skips when neither is
 * present would be a gate that reports success for work that did not happen.
 * It exits non-zero and says which piece is missing instead.
 */

import { existsSync } from 'node:fs';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { chromium } from 'playwright';
import { createServer } from 'vite';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, '..');
const PORT = 8788;

// The environment ships browser build 1194; playwright 1.60 pins 1223. Pointing
// at the installed binary is the documented fix — `playwright install` is not
// available here and would fetch a second copy of a browser we already have.
const CHROMIUM = '/opt/pw-browsers/chromium';

function requireDeployed() {
  const missing = [];
  if (!existsSync(path.join(FRONTEND, 'public/models/hand_landmarker.task'))) {
    missing.push('public/models/hand_landmarker.task');
  }
  if (!existsSync(path.join(FRONTEND, 'public/vendor/tasks-vision/wasm'))) {
    missing.push('public/vendor/tasks-vision/wasm');
  }
  if (missing.length > 0) {
    console.error('The hand-landmark model is not deployed. Missing:');
    for (const item of missing) console.error(`  ${item}`);
    console.error('\nRun:  python scripts/fetch_hand_model.py');
    process.exit(2);
  }
}

const SWIPE = path.join(FRONTEND, 'proof/swipe.y4m');
const SHOTS = path.join(FRONTEND, 'proof/shots');

async function capture(page, name) {
  const shot = await page.$('#shot');
  if (!shot) return null;
  const file = path.join(SHOTS, name);
  await shot.screenshot({ path: file });
  return file;
}

async function main() {
  requireDeployed();
  await mkdir(SHOTS, { recursive: true });

  const server = await createServer({
    root: FRONTEND,
    server: { port: PORT, host: '127.0.0.1' },
    logLevel: 'error',
  });
  await server.listen();

  const browser = await chromium.launch({
    executablePath: existsSync(CHROMIUM) ? CHROMIUM : undefined,
    args: ['--no-sandbox'],
  });
  const page = await browser.newPage();
  page.on('pageerror', (error) => console.error('  [pageerror]', error.message));

  let result;
  let stillShot = null;
  try {
    await page.goto(`http://127.0.0.1:${PORT}/proof/index.html`, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__proof !== undefined, null, { timeout: 180000 });
    result = await page.evaluate(() => window.__proof);
    stillShot = await capture(page, 'still.png');
  } finally {
    await browser.close();
    await server.close();
  }

  console.log(JSON.stringify(result, null, 2));
  if (stillShot) console.log(`screenshot ${path.relative(FRONTEND, stillShot)}`);

  const failures = [];
  if (!result?.ok) failures.push(`the run itself failed: ${result?.error ?? 'no reason given'}`);
  if (result?.landmarksPerFrame !== 21) failures.push(`expected 21 landmarks, got ${result?.landmarksPerFrame}`);
  if (!(result?.framesRead > 0)) failures.push('no frames were read');
  if (result?.statusState !== 'measured') failures.push(`expected status measured, got ${result?.statusState}`);
  if (!(result?.trackPoints > 0)) failures.push('the landmarks produced no track');
  if (result?.pointingAt !== 'gold-chart' && result?.pointingAt !== 'order-ticket') {
    failures.push(`the fingertip did not land on a panel: ${JSON.stringify(result?.pointingAt)}`);
  }
  // Was `!== 'measured'` alone, which passed while the detector reported
  // `unsupported` after close() — telling an operator who switched gestures off
  // that their browser could not run them. An assertion that only rules out one
  // wrong answer lets the others through.
  if (result?.closedState !== 'unpermitted') {
    failures.push(`after close() the state should be unpermitted, got ${result?.closedState}`);
  }

  if (failures.length > 0) {
    console.error('\nPROOF FAILED');
    for (const failure of failures) console.error(`  ${failure}`);
    process.exit(1);
  }
  console.log('\nPHASE 1 PASSED: the production HandDetector read a real hand — 21 landmarks, a track, a panel.');

  if (!existsSync(SWIPE)) {
    console.error('\nPhase 2 skipped: proof/swipe.y4m is missing.');
    console.error('Run:  python scripts/make_swipe_y4m.py');
    process.exit(3);
  }
  await phaseTwo();
}

/**
 * The path an operator actually uses: a camera, not a still.
 *
 * Chromium serves proof/swipe.y4m as the webcam, so the CAMERA is the only
 * synthetic part — the hand in those frames is the same real photograph.
 */
async function phaseTwo() {
  const server = await createServer({
    root: FRONTEND,
    server: { port: PORT + 1, host: '127.0.0.1' },
    logLevel: 'error',
  });
  await server.listen();

  const browser = await chromium.launch({
    executablePath: existsSync(CHROMIUM) ? CHROMIUM : undefined,
    args: [
      '--no-sandbox',
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-video-capture=${SWIPE}`,
    ],
  });
  const context = await browser.newContext({ permissions: ['camera'] });
  const page = await context.newPage();
  page.on('pageerror', (error) => console.error('  [pageerror]', error.message));

  let result;
  let shot = null;
  try {
    await page.goto(`http://127.0.0.1:${PORT + 1}/proof/camera.html`, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__proof !== undefined, null, { timeout: 180000 });
    result = await page.evaluate(() => window.__proof);
    shot = await capture(page, 'camera.png');
  } finally {
    await browser.close();
    await server.close();
  }

  console.log('\n--- phase 2: the camera path ---');
  console.log(JSON.stringify(result, null, 2));
  if (shot) console.log(`screenshot ${path.relative(FRONTEND, shot)}`);

  const failures = [];
  if (!result?.ok) failures.push(`the run failed: ${result?.error ?? 'no reason given'}`);
  if (!(result?.framesSeen > 0)) failures.push('no camera frames were read');
  if (result?.statusBeforeStop !== 'measured') {
    failures.push(`expected measured while reading, got ${result?.statusBeforeStop}`);
  }
  if (!(result?.tracks > 0)) failures.push('the camera produced no gesture track');
  // swipe_left, not right: the hand travels left-to-right in the video and the
  // console mirrors the camera, because an operator sees their own reflection.
  if (!result?.recognised?.includes('swipe_left')) {
    failures.push(`expected a mirrored swipe_left, got ${JSON.stringify(result?.recognised)}`);
  }

  if (failures.length > 0) {
    console.error('\nPHASE 2 FAILED');
    for (const failure of failures) console.error(`  ${failure}`);
    process.exit(1);
  }
  console.log('\nPHASE 2 PASSED: getUserMedia -> HandDetector -> HandGestureSource -> recogniseGesture = swipe_left.');
}

await main();
