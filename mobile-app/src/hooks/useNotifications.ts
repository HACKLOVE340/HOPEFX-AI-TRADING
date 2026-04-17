// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * hooks/useNotifications.ts
 * =========================
 * Manage notification preferences and push token registration.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../services/apiClient';
import { pushNotifications } from '../services/pushNotifications';
import { NotificationPrefs } from '../types';

const DEFAULT_PREFS: NotificationPrefs = {
  signals: true,
  trade_fills: true,
  price_alerts: true,
  daily_summary: true,
  risk_warnings: true,
  kill_switch: true,
  news_impact: true,
};

export function useNotifications() {
  const [prefs, setPrefs] = useState<NotificationPrefs>(DEFAULT_PREFS);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Load prefs from API
    apiClient
      .getNotificationPrefs()
      .then(setPrefs)
      .catch(() => {/* use defaults */});

    // Check push permission status
    pushNotifications
      .getPermissionStatus()
      .then((status) => setPushEnabled(status === 'granted'))
      .catch(() => {});
  }, []);

  const togglePref = useCallback(
    async (key: keyof NotificationPrefs) => {
      const updated = { ...prefs, [key]: !prefs[key] };
      const prev = prefs;
      setPrefs(updated);
      setSaving(true);
      setError(null);
      try {
        await apiClient.updateNotificationPrefs({ [key]: updated[key] });
      } catch {
        setPrefs(prev);
        setError('Failed to save preference');
      } finally {
        setSaving(false);
      }
    },
    [prefs]
  );

  const requestPushPermission = useCallback(async () => {
    const token = await pushNotifications.registerForPushNotificationsAsync();
    setPushEnabled(!!token);
    return !!token;
  }, []);

  const sendTestNotification = useCallback(async () => {
    await pushNotifications.scheduleLocalNotification(
      'HopeFX Test',
      'Push notifications are working correctly.',
      { type: 'test' }
    );
  }, []);

  return {
    prefs,
    pushEnabled,
    saving,
    error,
    togglePref,
    requestPushPermission,
    sendTestNotification,
  };
}
