// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/NotificationsScreen.tsx
 * ================================
 * Push notification preferences and in-app notification history.
 */

import React from 'react';
import {
  View, Text, StyleSheet, ScrollView, Switch,
  TouchableOpacity, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useNotifications } from '../hooks/useNotifications';
import { Card } from '../components/Card';
import { ErrorBanner } from '../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import { NotificationPrefs } from '../types';

const PREF_CONFIG: {
  key: keyof NotificationPrefs;
  label: string;
  description: string;
  icon: string;
}[] = [
  {
    key: 'signals',
    label: 'AI Trading Signals',
    description: 'New buy/sell signals from the ML engine',
    icon: 'flash-outline',
  },
  {
    key: 'trade_fills',
    label: 'Order Fills',
    description: 'Confirmation when orders are executed',
    icon: 'checkmark-circle-outline',
  },
  {
    key: 'price_alerts',
    label: 'Price Alerts',
    description: 'When price crosses your alert levels',
    icon: 'notifications-outline',
  },
  {
    key: 'daily_summary',
    label: 'Daily P&L Summary',
    description: 'End-of-day performance report at 22:00 UTC',
    icon: 'bar-chart-outline',
  },
  {
    key: 'risk_warnings',
    label: 'Risk Warnings',
    description: 'Drawdown limits, margin calls, circuit breakers',
    icon: 'warning-outline',
  },
];

export function NotificationsScreen() {
  const {
    prefs,
    pushEnabled,
    saving,
    error,
    togglePref,
    requestPushPermission,
    sendTestNotification,
  } = useNotifications();

  const handleRequestPermission = async () => {
    const granted = await requestPushPermission();
    if (!granted) {
      Alert.alert(
        'Permission Required',
        'Enable notifications in your device Settings to receive trading alerts.',
        [{ text: 'OK' }]
      );
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.pageTitle}>Notifications</Text>

        {error && <ErrorBanner message={error} />}

        {/* Push permission banner */}
        {!pushEnabled && (
          <TouchableOpacity style={styles.permissionBanner} onPress={handleRequestPermission}>
            <Ionicons name="notifications-off-outline" size={20} color={COLORS.warning} />
            <View style={styles.permissionText}>
              <Text style={styles.permissionTitle}>Push notifications disabled</Text>
              <Text style={styles.permissionSub}>Tap to enable trading alerts</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={COLORS.warning} />
          </TouchableOpacity>
        )}

        {/* Preferences */}
        <Text style={styles.sectionTitle}>Alert Preferences</Text>
        <Card style={styles.prefsCard}>
          {PREF_CONFIG.map((cfg, i) => (
            <View
              key={cfg.key}
              style={[
                styles.prefRow,
                i < PREF_CONFIG.length - 1 && styles.prefRowBorder,
              ]}
            >
              <View style={styles.prefIcon}>
                <Ionicons name={cfg.icon as any} size={18} color={COLORS.accent} />
              </View>
              <View style={styles.prefInfo}>
                <Text style={styles.prefLabel}>{cfg.label}</Text>
                <Text style={styles.prefDesc}>{cfg.description}</Text>
              </View>
              <Switch
                value={prefs[cfg.key]}
                onValueChange={() => togglePref(cfg.key)}
                trackColor={{ false: COLORS.border, true: COLORS.accent }}
                thumbColor={COLORS.white}
                disabled={saving || !pushEnabled}
              />
            </View>
          ))}
        </Card>

        {/* Test notification */}
        <TouchableOpacity
          style={[styles.testBtn, !pushEnabled && styles.testBtnDisabled]}
          onPress={sendTestNotification}
          disabled={!pushEnabled}
        >
          <Ionicons name="send-outline" size={16} color={pushEnabled ? COLORS.accent : COLORS.textMuted} />
          <Text style={[styles.testBtnText, !pushEnabled && styles.testBtnTextDisabled]}>
            Send Test Notification
          </Text>
        </TouchableOpacity>

        {/* Info */}
        <Card style={styles.infoCard}>
          <View style={styles.infoRow}>
            <Ionicons name="information-circle-outline" size={16} color={COLORS.textMuted} />
            <Text style={styles.infoText}>
              Notifications are sent via Expo Push Service. Signal alerts are
              delivered within 5 seconds of generation. Daily summaries are
              sent at 22:00 UTC.
            </Text>
          </View>
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:                { flex: 1, backgroundColor: COLORS.background },
  content:             { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  pageTitle:           { color: COLORS.text, fontSize: 24, fontWeight: '800' },
  permissionBanner:    { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, backgroundColor: COLORS.warning + '22', borderRadius: RADIUS.md, padding: SPACING.md, borderWidth: 1, borderColor: COLORS.warning + '55' },
  permissionText:      { flex: 1 },
  permissionTitle:     { color: COLORS.warning, fontSize: 14, fontWeight: '700' },
  permissionSub:       { color: COLORS.warning, fontSize: 12, opacity: 0.8, marginTop: 2 },
  sectionTitle:        { color: COLORS.text, fontSize: 16, fontWeight: '700' },
  prefsCard:           { gap: 0 },
  prefRow:             { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.md },
  prefRowBorder:       { borderBottomWidth: 1, borderBottomColor: COLORS.border },
  prefIcon:            { width: 36, height: 36, borderRadius: RADIUS.sm, backgroundColor: COLORS.accent + '22', alignItems: 'center', justifyContent: 'center' },
  prefInfo:            { flex: 1 },
  prefLabel:           { color: COLORS.text, fontSize: 14, fontWeight: '600' },
  prefDesc:            { color: COLORS.textMuted, fontSize: 12, marginTop: 2 },
  testBtn:             { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACING.sm, padding: SPACING.md, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.accent },
  testBtnDisabled:     { borderColor: COLORS.border },
  testBtnText:         { color: COLORS.accent, fontSize: 14, fontWeight: '600' },
  testBtnTextDisabled: { color: COLORS.textMuted },
  infoCard:            { backgroundColor: COLORS.surfaceAlt },
  infoRow:             { flexDirection: 'row', gap: SPACING.sm, alignItems: 'flex-start' },
  infoText:            { flex: 1, color: COLORS.textMuted, fontSize: 12, lineHeight: 18 },
});
