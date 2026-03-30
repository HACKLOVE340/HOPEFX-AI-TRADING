// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * App.tsx — Root entry point for HopeFX React Native app.
 *
 * Responsibilities:
 *  - Gesture handler root (required by react-native-gesture-handler)
 *  - Safe area provider
 *  - Root navigator (auth ↔ main tab)
 *  - Push notification setup
 *  - App state listener for offline cache flush
 */

import 'react-native-gesture-handler';
import React, { useEffect, useRef } from 'react';
import { AppState, AppStateStatus, LogBox } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

import { RootNavigator }    from './src/navigation/RootNavigator';
import { pushNotifications } from './src/services/pushNotifications';
import { offlineCache }     from './src/services/offlineCache';
import { useTradingStore }  from './src/store/tradingStore';

// Suppress known non-critical warnings in dev
LogBox.ignoreLogs([
  'Non-serializable values were found in the navigation state',
  'Sending `onAnimatedValueUpdate`',
]);

export default function App() {
  const appState = useRef<AppStateStatus>(AppState.currentState);

  useEffect(() => {
    // Register for push notifications
    pushNotifications.register().catch(console.warn);

    // Flush offline cache when app goes to background
    const sub = AppState.addEventListener('change', (nextState) => {
      if (
        appState.current.match(/active/) &&
        nextState.match(/inactive|background/)
      ) {
        const state = useTradingStore.getState();
        offlineCache.flush().catch(console.warn);
      }
      appState.current = nextState;
    });

    return () => sub.remove();
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StatusBar style="light" backgroundColor="transparent" translucent />
        <RootNavigator />
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
