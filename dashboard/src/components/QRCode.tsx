/**
 * QRCode — renders a QR code locally, in the browser.
 *
 * The crypto checkout used to draw the deposit-address QR with
 * `<img src="https://api.qrserver.com/...?data=ADDRESS">`, on a comment that
 * said "in production use a real QR library". That is the production bundle —
 * `dashboard/dist/` is committed and mounted at `/godmode/` — and the picture a
 * paying customer scans is whatever that third party returns. Swap the image
 * and the funds go elsewhere, while the address text printed underneath still
 * reads correctly, so the usual "check the address" advice does not catch it.
 *
 * Nothing leaves the browser now. Encoding is done by the `qrcode` package
 * onto a canvas. This mirrors frontend/src/components/QRCode.tsx.
 */
import { useEffect, useRef, useState } from 'react';
import QR from 'qrcode';

interface QRCodeProps {
  /** The value to encode. Never send this anywhere. */
  value: string;
  /** Rendered width/height in CSS pixels. */
  size?: number;
  /** Background colour, hex. */
  bgColor?: string;
  /** Foreground (module) colour, hex. */
  fgColor?: string;
  /** Accessible label; describe what scanning it does. */
  alt: string;
  /** Rendered instead of the canvas if encoding fails. */
  fallback?: React.ReactNode;
}

export default function QRCode({
  value,
  size = 180,
  bgColor = '#1e293b',
  fgColor = '#f1f5f9',
  alt,
  fallback = null,
}: QRCodeProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !value) return;

    let cancelled = false;
    setFailed(false);

    QR.toCanvas(canvas, value, {
      width: size,
      margin: 2,
      color: { dark: fgColor, light: bgColor },
      // Medium recovery keeps the code scannable if part of the screen is
      // obscured, without inflating it the way 'H' would.
      errorCorrectionLevel: 'M',
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });

    return () => {
      cancelled = true;
    };
  }, [value, size, bgColor, fgColor]);

  if (failed) return <>{fallback}</>;

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={alt}
      width={size}
      height={size}
      style={{ width: size, height: size, borderRadius: 8, display: 'block' }}
    />
  );
}
