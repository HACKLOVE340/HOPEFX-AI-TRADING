// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * components/ConnectionStatus.tsx
 * ================================
 * Compact WS connection status indicator for the header.
 */

import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';
import { COLORS, TEXT } from '../utils/theme';
import { WSConnectionStatus } from '../types';

interface Props {
  status: WSConnectionStatus;
  reconnectAttempts?: number;
}

export function ConnectionStatus({ status, reconnectAttempts = 0 }: Props) {
  const pulseAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (status === 'connected') {
      const pulse = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 0.3, duration: 1200, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1,   duration: 1200, useNativeDriver: true }),
        ])
      );
      pulse.start();
      return () => pulse.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [status]);

  const dotColor =
    status === 'connected'    ? COLORS.profit :
    status === 'connecting'   ? COLORS.warning :
    status === 'reconnecting' ? COLORS.warning : COLORS.loss;

  const label =
    status === 'connected'    ? 'LIVE' :
    status === 'connecting'   ? 'CONNECTING' :
    status === 'reconnecting' ? `RETRY ${reconnectAttempts}` : 'OFFLINE';

  return (
    <View style={styles.row}>
      <Animated.View style={[styles.dot, { backgroundColor: dotColor, opacity: status === 'connected' ? pulseAnim : 1 }]} />
      <Text style={[styles.label, { color: dotColor }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row:   { flexDirection: 'row', alignItems: 'center', gap: 5 },
  dot:   { width: 7, height: 7, borderRadius: 4 },
  label: { ...TEXT.labelSM, letterSpacing: 1 },
});
