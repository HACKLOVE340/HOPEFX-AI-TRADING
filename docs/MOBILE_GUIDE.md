# Mobile Guide

> HOPEFX mobile access: PWA, React Native app, and mobile API.
> Last updated: 2026-07-14

---

## Subscription Requirement

Mobile access requires an active HOPEFX subscription (Starter and above).
All mobile API endpoints validate your JWT token, which is tied to your subscription.
Expired or cancelled subscriptions return `403 Subscription Required`.

---

## Access Methods

### 1. Progressive Web App (PWA)

The PWA works on any device with a modern browser. No app store required.

**Install on iOS:**
1. Open `https://your-hopefx-domain/` in Safari
2. Tap the Share button → "Add to Home Screen"
3. Launch from your home screen

**Install on Android:**
1. Open `https://your-hopefx-domain/` in Chrome
2. Tap the install prompt or Menu → "Add to Home Screen"
3. Launch from your home screen

Features: offline signal cache, push notifications, touch-optimised charts, dark mode.

### 2. React Native App (Roadmap Milestone 8)

A native iOS and Android app is planned. See [roadmap.md](roadmap.md).

### 3. Mobile API

All REST and WebSocket endpoints work from mobile. The `/api/mobile/` prefix
provides mobile-specific endpoints (push registration, device management).

---

## Authentication on Mobile

```javascript
// Login and store token securely
const response = await fetch('https://your-domain/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'user', password: 'pass' })
});
const { access_token } = await response.json();

// Store securely (never in localStorage for sensitive apps)
// React Native: use expo-secure-store
import * as SecureStore from 'expo-secure-store';
await SecureStore.setItemAsync('hopefx_token', access_token);

// Use in requests
const token = await SecureStore.getItemAsync('hopefx_token');
const signal = await fetch('https://your-domain/api/signals/latest', {
  headers: { 'Authorization': `Bearer ${token}` }
});
```

---

## Push Notifications

Push notifications require a Pro subscription or above.

### Register a Device

```bash
POST /api/mobile/register-push
Authorization: Bearer <token>
Content-Type: application/json

{
  "device_token": "fcm_token_or_apns_token",
  "platform": "android",   // or "ios"
  "device_name": "My Phone"
}
```

### Unregister

```bash
DELETE /api/mobile/register-push
Authorization: Bearer <token>
```

### Test Push

```bash
POST /api/mobile/test-push
Authorization: Bearer <token>
```

### Check Registration Status

```bash
GET /api/mobile/push-status
Authorization: Bearer <token>
```

### Notification Types

| Type | Trigger | Plan Required |
|------|---------|---------------|
| Signal alert | New BUY/SELL signal | Starter |
| Price alert | Price crosses threshold | Starter |
| Kill switch fired | Emergency stop activated | All |
| Daily P&L summary | End of trading day | Pro |
| Prop firm warning | Approaching daily loss limit | Pro |
| ML model fallback | Production model failed | Elite |

---

## PWA Configuration

The PWA manifest is at `mobile/pwa/manifest.json`:

```json
{
  "name": "HOPEFX AI Trading",
  "short_name": "HOPEFX",
  "description": "AI-Powered Trading Platform",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#131722",
  "theme_color": "#26a69a",
  "icons": [
    { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

### Offline Support

The service worker caches the last 50 signals and the current positions list.
When offline, the app shows cached data with a "Last updated: X minutes ago" banner.

```javascript
// mobile/pwa/service-worker.js
const CACHE_NAME = 'hopefx-v1';
const STATIC_CACHE = ['/', '/static/css/main.css', '/static/js/main.js'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_CACHE)));
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request))
  );
});
```

---

## React Native Integration

For the planned native app (Milestone 8), the API client pattern:

```javascript
// api/client.js
import * as SecureStore from 'expo-secure-store';

const BASE_URL = 'https://your-hopefx-domain';

export async function apiGet(path) {
  const token = await SecureStore.getItemAsync('hopefx_token');
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  if (res.status === 401) {
    // Token expired — redirect to login
    throw new Error('UNAUTHORIZED');
  }
  if (res.status === 403) {
    // Subscription required or plan limit exceeded
    throw new Error('SUBSCRIPTION_REQUIRED');
  }
  return res.json();
}

export async function apiPost(path, body) {
  const token = await SecureStore.getItemAsync('hopefx_token');
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });
  return res.json();
}
```

### Real-Time Prices via WebSocket

```javascript
// hooks/usePrices.js
import { useEffect, useState } from 'react';
import * as SecureStore from 'expo-secure-store';

export function usePrices(symbol = 'XAUUSD') {
  const [price, setPrice] = useState(null);

  useEffect(() => {
    let ws;
    (async () => {
      const token = await SecureStore.getItemAsync('hopefx_token');
      ws = new WebSocket(`wss://your-domain/ws/prices?token=${token}`);
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.symbol === symbol) setPrice(data);
      };
    })();
    return () => ws?.close();
  }, [symbol]);

  return price;
}
```

### Signal Feed Component

```javascript
// components/SignalCard.js
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

export function SignalCard({ signal }) {
  const isBuy = signal.direction === 'BUY';
  return (
    <View style={styles.card}>
      <Text style={styles.symbol}>{signal.symbol}</Text>
      <Text style={[styles.direction, isBuy ? styles.buy : styles.sell]}>
        {signal.direction}
      </Text>
      <Text style={styles.confidence}>
        Confidence: {(signal.confidence * 100).toFixed(0)}%
      </Text>
      <Text style={styles.rr}>R/R: {signal.risk_reward.toFixed(1)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: '#1e222d', padding: 16, borderRadius: 8, marginBottom: 8 },
  symbol: { color: '#d1d4dc', fontSize: 16, fontWeight: 'bold' },
  direction: { fontSize: 24, fontWeight: 'bold', marginVertical: 4 },
  buy: { color: '#26a69a' },
  sell: { color: '#ef5350' },
  confidence: { color: '#787b86', fontSize: 14 },
  rr: { color: '#787b86', fontSize: 14 },
});
```

---

## Biometric Authentication

```javascript
import * as LocalAuthentication from 'expo-local-authentication';

export async function authenticateWithBiometrics() {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const isEnrolled = await LocalAuthentication.isEnrolledAsync();

  if (!hasHardware || !isEnrolled) return false;

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: 'Authenticate to access HOPEFX',
    fallbackLabel: 'Use PIN',
  });
  return result.success;
}
```

---

## CORS for Mobile

If your mobile app is hosted on a different domain, add it to the CORS allowlist:

```bash
MOBILE_CORS_ORIGINS=https://app.yourdomain.com,https://mobile.yourdomain.com
```

---

## App Store Deployment (Milestone 8)

### iOS App Store
1. Configure signing in Xcode with your Apple Developer account
2. Build release: `eas build --platform ios --profile production`
3. Upload to App Store Connect: `eas submit --platform ios`
4. Submit for review (typically 1–3 days)

### Google Play Store
1. Generate signed AAB: `eas build --platform android --profile production`
2. Upload to Play Console
3. Submit for review (typically 1–3 days)

### PWA Deployment
Ensure your server has:
- HTTPS with valid TLS certificate
- `Content-Security-Policy` header set
- Service worker served from root scope
- `manifest.json` linked in `<head>`

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Push notifications not arriving | Check `GET /api/mobile/push-status` — device may not be registered |
| `403 Subscription Required` | Your subscription has expired — renew at `/api/monetization/pricing` |
| PWA not installable | Must be served over HTTPS with a valid manifest.json |
| WebSocket disconnects | Implement reconnect with exponential backoff (see `usePrices` hook above) |
| Biometrics not working | Check `LocalAuthentication.hasHardwareAsync()` — not all devices support it |

---

*Last updated: 2026-07-14*
