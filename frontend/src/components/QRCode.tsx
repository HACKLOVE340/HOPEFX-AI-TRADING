/**
 * QRCode — renders a QR code locally, in the browser.
 *
 * Both the crypto deposit address and the 2FA otpauth URI were previously
 * rendered by building an <img src="https://api.qrserver.com/...?data=SECRET">.
 * That sends the encoded value to a third party and trusts the image that comes
 * back:
 *
 *   - For a payment address, whoever controls that response controls where the
 *     customer's funds go, while the address text below still reads correctly.
 *   - For 2FA, the otpauth URI *is* the shared secret. Sending it offsite
 *     defeats the second factor for anyone who can read those request logs.
 *
 * Nothing leaves the browser now. Encoding is done by the `qrcode` package
 * (~20 KB) onto a canvas.
 */
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
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
  fallback?: ReactNode;
}

export default function QRCode({
  value,
  size = 200,
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
