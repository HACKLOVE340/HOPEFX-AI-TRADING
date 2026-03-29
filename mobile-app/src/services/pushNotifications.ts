// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/pushNotifications.ts
 * ==============================
 * Expo push notification registration and handler setup.
 *
 * Flow:
 *  1. Request permission (iOS prompts user; Android auto-grants on API 33+)
 *  2. Get Expo push token
 *  3. POST token to backend /api/mobile/push-token
 *  4. Register foreground + background notification handlers
 *
 * Notification categories handled:
 *  - SIGNAL      — new AI trading signal
 *  - FILL        — order filled
 *  - ALERT       — price alert triggered
 *  - RISK        — risk limit warning
 *  - DAILY       — daily P&L summary
 */

import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { apiClient } from './apiClient';

// Show notifications as banners even when app is foregrounded
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

class PushNotificationService {
  private _expoPushToken: string | null = null;

  async registerForPushNotificationsAsync(): Promise<string | null> {
    if (!Device.isDevice) {
      console.log('[Push] Skipping — not a physical device');
      return null;
    }

    // Android channel
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('hopefx-trading', {
        name: 'HopeFX Trading',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#00d4aa',
        sound: 'default',
      });
      await Notifications.setNotificationChannelAsync('hopefx-signals', {
        name: 'AI Signals',
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 100, 100, 100],
        lightColor: '#f59e0b',
        sound: 'default',
      });
      await Notifications.setNotificationChannelAsync('hopefx-risk', {
        name: 'Risk Alerts',
        importance: Notifications.AndroidImportance.MAX,
        vibrationPattern: [0, 500, 200, 500],
        lightColor: '#ef4444',
        sound: 'default',
      });
    }

    // Request permission
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;

    if (existingStatus !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }

    if (finalStatus !== 'granted') {
      console.log('[Push] Permission denied');
      return null;
    }

    // Get Expo push token
    const tokenData = await Notifications.getExpoPushTokenAsync({
      projectId: 'hopefx-trading-app',
    });
    this._expoPushToken = tokenData.data;
    console.log('[Push] Token:', this._expoPushToken);

    // Register with backend
    try {
      await apiClient.registerPushToken({
        token: this._expoPushToken,
        platform: Platform.OS as 'ios' | 'android',
        device_id: Device.modelId ?? 'unknown',
      });
    } catch (e) {
      console.warn('[Push] Failed to register token with backend:', e);
    }

    return this._expoPushToken;
  }

  setupNotificationHandlers(): void {
    // Foreground notification received
    Notifications.addNotificationReceivedListener((notification) => {
      const { title, body, data } = notification.request.content;
      console.log('[Push] Received:', title, body, data);
    });

    // User tapped notification
    Notifications.addNotificationResponseReceivedListener((response) => {
      const data = response.notification.request.content.data as Record<string, unknown>;
      console.log('[Push] Tapped:', data);
      // Navigation handled by deep link scheme: hopefx://
      // e.g. hopefx://trading/signal/123
    });
  }

  async scheduleLocalNotification(
    title: string,
    body: string,
    data?: Record<string, unknown>,
    channelId = 'hopefx-trading'
  ): Promise<void> {
    await Notifications.scheduleNotificationAsync({
      content: { title, body, data: data ?? {}, sound: 'default' },
      trigger: null, // immediate
    });
  }

  async getBadgeCount(): Promise<number> {
    return Notifications.getBadgeCountAsync();
  }

  async clearBadge(): Promise<void> {
    await Notifications.setBadgeCountAsync(0);
  }

  async getPermissionStatus(): Promise<'granted' | 'denied' | 'undetermined'> {
    const { status } = await Notifications.getPermissionsAsync();
    return status as 'granted' | 'denied' | 'undetermined';
  }

  get token(): string | null {
    return this._expoPushToken;
  }
}

export const pushNotifications = new PushNotificationService();
