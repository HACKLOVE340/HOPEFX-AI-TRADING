// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/pushNotifications.ts
 * ==============================
 * Production push notification service using expo-notifications.
 *
 * Handles:
 *   - Device token registration + backend sync
 *   - Foreground notification display with custom styling
 *   - Background notification routing (tap → correct screen)
 *   - Custom sounds: signal.wav, risk_alert.wav
 *   - Haptic feedback on foreground notifications
 *   - Notification categories: SIGNAL, RISK, KILL_SWITCH, FILL, NEWS
 *
 * Notification types dispatched by backend:
 *   signal          → Signals tab, haptic: medium
 *   kill_switch     → Risk tab, haptic: error, sound: risk_alert.wav
 *   risk_warning    → Risk tab, haptic: warning
 *   trade_fill      → Trading tab, haptic: success
 *   price_alert     → Trading tab, haptic: light
 *   daily_summary   → Dashboard tab, haptic: none
 *   news_impact     → Signals tab, haptic: light
 */

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import * as Haptics from 'expo-haptics';
import { Platform } from 'react-native';
import { apiClient } from './apiClient';

/**
 * The fields we read off a permission response. `NotificationPermissionsStatus`
 * inherits these from `PermissionResponse` in `expo-modules-core`, but that base
 * package is hoisted under `expo/node_modules`, so the inherited members are not
 * always visible to the type checker. Reading them through this local shape keeps
 * the call sites type-safe regardless of how the dependency tree is laid out.
 */
type PermissionFields = { granted: boolean; canAskAgain: boolean };

// ── Foreground handler — show banner + haptic ─────────────────────────────────
Notifications.setNotificationHandler({
  handleNotification: async (notification) => {
    const data = notification.request.content.data as Record<string, unknown>;
    const type = String(data?.type ?? '');

    // Trigger haptic based on notification type
    triggerHaptic(type);

    return {
      // expo-notifications SDK 53+ replaced shouldShowAlert with
      // shouldShowBanner + shouldShowList.
      shouldShowBanner: true,
      shouldShowList:   true,
      shouldPlaySound:  true,
      shouldSetBadge:   true,
    };
  },
});

function triggerHaptic(type: string): void {
  switch (type) {
    case 'kill_switch':
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      break;
    case 'risk_warning':
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      break;
    case 'signal':
    case 'trade_fill':
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      break;
    case 'price_alert':
    case 'news_impact':
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      break;
    default:
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  }
}

// ── Navigation ref (set from App.tsx or RootNavigator) ───────────────────────
let _navigationRef: { navigate: (screen: string, params?: object) => void } | null = null;

export function setNavigationRef(ref: typeof _navigationRef): void {
  _navigationRef = ref;
}

function routeNotification(data: Record<string, unknown>): void {
  if (!_navigationRef) return;
  const type = String(data?.type ?? '');
  switch (type) {
    case 'signal':
    case 'news_impact':
      _navigationRef.navigate('Main', { screen: 'Signals' });
      break;
    case 'kill_switch':
    case 'risk_warning':
      _navigationRef.navigate('Main', { screen: 'Risk' });
      break;
    case 'trade_fill':
    case 'price_alert':
      _navigationRef.navigate('Main', { screen: 'Trading' });
      break;
    case 'daily_summary':
      _navigationRef.navigate('Main', { screen: 'Dashboard' });
      break;
  }
}

// ── Notification categories (iOS action buttons) ──────────────────────────────
async function registerCategories(): Promise<void> {
  await Notifications.setNotificationCategoryAsync('SIGNAL', [
    {
      identifier: 'VIEW_SIGNAL',
      buttonTitle: 'View Signal',
      options: { opensAppToForeground: true },
    },
    {
      identifier: 'DISMISS',
      buttonTitle: 'Dismiss',
      options: { isDestructive: false, opensAppToForeground: false },
    },
  ]);

  await Notifications.setNotificationCategoryAsync('KILL_SWITCH', [
    {
      identifier: 'VIEW_RISK',
      buttonTitle: 'View Risk Dashboard',
      options: { opensAppToForeground: true },
    },
  ]);

  await Notifications.setNotificationCategoryAsync('TRADE_FILL', [
    {
      identifier: 'VIEW_POSITION',
      buttonTitle: 'View Position',
      options: { opensAppToForeground: true },
    },
  ]);
}

// ── Android notification channels ─────────────────────────────────────────────
async function setupAndroidChannels(): Promise<void> {
  if (Platform.OS !== 'android') return;

  await Notifications.setNotificationChannelAsync('signals', {
    name: 'AI Signals',
    importance: Notifications.AndroidImportance.HIGH,
    vibrationPattern: [0, 250, 250, 250],
    lightColor: '#00d4aa',
    sound: 'signal.wav',
    description: 'New AI-generated trading signals',
  });

  await Notifications.setNotificationChannelAsync('risk_alerts', {
    name: 'Risk Alerts',
    importance: Notifications.AndroidImportance.MAX,
    vibrationPattern: [0, 500, 200, 500, 200, 500],
    lightColor: '#ff1744',
    sound: 'risk_alert.wav',
    description: 'Kill switch and risk breach alerts',
    bypassDnd: true,
  });

  await Notifications.setNotificationChannelAsync('trade_fills', {
    name: 'Trade Fills',
    importance: Notifications.AndroidImportance.DEFAULT,
    vibrationPattern: [0, 150],
    lightColor: '#00e676',
    description: 'Order execution confirmations',
  });

  await Notifications.setNotificationChannelAsync('price_alerts', {
    name: 'Price Alerts',
    importance: Notifications.AndroidImportance.HIGH,
    vibrationPattern: [0, 200],
    lightColor: '#ffab00',
    description: 'Custom price level alerts',
  });

  await Notifications.setNotificationChannelAsync('general', {
    name: 'General',
    importance: Notifications.AndroidImportance.DEFAULT,
    description: 'Daily summaries and general notifications',
  });
}

// ── Main service class ────────────────────────────────────────────────────────

class PushNotificationService {
  private _token: string | null = null;
  private _responseListener: Notifications.Subscription | null = null;
  private _receivedListener: Notifications.Subscription | null = null;

  async register(): Promise<string | null> {
    if (!Device.isDevice) {
      console.log('[Push] Skipping registration on simulator');
      return null;
    }

    // Request permissions. SDK 55 exposes a `.granted` boolean on the
    // PermissionResponse — prefer it over the (now untyped) `.status` field.
    const existing = (await Notifications.getPermissionsAsync()) as PermissionFields;
    let granted = existing.granted;

    if (!granted) {
      const requested = (await Notifications.requestPermissionsAsync({
        ios: {
          allowAlert: true,
          allowBadge: true,
          allowSound: true,
          allowCriticalAlerts: true,
        },
      })) as PermissionFields;
      granted = requested.granted;
    }

    if (!granted) {
      console.log('[Push] Permission denied');
      return null;
    }

    // Setup channels and categories
    await setupAndroidChannels();
    await registerCategories();

    // Get Expo push token
    try {
      const tokenData = await Notifications.getExpoPushTokenAsync({
        projectId: 'hopefx-trading-app',
      });
      this._token = tokenData.data;

      // Register token with backend
      await apiClient.registerPushToken({
        token: this._token,
        platform: Platform.OS as 'ios' | 'android',
        device_id: Device.modelId ?? 'unknown',
      });

      console.log('[Push] Registered:', this._token);
    } catch (e) {
      console.warn('[Push] Token registration failed:', e);
    }

    // Listen for notification taps (background → foreground)
    this._responseListener = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        const data = response.notification.request.content.data as Record<string, unknown>;
        const actionId = response.actionIdentifier;

        // Handle category actions
        if (actionId === 'VIEW_SIGNAL' || actionId === Notifications.DEFAULT_ACTION_IDENTIFIER) {
          routeNotification(data);
        }
      }
    );

    // Listen for foreground notifications
    this._receivedListener = Notifications.addNotificationReceivedListener(
      (notification) => {
        const data = notification.request.content.data as Record<string, unknown>;
        console.log('[Push] Received foreground:', data?.type);
      }
    );

    return this._token;
  }

  /**
   * Schedule a local notification (for testing or offline alerts).
   */
  async scheduleLocal(opts: {
    title: string;
    body: string;
    type: string;
    data?: Record<string, unknown>;
    channelId?: string;
    sound?: string;
    seconds?: number;
  }): Promise<string> {
    return Notifications.scheduleNotificationAsync({
      content: {
        title: opts.title,
        body:  opts.body,
        data:  { type: opts.type, ...opts.data },
        sound: opts.sound ?? 'default',
        ...(Platform.OS === 'android' && { channelId: opts.channelId ?? 'general' }),
      },
      trigger: opts.seconds
        ? { type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL, seconds: opts.seconds }
        : null,
    });
  }

  /**
   * Send a kill switch local alert immediately.
   */
  async alertKillSwitch(reason: string): Promise<void> {
    await this.scheduleLocal({
      title: '🚨 KILL SWITCH ACTIVATED',
      body:  reason || 'All trading has been halted by the risk system.',
      type:  'kill_switch',
      channelId: 'risk_alerts',
      sound: 'risk_alert.wav',
    });
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
  }

  /**
   * Send a high-confidence signal local alert.
   */
  async alertSignal(symbol: string, direction: string, confidence: number): Promise<void> {
    await this.scheduleLocal({
      title: `📊 ${direction.toUpperCase()} Signal — ${symbol}`,
      body:  `Confidence: ${(confidence * 100).toFixed(0)}% — Tap to review`,
      type:  'signal',
      channelId: 'signals',
      sound: 'signal.wav',
    });
  }

  /**
   * Send a risk warning local alert.
   */
  async alertRiskWarning(message: string): Promise<void> {
    await this.scheduleLocal({
      title: '⚠️ Risk Warning',
      body:  message,
      type:  'risk_warning',
      channelId: 'risk_alerts',
    });
  }

  /**
   * Returns the current push permission status ('granted' | 'denied' | 'undetermined').
   */
  async getPermissionStatus(): Promise<string> {
    const perms = (await Notifications.getPermissionsAsync()) as PermissionFields;
    if (perms.granted) return 'granted';
    return perms.canAskAgain ? 'undetermined' : 'denied';
  }

  /**
   * Request push permission and register the device token with the backend.
   * Returns the Expo push token string, or null if permission was denied.
   */
  async registerForPushNotificationsAsync(): Promise<string | null> {
    return this.register();
  }

  /**
   * Schedule an immediate local notification (convenience wrapper for useNotifications hook).
   */
  async scheduleLocalNotification(
    title: string,
    body: string,
    data: Record<string, unknown> = {}
  ): Promise<string> {
    return this.scheduleLocal({
      title,
      body,
      type: String(data.type ?? 'general'),
      data,
    });
  }

  async clearBadge(): Promise<void> {
    await Notifications.setBadgeCountAsync(0);
  }

  teardown(): void {
    this._responseListener?.remove();
    this._receivedListener?.remove();
  }

  get token(): string | null { return this._token; }
}

export const pushNotifications = new PushNotificationService();
