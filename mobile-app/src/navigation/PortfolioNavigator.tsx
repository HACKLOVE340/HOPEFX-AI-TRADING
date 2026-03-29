// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/PortfolioNavigator.tsx
 * ==================================
 * Stack navigator for the Portfolio tab.
 *
 *   PortfolioHome  →  Performance
 */

import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { PortfolioStackParamList } from '../types';
import { PortfolioScreen } from '../screens/PortfolioScreen';
import { PerformanceScreen } from '../screens/PerformanceScreen';
import { COLORS } from '../utils/theme';

const Stack = createNativeStackNavigator<PortfolioStackParamList>();

export function PortfolioNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: COLORS.surface },
        headerTintColor: COLORS.text,
        headerTitleStyle: { fontWeight: '700', color: COLORS.text },
        headerShadowVisible: false,
      }}
    >
      <Stack.Screen
        name="PortfolioHome"
        component={PortfolioScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Performance"
        component={PerformanceScreen}
        options={{ title: 'Performance Analytics' }}
      />
    </Stack.Navigator>
  );
}
