// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/RootNavigator.tsx
 * =============================
 * Root navigator: Auth stack ↔ Main tab navigator.
 * Reads auth state from Zustand — no prop drilling.
 */

import React, { useEffect } from 'react';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useAuthStore }    from '../store/authStore';
import { AuthNavigator }   from './AuthNavigator';
import { MainTabNavigator } from './MainTabNavigator';
import { COLORS } from '../utils/theme';
import { RootStackParamList } from '../types';

const Stack = createNativeStackNavigator<RootStackParamList>();

const NAV_THEME = {
  ...DefaultTheme,
  dark: true,
  colors: {
    ...DefaultTheme.colors,
    primary:    COLORS.accent,
    background: COLORS.background,
    card:       COLORS.surface,
    text:       COLORS.text,
    border:     COLORS.border,
    notification: COLORS.sell,
  },
};

export function RootNavigator() {
  const { isAuthenticated, isLoading, hydrate } = useAuthStore();

  useEffect(() => { hydrate(); }, []);

  if (isLoading) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color={COLORS.accent} />
      </View>
    );
  }

  return (
    <NavigationContainer theme={NAV_THEME}>
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

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: COLORS.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
