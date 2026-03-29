// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/SettingsNavigator.tsx
 * =================================
 * Stack navigator for the Settings tab.
 *
 *   SettingsHome  →  Notifications
 *                →  Alerts
 */

import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SettingsStackParamList } from '../types';
import { SettingsScreen } from '../screens/settings/SettingsScreen';
import { NotificationsScreen } from '../screens/NotificationsScreen';
import { AlertsScreen } from '../screens/AlertsScreen';
import { COLORS } from '../utils/theme';

const Stack = createNativeStackNavigator<SettingsStackParamList>();

export function SettingsNavigator() {
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
        name="SettingsHome"
        component={SettingsScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="Notifications"
        component={NotificationsScreen}
        options={{ title: 'Notifications' }}
      />
      <Stack.Screen
        name="Alerts"
        component={AlertsScreen}
        options={{ title: 'Price Alerts' }}
      />
    </Stack.Navigator>
  );
}
