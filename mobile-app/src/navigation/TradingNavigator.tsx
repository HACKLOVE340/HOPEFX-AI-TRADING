// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/TradingNavigator.tsx
 * ================================
 * Native stack for the Trading tab.
 */

import React from 'react';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { TradingScreen }        from '../screens/trading/TradingScreen';
import { PlaceOrderScreen }     from '../screens/trading/PlaceOrderScreen';
import { OrderDetailScreen }    from '../screens/trading/OrderDetailScreen';
import { PositionDetailScreen } from '../screens/trading/PositionDetailScreen';
import { OrdersScreen }         from '../screens/trading/OrdersScreen';
import { WatchlistScreen }      from '../screens/WatchlistScreen';
import { COLORS } from '../utils/theme';
import { TradingStackParamList } from '../types';

const Stack = createNativeStackNavigator<TradingStackParamList>();

export function TradingNavigator() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: COLORS.surface },
        headerTintColor: COLORS.text,
        headerTitleStyle: { fontWeight: '700', fontSize: 17 },
        headerShadowVisible: false,
        contentStyle: { backgroundColor: COLORS.background },
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
        options={{ title: 'Place Order', presentation: 'modal' }}
      />
      <Stack.Screen
        name="OrderDetail"
        component={OrderDetailScreen}
        options={{ title: 'Order Detail' }}
      />
      <Stack.Screen
        name="PositionDetail"
        component={PositionDetailScreen}
        options={{ title: 'Position Detail' }}
      />
      <Stack.Screen
        name="Orders"
        component={OrdersScreen}
        options={{ title: 'Order History' }}
      />
      <Stack.Screen
        name="Watchlist"
        component={WatchlistScreen}
        options={{ title: 'Watchlist' }}
      />
    </Stack.Navigator>
  );
}
