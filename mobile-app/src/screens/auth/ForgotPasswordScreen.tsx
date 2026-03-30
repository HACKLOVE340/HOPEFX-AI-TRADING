// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../../services/apiClient';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../../utils/theme';

export function ForgotPasswordScreen() {
  const navigation = useNavigation();
  const [email, setEmail]     = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent]       = useState(false);

  const handleSubmit = async () => {
    if (!email) return;
    setLoading(true);
    try {
      await apiClient.requestPasswordReset(email.trim().toLowerCase());
      setSent(true);
    } catch {
      Alert.alert('Error', 'Failed to send reset email. Check the address and try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        <TouchableOpacity style={styles.backBtn} onPress={() => navigation.goBack()}>
          <Ionicons name="arrow-back" size={22} color={COLORS.textSecondary} />
        </TouchableOpacity>
        <Text style={styles.title}>Reset Password</Text>
        <Text style={styles.subtitle}>Enter your email to receive a reset link.</Text>

        {sent ? (
          <View style={styles.successBox}>
            <Ionicons name="checkmark-circle" size={24} color={COLORS.profit} />
            <Text style={styles.successText}>Reset link sent to {email}</Text>
          </View>
        ) : (
          <>
            <View style={styles.inputGroup}>
              <Text style={styles.inputLabel}>EMAIL</Text>
              <View style={styles.inputWrap}>
                <Ionicons name="mail-outline" size={18} color={COLORS.textMuted} style={styles.inputIcon} />
                <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="you@hopefx.io" placeholderTextColor={COLORS.textDim} keyboardType="email-address" autoCapitalize="none" selectionColor={COLORS.accent} />
              </View>
            </View>
            <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={handleSubmit} disabled={loading || !email}>
              {loading ? <ActivityIndicator color={COLORS.black} /> : <Text style={styles.btnText}>SEND RESET LINK</Text>}
            </TouchableOpacity>
          </>
        )}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: COLORS.background },
  content:     { flex: 1, padding: SPACING.lg, gap: SPACING.md },
  backBtn:     { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  title:       { ...TEXT.h1, color: COLORS.text },
  subtitle:    { ...TEXT.body, color: COLORS.textMuted },
  successBox:  { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm, backgroundColor: COLORS.profitDim, borderRadius: RADIUS.md, padding: SPACING.md, borderWidth: 1, borderColor: COLORS.profit + '44' },
  successText: { ...TEXT.body, color: COLORS.profit, flex: 1 },
  inputGroup:  { gap: SPACING.xs },
  inputLabel:  { ...TEXT.label, color: COLORS.textMuted },
  inputWrap:   { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.sm },
  inputIcon:   { marginRight: SPACING.xs },
  input:       { flex: 1, height: 48, color: COLORS.text, fontSize: 15 },
  btn:         { backgroundColor: COLORS.accent, borderRadius: RADIUS.md, height: 52, alignItems: 'center', justifyContent: 'center', ...SHADOW.accentGlow },
  btnDisabled: { opacity: 0.5 },
  btnText:     { color: COLORS.black, fontWeight: '800', fontSize: 15, letterSpacing: 2 },
});
