/**
 * Draw what the detector saw, so a person can check it rather than trust a
 * number. Proof output, not app code — the console never draws landmarks.
 */

import type { Landmark } from '../src/hub/landmarks';

/** MediaPipe's hand topology: which landmarks are joined to which. */
const BONES: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [0, 9], [9, 10], [10, 11], [11, 12],
  [0, 13], [13, 14], [14, 15], [15, 16],
  [0, 17], [17, 18], [18, 19], [19, 20],
  [5, 9], [9, 13], [13, 17],
];

export function drawHand(
  canvas: HTMLCanvasElement,
  source: CanvasImageSource,
  width: number,
  height: number,
  landmarks: readonly Landmark[] | null,
  caption: string,
): void {
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  ctx.drawImage(source, 0, 0, width, height);

  if (landmarks) {
    ctx.strokeStyle = '#00e5a0';
    ctx.lineWidth = Math.max(2, width / 320);
    for (const [a, b] of BONES) {
      const from = landmarks[a];
      const to = landmarks[b];
      if (!from || !to) continue;
      ctx.beginPath();
      ctx.moveTo(from.x * width, from.y * height);
      ctx.lineTo(to.x * width, to.y * height);
      ctx.stroke();
    }
    ctx.fillStyle = '#ff4d6d';
    for (const point of landmarks) {
      ctx.beginPath();
      ctx.arc(point.x * width, point.y * height, Math.max(3, width / 220), 0, Math.PI * 2);
      ctx.fill();
    }
  }

  ctx.fillStyle = 'rgba(0,0,0,0.72)';
  ctx.fillRect(0, height - 34, width, 34);
  ctx.fillStyle = '#ffffff';
  ctx.font = `${Math.max(13, width / 46)}px ui-monospace, monospace`;
  ctx.fillText(caption, 10, height - 12);
}
