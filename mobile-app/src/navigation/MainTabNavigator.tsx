// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/MainTabNavigator.tsx
 * ================================
 * Animated bottom tab navigator with institutional dark styling.
 * Tabs: Dashboard | Trading | Risk | Signals | Settings
 */

import React from 'react';
import { View, Text, StyleSheet, Platform } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';
import Animated, {
  useSharedValue, useAnimatedStyle, withSpring,
} from 'react-native-reanimated';

import { DashboardScreen }  from '../screens/DashboardScreen';
import { SignalsScreen }    from '../screens/SignalsScreen';
import { RiskScreen }       from '../screens/risk/RiskScreen';
import { SettingsNavigator } from './SettingsNavigator';
import { TradingNavigator } from './TradingNavigator';
import { MoreNavigator } from './MoreNavigator';

import { useTradingStore }  from '../store/tradingStore';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';
import { MainTabParamList } from '../types';

const Tab = createBottomTabNavigator<MainTabParamList>();

type TabIconName = keyof typeof Ionicons.glyphMap;

const TAB_CONFIG: Record<keyof MainTabParamList, { icon: TabIconName; activeIcon: TabIconName; label: string }> = {
  Dashboard: { icon: 'grid-outline',       activeIcon: 'grid',            label: 'Dashboard' },
  Trading:   { icon: 'swap-horizontal-outline', activeIcon: 'swap-horizontal', label: 'Trade' },
  Risk:      { icon: 'shield-outline',     activeIcon: 'shield',          label: 'Risk' },
  Signals:   { icon: 'pulse-outline',      activeIcon: 'pulse',           label: 'Signals' },
  More:      { icon: 'apps-outline',       activeIcon: 'apps',            label: 'More' },
  Settings:  { icon: 'settings-outline',   activeIcon: 'settings',        label: 'Settings' },
};

function TabIcon({
  name, focused, color, badgeCount,
}: { name: keyof MainTabParamList; focused: boolean; color: string; badgeCount?: number }) {
  const cfg = TAB_CONFIG[name];
  const scale = useSharedValue(1);

  const animStyle = useAnimatedStyle(() => ({
    transform: [{ scale: withSpring(focused ? 1.15 : 1, { damping: 12, stiffness: 200 }) }],
  }));

  return (
    <Animated.View style={[tabIconStyles.wrap, animStyle]}>
      <Ionicons
        name={focused ? cfg.activeIcon : cfg.icon}
        size={22}
        color={color}
      />
      {badgeCount != null && badgeCount > 0 && (
        <View style={tabIconStyles.badge}>
          <Text style={tabIconStyles.badgeText}>
            {badgeCount > 9 ? '9+' : String(badgeCount)}
          </Text>
        </View>
      )}
    </Animated.View>
  );
}

const tabIconStyles = StyleSheet.create({
  wrap:      { alignItems: 'center', justifyContent: 'center' },
  badge:     {
    position: 'absolute', top: -4, right: -8,
    minWidth: 16, height: 16, borderRadius: 8,
    backgroundColor: COLORS.sell,
    alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 3,
    borderWidth: 1.5, borderColor: COLORS.surface,
  },
  badgeText: { color: COLORS.white, fontSize: 9, fontWeight: '800' },
});

export function MainTabNavigator() {
  const { signals, riskMetrics } = useTradingStore();

  const activeSignals = signals.filter(
    (s) => !s.approved && new Date(s.expires_at) > new Date()
  ).length;

  const riskAlert = riskMetrics?.kill_switch_active ||
                    (riskMetrics?.risk_utilization ?? 0) > 0.85;

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: styles.tabBar,
        tabBarActiveTintColor: COLORS.accent,
        tabBarInactiveTintColor: COLORS.textMuted,
        tabBarLabelStyle: styles.tabLabel,
        tabBarItemStyle: styles.tabItem,
        tabBarBackground: () => <View style={styles.tabBarBg} />,
        tabBarIcon: ({ focused, color }) => (
          <TabIcon
            name={route.name as keyof MainTabParamList}
            focused={focused}
            color={color}
            badgeCount={
              route.name === 'Signals' ? activeSignals :
              route.name === 'Risk' && riskAlert ? 1 : undefined
            }
          />
        ),
      })}
    >
      <Tab.Screen
        name="Dashboard"
        component={DashboardScreen}
        options={{ title: 'Dashboard' }}
      />
      <Tab.Screen
        name="Trading"
        component={TradingNavigator}
        options={{ title: 'Trade' }}
      />
      <Tab.Screen
        name="Risk"
        component={RiskScreen}
        options={{ title: 'Risk' }}
      />
      <Tab.Screen
        name="Signals"
        component={SignalsScreen}
        options={{ title: 'Signals' }}
      />
      <Tab.Screen
        name="More"
        component={MoreNavigator}
        options={{ title: 'More' }}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsNavigator}
        options={{ title: 'Settings' }}
      />
    </Tab.Navigator>
  );
}

const styles = StyleSheet.create({
  tabBar: {
    backgroundColor: 'transparent',
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
    height: Platform.OS === 'ios' ? 84 : 64,
    paddingBottom: Platform.OS === 'ios' ? 24 : 8,
    paddingTop: 8,
    elevation: 0,
  },
  tabBarBg: {
    flex: 1,
    backgroundColor: COLORS.surface,
  },
  tabLabel: {
    ...TEXT.captionSM,
    fontSize: 10,
    fontWeight: '600',
    marginTop: 2,
  },
  tabItem: {
    paddingVertical: 4,
  },
});
