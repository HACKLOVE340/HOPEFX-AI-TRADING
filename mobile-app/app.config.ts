// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * app.config.ts
 * =============
 * Dynamic Expo config — overrides app.json at build time.
 *
 * Environment variables (set in EAS build profile or .env):
 *   APP_ENV          — "development" | "staging" | "production"
 *   API_BASE_URL     — backend REST base URL
 *   WS_BASE_URL      — backend WebSocket base URL
 *   SENTRY_DSN       — Sentry error tracking DSN
 */

import { ExpoConfig, ConfigContext } from 'expo/config';

const ENV = process.env.APP_ENV ?? 'development';

const API_URLS: Record<string, string> = {
  development: 'http://localhost:8000',
  staging:     'https://staging-api.hopefx.io',
  production:  'https://api.hopefx.io',
};

const WS_URLS: Record<string, string> = {
  development: 'ws://localhost:8000',
  staging:     'wss://staging-api.hopefx.io',
  production:  'wss://api.hopefx.io',
};

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: ENV === 'production' ? 'HopeFX Trading' : `HopeFX (${ENV})`,
  slug: 'hopefx-trading',
  version: '1.0.0',
  orientation: 'portrait',
  userInterfaceStyle: 'dark',
  icon: './src/assets/icon.png',
  assetBundlePatterns: ['**/*'],
  ios: {
    supportsTablet: true,
    bundleIdentifier:
      ENV === 'production' ? 'io.hopefx.trading' : `io.hopefx.trading.${ENV}`,
    buildNumber: '1',
    infoPlist: {
      NSFaceIDUsageDescription: 'Used for biometric authentication',
      NSCameraUsageDescription: 'Used for KYC document scanning',
    },
  },
  android: {
    adaptiveIcon: {
      foregroundImage: './src/assets/adaptive-icon.png',
      backgroundColor: '#0a0f1c',
    },
    package:
      ENV === 'production' ? 'io.hopefx.trading' : `io.hopefx.trading.${ENV}`,
    versionCode: 1,
    permissions: [
      'RECEIVE_BOOT_COMPLETED',
      'VIBRATE',
      'USE_BIOMETRIC',
      'USE_FINGERPRINT',
    ],
  },
  web: {
    favicon: './src/assets/favicon.png',
    bundler: 'metro',
  },
  plugins: [
    'expo-router',
    'expo-secure-store',
    [
      // SDK 55 moved the splash screen out of the top-level config into the
      // expo-splash-screen plugin.
      'expo-splash-screen',
      {
        image: './src/assets/splash.png',
        resizeMode: 'contain',
        backgroundColor: '#0a0f1c',
      },
    ],
    [
      'expo-notifications',
      {
        icon: './src/assets/notification-icon.png',
        color: '#00d4aa',
        sounds: [],
      },
    ],
  ],
  scheme: 'hopefx',
  extra: {
    eas: {
      projectId: 'hopefx-trading-app',
    },
    apiBaseUrl: process.env.API_BASE_URL ?? API_URLS[ENV] ?? API_URLS.development,
    wsBaseUrl:  process.env.WS_BASE_URL  ?? WS_URLS[ENV]  ?? WS_URLS.development,
    sentryDsn:  process.env.SENTRY_DSN   ?? '',
    appEnv:     ENV,
  },
  updates: {
    fallbackToCacheTimeout: 0,
    url: 'https://u.expo.dev/hopefx-trading-app',
  },
  runtimeVersion: {
    policy: 'appVersion',
  },
});
