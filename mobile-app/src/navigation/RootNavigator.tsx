// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/RootNavigator.tsx
 * ============================
 * Root navigation tree.
 *
 * Structure:
 *   RootStack
 *   ├── AuthStack  (Login, Register, ForgotPassword, TwoFactor)
 *   └── MainTabs   (Dashboard, Trading, Portfolio, Signals, Settings)
 *       └── TradingStack (TradingHome, PlaceOrder, OrderDetail, PositionDetail)
 */

import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAuthStore } from '../store/authStore';
import { AuthNavigator } from './AuthNavigator';
import { MainTabNavigator } from './MainTabNavigator';
import { RootStackParamList } from '../types';
import { COLORS } from '../utils/theme';

const Stack = createNativeStackNavigator<RootStackParamList>();

export function RootNavigator() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  return (
    <NavigationContainer
      theme={{
        dark: true,
        colors: {
          primary: COLORS.accent,
          background: COLORS.background,
          card: COLORS.surface,
          text: COLORS.text,
          border: COLORS.border,
          notification: COLORS.accent,
        },
      }}
    >
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        {isAuthenticated ? (
          <Stack.Screen name="Main" component={MainTabNavigator} />
        ) : (
          <Stack.Screen name="Auth" component={AuthNavigator} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
