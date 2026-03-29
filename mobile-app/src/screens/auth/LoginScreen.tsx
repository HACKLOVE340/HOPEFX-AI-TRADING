// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/auth/LoginScreen.tsx
 * ============================
 * Email + password login with 2FA redirect and biometric hint.
 */

import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { AuthStackParamList } from '../../types';
import { useAuthStore } from '../../store/authStore';
import { Button } from '../../components/Button';
import { ErrorBanner } from '../../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';

type Props = {
  navigation: NativeStackNavigationProp<AuthStackParamList, 'Login'>;
};

export function LoginScreen({ navigation }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const { login, isLoading, error, clearError } = useAuthStore();

  const handleLogin = async () => {
    if (!email.trim() || !password) return;
    clearError();
    try {
      await login(email.trim().toLowerCase(), password);
      // Navigation handled automatically by RootNavigator auth state change
    } catch (e: unknown) {
      // Check if 2FA required
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail ?? '';
      if (detail.includes('2fa') || detail.includes('two_factor')) {
        navigation.navigate('TwoFactor', { email: email.trim(), password });
      }
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.kav}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          {/* Logo / Header */}
          <View style={styles.header}>
            <Text style={styles.logo}>HOPE<Text style={styles.logoAccent}>FX</Text></Text>
            <Text style={styles.tagline}>AI-Powered Gold Trading</Text>
          </View>

          {/* Form */}
          <View style={styles.form}>
            <Text style={styles.title}>Sign In</Text>

            {error && <ErrorBanner message={error} onDismiss={clearError} />}

            <View style={styles.field}>
              <Text style={styles.label}>Email</Text>
              <TextInput
                style={styles.input}
                value={email}
                onChangeText={setEmail}
                placeholder="you@example.com"
                placeholderTextColor={COLORS.textDim}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                returnKeyType="next"
              />
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>Password</Text>
              <View style={styles.passwordRow}>
                <TextInput
                  style={[styles.input, styles.passwordInput]}
                  value={password}
                  onChangeText={setPassword}
                  placeholder="••••••••"
                  placeholderTextColor={COLORS.textDim}
                  secureTextEntry={!showPassword}
                  returnKeyType="done"
                  onSubmitEditing={handleLogin}
                />
                <TouchableOpacity
                  style={styles.eyeBtn}
                  onPress={() => setShowPassword((v) => !v)}
                >
                  <Text style={styles.eyeText}>{showPassword ? '🙈' : '👁'}</Text>
                </TouchableOpacity>
              </View>
            </View>

            <TouchableOpacity
              onPress={() => navigation.navigate('ForgotPassword')}
              style={styles.forgotRow}
            >
              <Text style={styles.forgotText}>Forgot password?</Text>
            </TouchableOpacity>

            <Button
              title="Sign In"
              onPress={handleLogin}
              loading={isLoading}
              disabled={!email || !password}
              fullWidth
              style={styles.submitBtn}
            />

            <View style={styles.registerRow}>
              <Text style={styles.registerText}>Don't have an account? </Text>
              <TouchableOpacity onPress={() => navigation.navigate('Register')}>
                <Text style={styles.registerLink}>Create Account</Text>
              </TouchableOpacity>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: COLORS.background },
  kav: { flex: 1 },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: SPACING.lg },
  header: { alignItems: 'center', marginBottom: SPACING.xxl },
  logo: { fontSize: 42, fontWeight: '900', color: COLORS.text, letterSpacing: 2 },
  logoAccent: { color: COLORS.accent },
  tagline: { color: COLORS.textMuted, fontSize: 14, marginTop: SPACING.xs },
  form: { gap: SPACING.md },
  title: { fontSize: 24, fontWeight: '700', color: COLORS.text, marginBottom: SPACING.sm },
  field: { gap: SPACING.xs },
  label: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  input: {
    backgroundColor: COLORS.surface,
    borderWidth: 1,
    borderColor: COLORS.border,
    borderRadius: RADIUS.md,
    padding: SPACING.md,
    color: COLORS.text,
    fontSize: 15,
  },
  passwordRow: { flexDirection: 'row', alignItems: 'center' },
  passwordInput: { flex: 1 },
  eyeBtn: { position: 'absolute', right: SPACING.md },
  eyeText: { fontSize: 18 },
  forgotRow: { alignSelf: 'flex-end' },
  forgotText: { color: COLORS.accent, fontSize: 13 },
  submitBtn: { marginTop: SPACING.sm },
  registerRow: { flexDirection: 'row', justifyContent: 'center', marginTop: SPACING.md },
  registerText: { color: COLORS.textMuted, fontSize: 14 },
  registerLink: { color: COLORS.accent, fontSize: 14, fontWeight: '600' },
});
