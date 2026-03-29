// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useState } from 'react';
import {
  View, Text, TextInput, StyleSheet,
  KeyboardAvoidingView, Platform, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { AuthStackParamList } from '../../types';
import { apiClient } from '../../services/apiClient';
import { Button } from '../../components/Button';
import { ErrorBanner } from '../../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';

type Props = { navigation: NativeStackNavigationProp<AuthStackParamList, 'ForgotPassword'> };

export function ForgotPasswordScreen({ navigation }: Props) {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    if (!email.trim()) return;
    setLoading(true);
    setError('');
    try {
      await apiClient.forgotPassword(email.trim().toLowerCase());
      setSent(true);
    } catch {
      setError('Failed to send reset email. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.kav}>
        <View style={styles.container}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.back}>
            <Text style={styles.backText}>← Back</Text>
          </TouchableOpacity>

          <Text style={styles.title}>Reset Password</Text>
          <Text style={styles.subtitle}>
            Enter your email and we'll send you a reset link.
          </Text>

          {error ? <ErrorBanner message={error} onDismiss={() => setError('')} /> : null}

          {sent ? (
            <View style={styles.successBox}>
              <Text style={styles.successText}>
                ✅ Reset link sent to {email}. Check your inbox.
              </Text>
              <Button title="Back to Login" onPress={() => navigation.navigate('Login')} fullWidth style={styles.btn} />
            </View>
          ) : (
            <>
              <View style={styles.field}>
                <Text style={styles.label}>Email Address</Text>
                <TextInput
                  style={styles.input}
                  value={email}
                  onChangeText={setEmail}
                  placeholder="you@example.com"
                  placeholderTextColor={COLORS.textDim}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  returnKeyType="done"
                  onSubmitEditing={handleSubmit}
                />
              </View>
              <Button title="Send Reset Link" onPress={handleSubmit} loading={loading} disabled={!email} fullWidth style={styles.btn} />
            </>
          )}
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  kav: { flex: 1 },
  container: { flex: 1, padding: SPACING.lg, gap: SPACING.md },
  back: { marginBottom: SPACING.sm },
  backText: { color: COLORS.accent, fontSize: 15 },
  title: { fontSize: 26, fontWeight: '700', color: COLORS.text },
  subtitle: { color: COLORS.textMuted, fontSize: 14, lineHeight: 20 },
  field: { gap: SPACING.xs },
  label: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  input: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: RADIUS.md, padding: SPACING.md, color: COLORS.text, fontSize: 15,
  },
  btn: { marginTop: SPACING.sm },
  successBox: { gap: SPACING.md },
  successText: { color: COLORS.accent, fontSize: 15, lineHeight: 22 },
});
