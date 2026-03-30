// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useState, useRef } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import * as Haptics from 'expo-haptics';
import { apiClient } from '../../services/apiClient';
import { useAuthStore } from '../../store/authStore';
import { wsClient } from '../../services/wsClient';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../../utils/theme';
import { AuthStackParamList } from '../../types';

type RouteT = RouteProp<AuthStackParamList, 'TwoFactor'>;

export function TwoFactorScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteT>();
  const { setUser } = useAuthStore();
  const [code, setCode]       = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  const handleVerify = async () => {
    if (code.length !== 6) return;
    setLoading(true);
    setError('');
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      const tokens = await apiClient.verifyTwoFactorLogin(route.params.email, route.params.password, code);
      apiClient.setAuthToken(tokens.access_token);
      const user = await apiClient.getMe();
      wsClient.connect(tokens.access_token);
      setUser(user);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    } catch {
      setError('Invalid code. Try again.');
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        <Text style={styles.title}>Two-Factor Auth</Text>
        <Text style={styles.subtitle}>Enter the 6-digit code from your authenticator app.</Text>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <TextInput
          style={styles.codeInput}
          value={code}
          onChangeText={(t) => { setCode(t.replace(/\D/g, '').slice(0, 6)); }}
          keyboardType="number-pad"
          maxLength={6}
          placeholder="000000"
          placeholderTextColor={COLORS.textDim}
          selectionColor={COLORS.accent}
          textAlign="center"
        />

        <TouchableOpacity style={[styles.btn, (loading || code.length !== 6) && styles.btnDisabled]} onPress={handleVerify} disabled={loading || code.length !== 6}>
          {loading ? <ActivityIndicator color={COLORS.black} /> : <Text style={styles.btnText}>VERIFY</Text>}
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:      { flex: 1, backgroundColor: COLORS.background },
  content:   { flex: 1, padding: SPACING.lg, gap: SPACING.lg, justifyContent: 'center' },
  title:     { ...TEXT.h1, color: COLORS.text, textAlign: 'center' },
  subtitle:  { ...TEXT.body, color: COLORS.textMuted, textAlign: 'center' },
  error:     { ...TEXT.bodySM, color: COLORS.loss, textAlign: 'center' },
  codeInput: { height: 72, backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.lg, borderWidth: 2, borderColor: COLORS.borderAccent, color: COLORS.accent, fontSize: 36, fontWeight: '800', fontFamily: 'Courier New', letterSpacing: 12 },
  btn:       { backgroundColor: COLORS.accent, borderRadius: RADIUS.md, height: 52, alignItems: 'center', justifyContent: 'center', ...SHADOW.accentGlow },
  btnDisabled: { opacity: 0.5 },
  btnText:   { color: COLORS.black, fontWeight: '800', fontSize: 15, letterSpacing: 2 },
});
