// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, ScrollView,
  KeyboardAvoidingView, Platform, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { AuthStackParamList } from '../../types';
import { useAuthStore } from '../../store/authStore';
import { Button } from '../../components/Button';
import { ErrorBanner } from '../../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';

type Props = { navigation: NativeStackNavigationProp<AuthStackParamList, 'Register'> };

export function RegisterScreen({ navigation }: Props) {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [localError, setLocalError] = useState('');

  const { register, isLoading, error, clearError } = useAuthStore();

  const handleRegister = async () => {
    clearError();
    setLocalError('');
    if (!email || !username || !password) {
      setLocalError('All fields are required.');
      return;
    }
    if (password.length < 8) {
      setLocalError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setLocalError('Passwords do not match.');
      return;
    }
    try {
      await register(email.trim().toLowerCase(), password, username.trim());
    } catch {
      // error shown via store
    }
  };

  const displayError = localError || error;

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.kav}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <Text style={styles.logo}>HOPE<Text style={styles.logoAccent}>FX</Text></Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.title}>Create Account</Text>

            {displayError && (
              <ErrorBanner message={displayError} onDismiss={() => { clearError(); setLocalError(''); }} />
            )}

            {[
              { label: 'Email', value: email, setter: setEmail, keyboard: 'email-address' as const, placeholder: 'you@example.com' },
              { label: 'Username', value: username, setter: setUsername, keyboard: 'default' as const, placeholder: 'trader123' },
              { label: 'Password', value: password, setter: setPassword, keyboard: 'default' as const, placeholder: '••••••••', secure: true },
              { label: 'Confirm Password', value: confirm, setter: setConfirm, keyboard: 'default' as const, placeholder: '••••••••', secure: true },
            ].map(({ label, value, setter, keyboard, placeholder, secure }) => (
              <View key={label} style={styles.field}>
                <Text style={styles.label}>{label}</Text>
                <TextInput
                  style={styles.input}
                  value={value}
                  onChangeText={setter}
                  placeholder={placeholder}
                  placeholderTextColor={COLORS.textDim}
                  keyboardType={keyboard}
                  autoCapitalize="none"
                  secureTextEntry={secure}
                />
              </View>
            ))}

            <Button title="Create Account" onPress={handleRegister} loading={isLoading} fullWidth style={styles.btn} />

            <View style={styles.loginRow}>
              <Text style={styles.loginText}>Already have an account? </Text>
              <TouchableOpacity onPress={() => navigation.navigate('Login')}>
                <Text style={styles.loginLink}>Sign In</Text>
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
  header: { alignItems: 'center', marginBottom: SPACING.xl },
  logo: { fontSize: 36, fontWeight: '900', color: COLORS.text, letterSpacing: 2 },
  logoAccent: { color: COLORS.accent },
  form: { gap: SPACING.md },
  title: { fontSize: 24, fontWeight: '700', color: COLORS.text, marginBottom: SPACING.sm },
  field: { gap: SPACING.xs },
  label: { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  input: {
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.border,
    borderRadius: RADIUS.md, padding: SPACING.md, color: COLORS.text, fontSize: 15,
  },
  btn: { marginTop: SPACING.sm },
  loginRow: { flexDirection: 'row', justifyContent: 'center', marginTop: SPACING.md },
  loginText: { color: COLORS.textMuted, fontSize: 14 },
  loginLink: { color: COLORS.accent, fontSize: 14, fontWeight: '600' },
});
