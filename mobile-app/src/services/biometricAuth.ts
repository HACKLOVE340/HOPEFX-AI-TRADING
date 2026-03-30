// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/biometricAuth.ts
 * =========================
 * Face ID / Fingerprint authentication via expo-local-authentication.
 * Wraps the native biometric API with a clean async interface.
 */

import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';

const BIOMETRIC_ENABLED_KEY = 'hopefx_biometric_enabled';
const BIOMETRIC_TOKEN_KEY   = 'hopefx_biometric_token';

export type BiometricType = 'fingerprint' | 'facial' | 'iris' | 'none';

export interface BiometricCapability {
  isAvailable: boolean;
  isEnrolled: boolean;
  types: BiometricType[];
  primaryType: BiometricType;
}

export interface BiometricResult {
  success: boolean;
  error?: string;
}

class BiometricAuthService {
  /**
   * Check device biometric capability.
   */
  async getCapability(): Promise<BiometricCapability> {
    const isAvailable = await LocalAuthentication.hasHardwareAsync();
    if (!isAvailable) {
      return { isAvailable: false, isEnrolled: false, types: [], primaryType: 'none' };
    }

    const isEnrolled = await LocalAuthentication.isEnrolledAsync();
    const supportedTypes = await LocalAuthentication.supportedAuthenticationTypesAsync();

    const types: BiometricType[] = supportedTypes.map((t) => {
      switch (t) {
        case LocalAuthentication.AuthenticationType.FINGERPRINT:
          return 'fingerprint';
        case LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION:
          return 'facial';
        case LocalAuthentication.AuthenticationType.IRIS:
          return 'iris';
        default:
          return 'fingerprint';
      }
    });

    const primaryType: BiometricType =
      types.includes('facial') ? 'facial' :
      types.includes('fingerprint') ? 'fingerprint' :
      types.includes('iris') ? 'iris' : 'none';

    return { isAvailable, isEnrolled, types, primaryType };
  }

  /**
   * Prompt biometric authentication.
   */
  async authenticate(reason = 'Authenticate to access HopeFX Trading'): Promise<BiometricResult> {
    try {
      const capability = await this.getCapability();
      if (!capability.isAvailable || !capability.isEnrolled) {
        return { success: false, error: 'Biometric authentication not available' };
      }

      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: reason,
        cancelLabel: 'Use Password',
        disableDeviceFallback: false,
        fallbackLabel: 'Use Password',
      });

      if (result.success) {
        return { success: true };
      }

      const errorMsg =
        result.error === 'user_cancel'    ? 'Authentication cancelled' :
        result.error === 'user_fallback'  ? 'Fallback requested' :
        result.error === 'lockout'        ? 'Too many attempts — try again later' :
        result.error === 'not_enrolled'   ? 'No biometrics enrolled' :
        'Authentication failed';

      return { success: false, error: errorMsg };
    } catch (e) {
      return { success: false, error: 'Biometric error: ' + String(e) };
    }
  }

  /**
   * Check if biometric login is enabled by the user.
   */
  async isEnabled(): Promise<boolean> {
    try {
      const val = await SecureStore.getItemAsync(BIOMETRIC_ENABLED_KEY);
      return val === 'true';
    } catch {
      return false;
    }
  }

  /**
   * Enable biometric login — stores the current access token for retrieval.
   */
  async enable(accessToken: string): Promise<BiometricResult> {
    const auth = await this.authenticate('Enable biometric login for HopeFX');
    if (!auth.success) return auth;

    try {
      await SecureStore.setItemAsync(BIOMETRIC_ENABLED_KEY, 'true');
      await SecureStore.setItemAsync(BIOMETRIC_TOKEN_KEY, accessToken);
      return { success: true };
    } catch (e) {
      return { success: false, error: 'Failed to save biometric settings' };
    }
  }

  /**
   * Disable biometric login.
   */
  async disable(): Promise<void> {
    await SecureStore.deleteItemAsync(BIOMETRIC_ENABLED_KEY);
    await SecureStore.deleteItemAsync(BIOMETRIC_TOKEN_KEY);
  }

  /**
   * Authenticate and return the stored token (for biometric login flow).
   */
  async loginWithBiometric(): Promise<{ success: boolean; token?: string; error?: string }> {
    const enabled = await this.isEnabled();
    if (!enabled) return { success: false, error: 'Biometric login not enabled' };

    const auth = await this.authenticate('Sign in to HopeFX Trading');
    if (!auth.success) return auth;

    try {
      const token = await SecureStore.getItemAsync(BIOMETRIC_TOKEN_KEY);
      if (!token) return { success: false, error: 'No stored credentials' };
      return { success: true, token };
    } catch {
      return { success: false, error: 'Failed to retrieve credentials' };
    }
  }

  /**
   * Update the stored token (call after token refresh).
   */
  async updateStoredToken(newToken: string): Promise<void> {
    const enabled = await this.isEnabled();
    if (enabled) {
      await SecureStore.setItemAsync(BIOMETRIC_TOKEN_KEY, newToken);
    }
  }
}

export const biometricAuth = new BiometricAuthService();
