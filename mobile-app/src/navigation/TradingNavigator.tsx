// HOPEFX-AI-TRADING — AGPL-3.0
import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { TradingStackParamList } from '../types';
import { COLORS } from '../utils/theme';
import { TradingScreen } from '../screens/trading/TradingScreen';
import { PlaceOrderScreen } from '../screens/trading/PlaceOrderScreen';
import { OrderDetailScreen } from '../screens/trading/OrderDetailScreen';
import { PositionDetailScreen } from '../screens/trading/PositionDetailScreen';

const Stack = createNativeStackNavigator<TradingStackParamList>();

export function TradingNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: COLORS.surface },
        headerTintColor: COLORS.text,
        headerTitleStyle: { fontWeight: '700', color: COLORS.text },
        headerShadowVisible: false,
        animation: 'slide_from_right',
      }}
    >
      <Stack.Screen
        name="TradingHome"
        component={TradingScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="PlaceOrder"
        component={PlaceOrderScreen}
        options={{ title: 'Place Order' }}
      />
      <Stack.Screen
        name="OrderDetail"
        component={OrderDetailScreen}
        options={{ title: 'Order Details' }}
      />
      <Stack.Screen
        name="PositionDetail"
        component={PositionDetailScreen}
        options={{ title: 'Position Details' }}
      />
    </Stack.Navigator>
  );
}
