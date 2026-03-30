// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/AuthNavigator.tsx
 * =============================
 * Auth stack: Login → Register → ForgotPassword → TwoFactor
 */

import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { LoginScreen }        from '../screens/auth/LoginScreen';
import { RegisterScreen }     from '../screens/auth/RegisterScreen';
import { ForgotPasswordScreen } from '../screens/auth/ForgotPasswordScreen';
import { TwoFactorScreen }    from '../screens/auth/TwoFactorScreen';
import { COLORS } from '../utils/theme';
import { AuthStackParamList } from '../types';

const Stack = createNativeStackNavigator<AuthStackParamList>();

export function AuthNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: COLORS.background },
        animation: 'slide_from_right',
      }}
    >
      <Stack.Screen name="Login"          component={LoginScreen} />
      <Stack.Screen name="Register"       component={RegisterScreen} />
      <Stack.Screen name="ForgotPassword" component={ForgotPasswordScreen} />
      <Stack.Screen name="TwoFactor"      component={TwoFactorScreen} />
    </Stack.Navigator>
  );
}
