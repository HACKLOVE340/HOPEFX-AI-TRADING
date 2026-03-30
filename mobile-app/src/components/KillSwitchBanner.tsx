// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/KillSwitchBanner.tsx
 * ================================
 * Full-width danger banner shown when kill switch is active.
 * Pulses with haptic feedback on mount.
 */

import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { COLORS, SPACING, RADIUS, TEXT } from '../utils/theme';

interface Props {
  reason?: string;
  triggeredAt?: string;
}

export function KillSwitchBanner({ reason, triggeredAt }: Props) {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 0.6, duration: 600, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 1,   duration: 600, useNativeDriver: true }),
      ])
    );
    pulse.start();
    return () => pulse.stop();
  }, []);

  return (
    <Animated.View style={[styles.banner, { opacity: pulseAnim }]}>
      <Ionicons name="warning" size={20} color={COLORS.white} />
      <View style={styles.text}>
        <Text style={styles.title}>KILL SWITCH ACTIVE — ALL TRADING HALTED</Text>
        {reason && <Text style={styles.reason}>{reason}</Text>}
        {triggeredAt && (
          <Text style={styles.time}>
            Triggered: {new Date(triggeredAt).toLocaleTimeString()}
          </Text>
        )}
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row', alignItems: 'flex-start', gap: SPACING.sm,
    backgroundColor: COLORS.killSwitch,
    borderRadius: RADIUS.md, padding: SPACING.md,
    borderWidth: 1, borderColor: COLORS.danger,
  },
  text:   { flex: 1, gap: 3 },
  title:  { ...TEXT.label, color: COLORS.white, letterSpacing: 0.5 },
  reason: { ...TEXT.bodySM, color: 'rgba(255,255,255,0.85)' },
  time:   { ...TEXT.caption, color: 'rgba(255,255,255,0.65)' },
});
