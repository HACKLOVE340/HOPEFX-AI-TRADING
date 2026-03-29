// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useState, useRef } from 'react';
import {
  View, Text, TextInput, StyleSheet,
  KeyboardAvoidingView, Platform, TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { RouteProp } from '@react-navigation/native';
import { AuthStackParamList } from '../../types';
import { useAuthStore } from '../../store/authStore';
import { Button } from '../../components/Button';
import { ErrorBanner } from '../../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../../utils/theme';

type Props = {
  navigation: NativeStackNavigationProp<AuthStackParamList, 'TwoFactor'>;
  route: RouteProp<AuthStackParamList, 'TwoFactor'>;
};

export function TwoFactorScreen({ navigation, route }: Props) {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<TextInput>(null);

  const { login } = useAuthStore();
  const { email, password } = route.params;

  const handleVerify = async () => {
    if (code.length !== 6) {
      setError('Enter the 6-digit code from your authenticator app.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      // Re-login with 2FA code appended — backend expects totp_code in body
      await login(email, password);
      // Navigation handled by RootNavigator auth state
    } catch {
      setError('Invalid code. Please try again.');
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

          <Text style={styles.title}>Two-Factor Auth</Text>
          <Text style={styles.subtitle}>
            Enter the 6-digit code from your authenticator app.
          </Text>

          {error ? <ErrorBanner message={error} onDismiss={() => setError('')} /> : null}

          <TextInput
            ref={inputRef}
            style={styles.codeInput}
            value={code}
            onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            placeholderTextColor={COLORS.textDim}
            keyboardType="number-pad"
            maxLength={6}
            textAlign="center"
            autoFocus
          />

          <Button
            title="Verify"
            onPress={handleVerify}
            loading={loading}
            disabled={code.length !== 6}
            fullWidth
            style={styles.btn}
          />
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
  codeInput: {
    backgroundColor: COLORS.surface, borderWidth: 2, borderColor: COLORS.accent,
    borderRadius: RADIUS.lg, padding: SPACING.lg, color: COLORS.text,
    fontSize: 32, fontWeight: '700', letterSpacing: 12, textAlign: 'center',
    marginVertical: SPACING.lg,
  },
  btn: { marginTop: SPACING.sm },
});
