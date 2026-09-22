# HopeFX Mobile App

React Native (Expo) mobile trading app for the HopeFX AI Trading platform.

## Stack

- **Expo SDK 55** — managed workflow
- **React Navigation 7** — stack + bottom tabs
- **Zustand 4** — auth + trading state
- **Axios** — HTTP client with JWT refresh
- **expo-notifications** — push notifications (iOS + Android)
- **expo-secure-store** — encrypted token storage

## Structure

```
mobile-app/
├── App.tsx                    # Root entry — hydration, push init, navigator
├── src/
│   ├── navigation/
│   │   ├── RootNavigator.tsx  # Auth vs Main gate
│   │   ├── AuthNavigator.tsx  # Login, Register, ForgotPassword, 2FA
│   │   ├── MainTabNavigator.tsx
│   │   └── TradingNavigator.tsx
│   ├── screens/
│   │   ├── auth/              # LoginScreen, RegisterScreen, ForgotPasswordScreen, TwoFactorScreen
│   │   ├── trading/           # TradingScreen, PlaceOrderScreen, OrderDetailScreen, PositionDetailScreen
│   │   ├── settings/          # SettingsScreen
│   │   ├── DashboardScreen.tsx
│   │   ├── PortfolioScreen.tsx
│   │   └── SignalsScreen.tsx
│   ├── store/
│   │   ├── authStore.ts       # JWT tokens, user profile, SecureStore persistence
│   │   └── tradingStore.ts    # Prices, positions, orders, signals
│   ├── services/
│   │   ├── apiClient.ts       # Axios + auto token refresh
│   │   ├── wsClient.ts        # WebSocket /ws/live with reconnect
│   │   └── pushNotifications.ts
│   ├── components/            # Button, Card, PriceTag, SignalBadge, ErrorBanner, LoadingSpinner
│   ├── hooks/                 # useLivePrice, useRefreshOnFocus
│   ├── utils/                 # theme.ts, formatters.ts
│   └── types/index.ts
```

## Backend Connection

The app connects to the HopeFX FastAPI backend:

| Feature | Endpoint |
|---------|----------|
| Auth | `POST /api/auth/login` |
| Live prices | `GET /api/trading/price/:symbol` |
| WebSocket | `wss://api.hopefx.io/ws/live?token=JWT` |
| Place order | `POST /api/trading/order` |
| Signals | `GET /api/signals/latest` |
| Push tokens | `POST /api/mobile/push-token` |
| Notification prefs | `GET/PATCH /api/mobile/notification-prefs` |

## Development

```bash
cd mobile-app
npm install
npx expo start
```

Scan the QR code with Expo Go (iOS/Android) or press `a` for Android emulator.

## Production Build

```bash
npm install -g eas-cli
eas build --platform android --profile production
eas build --platform ios --profile production
```

## Environment

Set `apiBaseUrl` and `wsBaseUrl` in `app.json` under `expo.extra`, or override via EAS build environment variables.
