// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Switch,
  TouchableOpacity, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuthStore } from '../../store/authStore';
import { apiClient } from '../../services/apiClient';
import { pushNotifications } from '../../services/pushNotifications';
import { Card } from '../../components/Card';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';
import { NotificationPrefs } from '../../types';

const DEFAULT_PREFS: NotificationPrefs = {
  signals: true,
  trade_fills: true,
  price_alerts: true,
  daily_summary: true,
  risk_warnings: true,
};

export function SettingsScreen() {
  const { user, logout } = useAuthStore();
  const [prefs, setPrefs] = useState<NotificationPrefs>(DEFAULT_PREFS);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient.getNotificationPrefs()
      .then(setPrefs)
      .catch(() => { /* use defaults */ });
  }, []);

  const togglePref = async (key: keyof NotificationPrefs) => {
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    setSaving(true);
    try {
      await apiClient.updateNotificationPrefs({ [key]: updated[key] });
    } catch {
      setPrefs(prefs); // revert on failure
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = () => {
    Alert.alert('Sign Out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign Out', style: 'destructive', onPress: logout },
    ]);
  };

  const handleTestNotification = async () => {
    await pushNotifications.scheduleLocalNotification(
      'HopeFX Test',
      'Push notifications are working correctly.',
      { type: 'test' }
    );
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.pageTitle}>Settings</Text>

        {/* Profile */}
        <Card style={styles.profileCard}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>
              {user?.username?.[0]?.toUpperCase() ?? 'T'}
            </Text>
          </View>
          <View>
            <Text style={styles.profileName}>{user?.username ?? 'Trader'}</Text>
            <Text style={styles.profileEmail}>{user?.email ?? ''}</Text>
            <View style={styles.roleBadge}>
              <Text style={styles.roleText}>{user?.role?.toUpperCase() ?? 'USER'}</Text>
            </View>
          </View>
        </Card>

        {/* Notifications */}
        <Text style={styles.sectionTitle}>Push Notifications</Text>
        <Card style={styles.prefsCard}>
          {(Object.keys(DEFAULT_PREFS) as (keyof NotificationPrefs)[]).map((key) => (
            <View key={key} style={styles.prefRow}>
              <Text style={styles.prefLabel}>{PREF_LABELS[key]}</Text>
              <Switch
                value={prefs[key]}
                onValueChange={() => togglePref(key)}
                trackColor={{ false: COLORS.border, true: COLORS.accent }}
                thumbColor={COLORS.white}
                disabled={saving}
              />
            </View>
          ))}
        </Card>

        <TouchableOpacity style={styles.testBtn} onPress={handleTestNotification}>
          <Ionicons name="notifications-outline" size={16} color={COLORS.accent} />
          <Text style={styles.testBtnText}>Send Test Notification</Text>
        </TouchableOpacity>

        {/* Account */}
        <Text style={styles.sectionTitle}>Account</Text>
        <Card style={styles.accountCard}>
          <SettingRow icon="shield-checkmark-outline" label="KYC Status" value={user?.kyc_verified ? 'Verified ✅' : 'Pending'} />
          <SettingRow icon="lock-closed-outline" label="Two-Factor Auth" value={user?.two_factor_enabled ? 'Enabled' : 'Disabled'} />
          <SettingRow icon="document-text-outline" label="App Version" value="1.0.0" />
        </Card>

        {/* Sign out */}
        <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
          <Ionicons name="log-out-outline" size={20} color={COLORS.sell} />
          <Text style={styles.logoutText}>Sign Out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function SettingRow({ icon, label, value }: { icon: string; label: string; value: string }) {
  return (
    <View style={rowStyles.row}>
      <Ionicons name={icon as any} size={18} color={COLORS.textMuted} />
      <Text style={rowStyles.label}>{label}</Text>
      <Text style={rowStyles.value}>{value}</Text>
    </View>
  );
}

const PREF_LABELS: Record<keyof NotificationPrefs, string> = {
  signals: 'AI Trading Signals',
  trade_fills: 'Order Fills',
  price_alerts: 'Price Alerts',
  daily_summary: 'Daily P&L Summary',
  risk_warnings: 'Risk Warnings',
};

const rowStyles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, paddingVertical: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  label: { flex: 1, color: COLORS.text, fontSize: 14 },
  value: { color: COLORS.textMuted, fontSize: 13 },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  pageTitle: { color: COLORS.text, fontSize: 24, fontWeight: '800' },
  profileCard: { flexDirection: 'row', alignItems: 'center', gap: SPACING.md },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: COLORS.accent, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: COLORS.white, fontSize: 24, fontWeight: '800' },
  profileName: { color: COLORS.text, fontSize: 18, fontWeight: '700' },
  profileEmail: { color: COLORS.textMuted, fontSize: 13, marginTop: 2 },
  roleBadge: { backgroundColor: COLORS.accent + '33', paddingHorizontal: SPACING.sm, paddingVertical: 2, borderRadius: RADIUS.sm, alignSelf: 'flex-start', marginTop: SPACING.xs },
  roleText: { color: COLORS.accent, fontSize: 11, fontWeight: '700' },
  sectionTitle: { color: COLORS.text, fontSize: 16, fontWeight: '700' },
  prefsCard: { gap: SPACING.xs },
  prefRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: SPACING.sm, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  prefLabel: { color: COLORS.text, fontSize: 14, flex: 1 },
  testBtn: { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, padding: SPACING.md, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.accent },
  testBtnText: { color: COLORS.accent, fontSize: 14, fontWeight: '600' },
  accountCard: { gap: 0 },
  logoutBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: SPACING.sm, padding: SPACING.md, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.sell, marginTop: SPACING.md },
  logoutText: { color: COLORS.sell, fontSize: 16, fontWeight: '700' },
});
