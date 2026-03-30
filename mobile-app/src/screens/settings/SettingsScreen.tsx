// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/settings/SettingsScreen.tsx
 * =====================================
 * Full settings screen: biometrics, notifications, connection,
 * account info, and danger zone.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Switch,
  TouchableOpacity, Alert, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';

import { useAuthStore }    from '../../store/authStore';
import { useTradingStore } from '../../store/tradingStore';
import { apiClient }       from '../../services/apiClient';
import { biometricAuth }   from '../../services/biometricAuth';
import { wsClient }        from '../../services/wsClient';
import { Card }            from '../../components/Card';
import { ConnectionStatus } from '../../components/ConnectionStatus';

import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../../utils/theme';
import { NotificationPrefs } from '../../types';

const DEFAULT_PREFS: NotificationPrefs = {
  signals: true,
  trade_fills: true,
  price_alerts: true,
  daily_summary: true,
  risk_warnings: true,
  kill_switch: true,
  news_impact: false,
};

export function SettingsScreen() {
  const { user, logout, biometricAvailable, biometricEnabled,
          enableBiometric, disableBiometric } = useAuthStore();
  const { wsStatus, account } = useTradingStore();

  const [prefs, setPrefs]           = useState<NotificationPrefs>(DEFAULT_PREFS);
  const [saving, setSaving]         = useState(false);
  const [biometricLoading, setBiometricLoading] = useState(false);
  const [capability, setCapability] = useState<Awaited<ReturnType<typeof biometricAuth.getCapability>> | null>(null);

  useEffect(() => {
    apiClient.getNotificationPrefs().then(setPrefs).catch(() => {});
    biometricAuth.getCapability().then(setCapability);
  }, []);

  const togglePref = async (key: keyof NotificationPrefs) => {
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    setSaving(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    try {
      await apiClient.updateNotificationPrefs({ [key]: updated[key] });
    } catch {
      setPrefs(prefs);
    } finally {
      setSaving(false);
    }
  };

  const handleBiometricToggle = async () => {
    setBiometricLoading(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    if (biometricEnabled) {
      await disableBiometric();
    } else {
      const result = await enableBiometric();
      if (!result.success) {
        Alert.alert('Biometric Setup Failed', result.error ?? 'Unknown error');
      }
    }
    setBiometricLoading(false);
  };

  const handleLogout = () => {
    Alert.alert(
      'Sign Out',
      'Are you sure you want to sign out?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign Out',
          style: 'destructive',
          onPress: () => {
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
            logout();
          },
        },
      ]
    );
  };

  const biometricTypeName = capability?.primaryType === 'facial' ? 'Face ID' :
                            capability?.primaryType === 'iris'    ? 'Iris Scan' : 'Fingerprint';

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.pageTitle}>Settings</Text>

        {/* ── Account ── */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>ACCOUNT</Text>
          <Card style={styles.card}>
            <View style={styles.accountRow}>
              <View style={styles.avatarRing}>
                <Text style={styles.avatarText}>
                  {(user?.username ?? 'T')[0].toUpperCase()}
                </Text>
              </View>
              <View style={styles.accountInfo}>
                <Text style={styles.accountName}>{user?.username ?? '—'}</Text>
                <Text style={styles.accountEmail}>{user?.email ?? '—'}</Text>
                <View style={styles.accountBadges}>
                  <View style={[styles.badge, { backgroundColor: COLORS.accentGlow, borderColor: COLORS.borderAccent }]}>
                    <Text style={[styles.badgeText, { color: COLORS.accent }]}>
                      {user?.role?.toUpperCase() ?? 'USER'}
                    </Text>
                  </View>
                  {account?.account_type && (
                    <View style={[styles.badge, {
                      backgroundColor: account.account_type === 'live' ? COLORS.profitDim : COLORS.infoDim,
                      borderColor: account.account_type === 'live' ? COLORS.profit + '44' : COLORS.info + '44',
                    }]}>
                      <Text style={[styles.badgeText, {
                        color: account.account_type === 'live' ? COLORS.profit : COLORS.info,
                      }]}>
                        {account.account_type.toUpperCase()}
                      </Text>
                    </View>
                  )}
                </View>
              </View>
            </View>
          </Card>
        </View>

        {/* ── Connection ── */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>CONNECTION</Text>
          <Card style={styles.card}>
            <SettingRow
              icon="wifi"
              label="WebSocket Status"
              right={<ConnectionStatus status={wsStatus} reconnectAttempts={wsClient.reconnectAttempts} />}
            />
            <Divider />
            <SettingRow
              icon="server-outline"
              label="API Endpoint"
              value="api.hopefx.io"
            />
            <Divider />
            <SettingRow
              icon="flash-outline"
              label="Latency Mode"
              value="Low latency"
            />
          </Card>
        </View>

        {/* ── Security ── */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>SECURITY</Text>
          <Card style={styles.card}>
            {biometricAvailable ? (
              <>
                <SettingRow
                  icon={capability?.primaryType === 'facial' ? 'scan-outline' : 'finger-print'}
                  label={`${biometricTypeName} Login`}
                  sublabel={biometricEnabled ? 'Tap to disable' : 'Tap to enable fast sign-in'}
                  right={
                    biometricLoading ? (
                      <ActivityIndicator size="small" color={COLORS.accent} />
                    ) : (
                      <Switch
                        value={biometricEnabled}
                        onValueChange={handleBiometricToggle}
                        trackColor={{ false: COLORS.border, true: COLORS.accent }}
                        thumbColor={biometricEnabled ? COLORS.white : COLORS.textMuted}
                      />
                    )
                  }
                />
                <Divider />
              </>
            ) : null}
            <SettingRow
              icon="shield-checkmark-outline"
              label="Two-Factor Auth"
              value={user?.two_factor_enabled ? 'Enabled' : 'Disabled'}
              valueColor={user?.two_factor_enabled ? COLORS.profit : COLORS.warning}
            />
            <Divider />
            <SettingRow
              icon="key-outline"
              label="Session Encryption"
              value="AES-256"
              valueColor={COLORS.profit}
            />
          </Card>
        </View>

        {/* ── Notifications ── */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>NOTIFICATIONS</Text>
          <Card style={styles.card}>
            {(Object.keys(DEFAULT_PREFS) as (keyof NotificationPrefs)[]).map((key, idx, arr) => (
              <React.Fragment key={key}>
                <SettingRow
                  icon={notifIcon(key)}
                  label={notifLabel(key)}
                  sublabel={notifSublabel(key)}
                  right={
                    <Switch
                      value={prefs[key]}
                      onValueChange={() => togglePref(key)}
                      trackColor={{ false: COLORS.border, true: COLORS.accent }}
                      thumbColor={prefs[key] ? COLORS.white : COLORS.textMuted}
                      disabled={saving}
                    />
                  }
                />
                {idx < arr.length - 1 && <Divider />}
              </React.Fragment>
            ))}
          </Card>
        </View>

        {/* ── App info ── */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>APP</Text>
          <Card style={styles.card}>
            <SettingRow icon="information-circle-outline" label="Version" value="2.0.0" />
            <Divider />
            <SettingRow icon="document-text-outline" label="License" value="AGPL-3.0" />
            <Divider />
            <SettingRow icon="code-slash-outline" label="Build" value="Production" valueColor={COLORS.profit} />
          </Card>
        </View>

        {/* ── Danger zone ── */}
        <View style={styles.section}>
          <Text style={[styles.sectionLabel, { color: COLORS.danger }]}>DANGER ZONE</Text>
          <Card style={[styles.card, styles.dangerCard]}>
            <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout} activeOpacity={0.8}>
              <Ionicons name="log-out-outline" size={20} color={COLORS.loss} />
              <Text style={styles.logoutText}>Sign Out</Text>
            </TouchableOpacity>
          </Card>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SettingRow({
  icon, label, sublabel, value, valueColor, right,
}: {
  icon: string;
  label: string;
  sublabel?: string;
  value?: string;
  valueColor?: string;
  right?: React.ReactNode;
}) {
  return (
    <View style={rowStyles.row}>
      <View style={rowStyles.iconWrap}>
        <Ionicons name={icon as any} size={18} color={COLORS.accent} />
      </View>
      <View style={rowStyles.labelWrap}>
        <Text style={rowStyles.label}>{label}</Text>
        {sublabel && <Text style={rowStyles.sublabel}>{sublabel}</Text>}
      </View>
      {right ?? (value ? (
        <Text style={[rowStyles.value, valueColor ? { color: valueColor } : {}]}>{value}</Text>
      ) : null)}
    </View>
  );
}

function Divider() {
  return <View style={{ height: 1, backgroundColor: COLORS.border, marginVertical: 2 }} />;
}

const rowStyles = StyleSheet.create({
  row:       { flexDirection: 'row', alignItems: 'center', paddingVertical: SPACING.sm, gap: SPACING.sm },
  iconWrap:  { width: 32, height: 32, borderRadius: RADIUS.sm, backgroundColor: COLORS.accentGlow, alignItems: 'center', justifyContent: 'center' },
  labelWrap: { flex: 1 },
  label:     { ...TEXT.body, color: COLORS.text },
  sublabel:  { ...TEXT.caption, color: COLORS.textMuted, marginTop: 2 },
  value:     { ...TEXT.bodySM, color: COLORS.textSecondary },
});

function notifIcon(key: keyof NotificationPrefs): string {
  const map: Record<keyof NotificationPrefs, string> = {
    signals:      'pulse-outline',
    trade_fills:  'checkmark-circle-outline',
    price_alerts: 'trending-up-outline',
    daily_summary:'bar-chart-outline',
    risk_warnings:'warning-outline',
    kill_switch:  'stop-circle-outline',
    news_impact:  'newspaper-outline',
  };
  return map[key] ?? 'notifications-outline';
}

function notifLabel(key: keyof NotificationPrefs): string {
  const map: Record<keyof NotificationPrefs, string> = {
    signals:      'AI Signals',
    trade_fills:  'Trade Fills',
    price_alerts: 'Price Alerts',
    daily_summary:'Daily Summary',
    risk_warnings:'Risk Warnings',
    kill_switch:  'Kill Switch Alerts',
    news_impact:  'High-Impact News',
  };
  return map[key] ?? key;
}

function notifSublabel(key: keyof NotificationPrefs): string {
  const map: Record<keyof NotificationPrefs, string> = {
    signals:      'New AI-generated trading signals',
    trade_fills:  'Order execution confirmations',
    price_alerts: 'Custom price level alerts',
    daily_summary:'End-of-day P&L summary',
    risk_warnings:'Risk limit breach warnings',
    kill_switch:  'Emergency trading halt notifications',
    news_impact:  'High-impact macro news events',
  };
  return map[key] ?? '';
}

const styles = StyleSheet.create({
  safe:         { flex: 1, backgroundColor: COLORS.background },
  content:      { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xxl },
  pageTitle:    { ...TEXT.h1, color: COLORS.text },
  section:      { gap: SPACING.sm },
  sectionLabel: { ...TEXT.label, color: COLORS.textMuted, paddingHorizontal: SPACING.xs },
  card:         { gap: 0 },
  accountRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  avatarRing:   {
    width: 52, height: 52, borderRadius: 26,
    borderWidth: 2, borderColor: COLORS.accent,
    backgroundColor: COLORS.accentGlow,
    alignItems: 'center', justifyContent: 'center',
  },
  avatarText:   { ...TEXT.h2, color: COLORS.accent },
  accountInfo:  { flex: 1, gap: 4 },
  accountName:  { ...TEXT.h4, color: COLORS.text },
  accountEmail: { ...TEXT.bodySM, color: COLORS.textMuted },
  accountBadges:{ flexDirection: 'row', gap: SPACING.xs, marginTop: 4 },
  badge:        { paddingHorizontal: SPACING.sm, paddingVertical: 2, borderRadius: RADIUS.sm, borderWidth: 1 },
  badgeText:    { ...TEXT.captionSM, fontWeight: '700' },
  dangerCard:   { borderColor: COLORS.danger + '33' },
  logoutBtn:    { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.sm },
  logoutText:   { ...TEXT.body, color: COLORS.loss, fontWeight: '600' },
});
