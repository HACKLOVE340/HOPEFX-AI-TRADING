// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/auth/BiometricSetupScreen.tsx
 * ======================================
 * Post-login biometric enrollment screen.
 * Shown once after first login if biometrics are available but not yet enabled.
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, Animated, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useAuthStore } from '../../store/authStore';
import { biometricAuth, BiometricCapability } from '../../services/biometricAuth';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../../utils/theme';

interface Props {
  onDone: () => void;
}

export function BiometricSetupScreen({ onDone }: Props) {
  const { enableBiometric } = useAuthStore();
  const [capability, setCapability] = useState<BiometricCapability | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<'idle' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    biometricAuth.getCapability().then(setCapability);

    // Pulse animation for the icon
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1.12, duration: 900, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1,    duration: 900, useNativeDriver: true }),
      ])
    );
    pulse.start();
    return () => pulse.stop();
  }, []);

  const iconName = capability?.primaryType === 'facial' ? 'scan-outline' : 'finger-print';
  const typeName = capability?.primaryType === 'facial' ? 'Face ID' :
                   capability?.primaryType === 'iris'    ? 'Iris Scan' : 'Fingerprint';

  const handleEnable = async () => {
    setLoading(true);
    setResult('idle');
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    const res = await enableBiometric();
    setLoading(false);

    if (res.success) {
      setResult('success');
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setTimeout(onDone, 1200);
    } else {
      setResult('error');
      setErrorMsg(res.error ?? 'Setup failed');
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        {/* Icon */}
        <Animated.View style={[styles.iconRing, { transform: [{ scale: pulseAnim }] }]}>
          <Ionicons name={iconName as any} size={52} color={COLORS.accent} />
        </Animated.View>

        <Text style={styles.title}>Enable {typeName}</Text>
        <Text style={styles.subtitle}>
          Sign in instantly with {typeName} — no password required.
          Your credentials are stored securely in the device keychain.
        </Text>

        {result === 'success' && (
          <View style={styles.successBox}>
            <Ionicons name="checkmark-circle" size={20} color={COLORS.profit} />
            <Text style={styles.successText}>{typeName} enabled successfully</Text>
          </View>
        )}

        {result === 'error' && (
          <View style={styles.errorBox}>
            <Ionicons name="alert-circle" size={16} color={COLORS.loss} />
            <Text style={styles.errorText}>{errorMsg}</Text>
          </View>
        )}

        <TouchableOpacity
          style={[styles.enableBtn, loading && styles.btnDisabled]}
          onPress={handleEnable}
          disabled={loading || result === 'success'}
          activeOpacity={0.85}
        >
          {loading ? (
            <ActivityIndicator color={COLORS.black} />
          ) : (
            <>
              <Ionicons name={iconName as any} size={20} color={COLORS.black} />
              <Text style={styles.enableBtnText}>Enable {typeName}</Text>
            </>
          )}
        </TouchableOpacity>

        <TouchableOpacity style={styles.skipBtn} onPress={onDone}>
          <Text style={styles.skipText}>Skip for now</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: COLORS.background },
  content:     {
    flex: 1, alignItems: 'center', justifyContent: 'center',
    padding: SPACING.xl, gap: SPACING.lg,
  },
  iconRing:    {
    width: 120, height: 120, borderRadius: 60,
    borderWidth: 2, borderColor: COLORS.accent,
    backgroundColor: COLORS.accentGlow,
    alignItems: 'center', justifyContent: 'center',
    ...SHADOW.accentGlow,
  },
  title:       { ...TEXT.h1, color: COLORS.text, textAlign: 'center' },
  subtitle:    { ...TEXT.body, color: COLORS.textSecondary, textAlign: 'center', lineHeight: 22 },
  successBox:  {
    flexDirection: 'row', alignItems: 'center', gap: SPACING.sm,
    backgroundColor: COLORS.profitDim, borderRadius: RADIUS.md,
    padding: SPACING.sm, borderWidth: 1, borderColor: COLORS.profit + '44',
  },
  successText: { ...TEXT.body, color: COLORS.profit },
  errorBox:    {
    flexDirection: 'row', alignItems: 'center', gap: SPACING.sm,
    backgroundColor: COLORS.lossDim, borderRadius: RADIUS.md,
    padding: SPACING.sm, borderWidth: 1, borderColor: COLORS.loss + '44',
  },
  errorText:   { ...TEXT.bodySM, color: COLORS.loss, flex: 1 },
  enableBtn:   {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACING.sm, width: '100%', height: 56,
    backgroundColor: COLORS.accent, borderRadius: RADIUS.lg,
    ...SHADOW.accentGlow,
  },
  btnDisabled: { opacity: 0.5 },
  enableBtnText: { color: COLORS.black, fontWeight: '800', fontSize: 16, letterSpacing: 1 },
  skipBtn:     { paddingVertical: SPACING.sm },
  skipText:    { ...TEXT.body, color: COLORS.textMuted },
});
