// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * navigation/MoreNavigator.tsx
 * =============================
 * Stack navigator for the "More" tab — provides access to:
 * - News & Sentiment
 * - Copy Trading
 * - Strategy Builder
 * - Trade Transparency
 * - Performance
 * - Portfolio
 * - Notifications
 */
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { NewsSentimentScreen }    from '../screens/NewsSentimentScreen';
import { CopyTradingScreen }      from '../screens/CopyTradingScreen';
import { StrategyBuilderScreen }  from '../screens/StrategyBuilderScreen';
import { TransparencyScreen }     from '../screens/TransparencyScreen';
import { PerformanceScreen }      from '../screens/PerformanceScreen';
import { PortfolioScreen }        from '../screens/PortfolioScreen';
import { NotificationsScreen }    from '../screens/NotificationsScreen';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';

export type MoreStackParamList = {
  MoreHome: undefined;
  NewsSentiment: undefined;
  CopyTrading: undefined;
  StrategyBuilder: undefined;
  Transparency: undefined;
  Performance: undefined;
  Portfolio: undefined;
  Notifications: undefined;
};

const Stack = createNativeStackNavigator<MoreStackParamList>();

type MoreNav = NativeStackNavigationProp<MoreStackParamList>;

interface MenuItem {
  key: keyof MoreStackParamList;
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  description: string;
  color: string;
}

const MENU_ITEMS: MenuItem[] = [
  { key: 'NewsSentiment', icon: 'newspaper', label: 'News & Sentiment', description: 'Nuclear wordmap scoring & live news', color: COLORS.accent },
  { key: 'CopyTrading', icon: 'people', label: 'Copy Trading', description: 'Follow top traders automatically', color: '#6366f1' },
  { key: 'StrategyBuilder', icon: 'code-slash', label: 'Strategy Builder', description: 'Build & deploy trading strategies', color: '#10b981' },
  { key: 'Transparency', icon: 'eye', label: 'Trade Explain', description: 'Why every decision was made', color: '#f59e0b' },
  { key: 'Performance', icon: 'stats-chart', label: 'Performance', description: 'Detailed analytics & metrics', color: '#3b82f6' },
  { key: 'Portfolio', icon: 'pie-chart', label: 'Portfolio', description: 'Holdings & allocation overview', color: '#8b5cf6' },
  { key: 'Notifications', icon: 'notifications', label: 'Notifications', description: 'Alerts, signals & system events', color: '#ef4444' },
];

function MoreHomeScreen() {
  const navigation = useNavigation<MoreNav>();

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView showsVerticalScrollIndicator={false}>
        <View style={styles.header}>
          <Text style={styles.title}>More</Text>
          <Text style={styles.subtitle}>Additional features & tools</Text>
        </View>
        <View style={styles.menuList}>
          {MENU_ITEMS.map(item => (
            <TouchableOpacity
              key={item.key}
              style={styles.menuItem}
              onPress={() => navigation.navigate(item.key)}
              activeOpacity={0.7}
            >
              <View style={[styles.menuIcon, { backgroundColor: `${item.color}20` }]}>
                <Ionicons name={item.icon} size={22} color={item.color} />
              </View>
              <View style={styles.menuContent}>
                <Text style={styles.menuLabel}>{item.label}</Text>
                <Text style={styles.menuDesc}>{item.description}</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={COLORS.textMuted} />
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

export function MoreNavigator() {
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
        name="MoreHome"
        component={MoreHomeScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="NewsSentiment"
        component={NewsSentimentScreen}
        options={{ title: 'News & Sentiment' }}
      />
      <Stack.Screen
        name="CopyTrading"
        component={CopyTradingScreen}
        options={{ title: 'Copy Trading' }}
      />
      <Stack.Screen
        name="StrategyBuilder"
        component={StrategyBuilderScreen}
        options={{ title: 'Strategy Builder' }}
      />
      <Stack.Screen
        name="Transparency"
        component={TransparencyScreen}
        options={{ title: 'Trade Explain' }}
      />
      <Stack.Screen
        name="Performance"
        component={PerformanceScreen}
        options={{ title: 'Performance' }}
      />
      <Stack.Screen
        name="Portfolio"
        component={PortfolioScreen}
        options={{ title: 'Portfolio' }}
      />
      <Stack.Screen
        name="Notifications"
        component={NotificationsScreen}
        options={{ title: 'Notifications' }}
      />
    </Stack.Navigator>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  header: { paddingHorizontal: SPACING.lg, paddingTop: SPACING.lg, paddingBottom: SPACING.md },
  title: { ...TEXT.h1, color: COLORS.text },
  subtitle: { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  menuList: { paddingHorizontal: SPACING.lg, paddingBottom: SPACING.xl },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.lg,
    padding: SPACING.md,
    marginBottom: SPACING.sm,
    borderWidth: 1,
    borderColor: COLORS.border,
  },
  menuIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: SPACING.md,
  },
  menuContent: { flex: 1 },
  menuLabel: { ...TEXT.body, color: COLORS.text, fontWeight: '700' },
  menuDesc: { ...TEXT.captionSM, color: COLORS.textMuted, marginTop: 2 },
});
