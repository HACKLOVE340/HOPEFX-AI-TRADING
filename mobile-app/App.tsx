// HOPEFX-AI-TRADING
// Copyright (c) 2025-2026 — AGPL-3.0
/**
 * App.tsx — Root entry point for HopeFX React Native app.
 *
 * Responsibilities:
 *  - Initialise Zustand auth store from SecureStore on cold start
 *  - Register push notification handlers
 *  - Wrap the navigator tree in required providers
 *  - Gate navigation between Auth and Main stacks based on auth state
 */

import React, { useCallback, useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StyleSheet, View } from 'react-native';

import { RootNavigator } from './src/navigation/RootNavigator';
import { useAuthStore } from './src/store/authStore';
import { pushNotifications } from './src/services/pushNotifications';
import { apiClient } from './src/services/apiClient';

// Keep splash screen visible while we initialise
SplashScreen.preventAutoHideAsync();

export default function App() {
  const [appReady, setAppReady] = useState(false);
  const { hydrate, token } = useAuthStore();

  useEffect(() => {
    async function prepare() {
      try {
        // 1. Rehydrate auth token from SecureStore
        await hydrate();

        // 2. Sync axios default auth header
        if (token) {
          apiClient.setAuthToken(token);
        }

        // 3. Register for push notifications (non-blocking)
        await pushNotifications.registerForPushNotificationsAsync();
        pushNotifications.setupNotificationHandlers();
      } catch (e) {
        console.warn('[App] Prepare error:', e);
      } finally {
        setAppReady(true);
      }
    }

    prepare();
  }, [hydrate, token]);

  const onLayoutRootView = useCallback(async () => {
    if (appReady) {
      await SplashScreen.hideAsync();
    }
  }, [appReady]);

  if (!appReady) return null;

  return (
    <GestureHandlerRootView style={styles.root} onLayout={onLayoutRootView}>
      <SafeAreaProvider>
        <StatusBar style="light" backgroundColor="#0a0f1c" />
        <RootNavigator />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0a0f1c' },
});
