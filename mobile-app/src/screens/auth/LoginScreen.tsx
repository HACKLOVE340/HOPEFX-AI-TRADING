// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/auth/LoginScreen.tsx
 * ============================
 * Institutional-grade login with biometric fast-auth, animated entry,
 * and full error handling.
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator,
  Animated,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useAuthStore } from '../../store/authStore';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../../utils/theme';
import { AuthStackParamList } from '../../types';

type Nav = NativeStackNavigationProp<AuthStackParamList>;

export function LoginScreen() {
  const navigation = useNavigation<Nav>();
  const { login, loginWithBiometric, isLoading, error, clearError,
          biometricAvailable, biometricEnabled } = useAuthStore();

  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);

  // Entry animation
  const fadeAnim  = useRef(new Animated.Value(0)).current;
  const slideAnim = useRef(new Animated.Value(30)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fadeAnim,  { toValue: 1, duration: 600, useNativeDriver: true }),
      Animated.timing(slideAnim, { toValue: 0, duration: 500, useNativeDriver: true }),
    ]).start();
  }, []);

  useEffect(() => {
    if (error) {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    }
  }, [error]);

  const handleLogin = async () => {
    if (!email.trim() || !password) return;
    clearError();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    await login(email.trim().toLowerCase(), password);
  };

  const handleBiometric = async () => {
    clearError();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    await loginWithBiometric();
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Animated.View style={[styles.content, { opacity: fadeAnim, transform: [{ translateY: slideAnim }] }]}>
            {/* Logo / Brand */}
            <View style={styles.brand}>
              <View style={styles.logoRing}>
                <Text style={styles.logoText}>HX</Text>
              </View>
              <Text style={styles.brandName}>HopeFX</Text>
              <Text style={styles.brandTagline}>Institutional AI Trading</Text>
            </View>

            {/* Form */}
            <View style={styles.form}>
              <Text style={styles.formTitle}>Sign In</Text>

              {error ? (
                <View style={styles.errorBox}>
                  <Ionicons name="alert-circle" size={16} color={COLORS.loss} />
                  <Text style={styles.errorText}>{error}</Text>
                </View>
              ) : null}

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>EMAIL</Text>
                <View style={styles.inputWrap}>
                  <Ionicons name="mail-outline" size={18} color={COLORS.textMuted} style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    value={email}
                    onChangeText={setEmail}
                    placeholder="trader@hopefx.io"
                    placeholderTextColor={COLORS.textDim}
                    keyboardType="email-address"
                    autoCapitalize="none"
                    autoCorrect={false}
                    returnKeyType="next"
                    selectionColor={COLORS.accent}
                  />
                </View>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>PASSWORD</Text>
                <View style={styles.inputWrap}>
                  <Ionicons name="lock-closed-outline" size={18} color={COLORS.textMuted} style={styles.inputIcon} />
                  <TextInput
                    style={[styles.input, styles.inputPassword]}
                    value={password}
                    onChangeText={setPassword}
                    placeholder="••••••••"
                    placeholderTextColor={COLORS.textDim}
                    secureTextEntry={!showPass}
                    returnKeyType="done"
                    onSubmitEditing={handleLogin}
                    selectionColor={COLORS.accent}
                  />
                  <TouchableOpacity onPress={() => setShowPass(!showPass)} style={styles.eyeBtn}>
                    <Ionicons
                      name={showPass ? 'eye-off-outline' : 'eye-outline'}
                      size={18}
                      color={COLORS.textMuted}
                    />
                  </TouchableOpacity>
                </View>
              </View>

              <TouchableOpacity
                style={styles.forgotBtn}
                onPress={() => navigation.navigate('ForgotPassword')}
              >
                <Text style={styles.forgotText}>Forgot password?</Text>
              </TouchableOpacity>

              {/* Primary login button */}
              <TouchableOpacity
                style={[styles.loginBtn, isLoading && styles.loginBtnDisabled]}
                onPress={handleLogin}
                disabled={isLoading || !email || !password}
                activeOpacity={0.85}
              >
                {isLoading ? (
                  <ActivityIndicator color={COLORS.black} size="small" />
                ) : (
                  <Text style={styles.loginBtnText}>SIGN IN</Text>
                )}
              </TouchableOpacity>

              {/* Biometric login */}
              {biometricAvailable && biometricEnabled && (
                <TouchableOpacity
                  style={styles.biometricBtn}
                  onPress={handleBiometric}
                  disabled={isLoading}
                  activeOpacity={0.8}
                >
                  <Ionicons name="finger-print" size={22} color={COLORS.accent} />
                  <Text style={styles.biometricText}>Use Biometric</Text>
                </TouchableOpacity>
              )}

              {/* Register link */}
              <View style={styles.registerRow}>
                <Text style={styles.registerPrompt}>No account? </Text>
                <TouchableOpacity onPress={() => navigation.navigate('Register')}>
                  <Text style={styles.registerLink}>Create Account</Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Footer */}
            <Text style={styles.footer}>
              Protected by 256-bit AES encryption · AGPL-3.0
            </Text>
          </Animated.View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:              { flex: 1, backgroundColor: COLORS.background },
  flex:              { flex: 1 },
  scroll:            { flexGrow: 1, justifyContent: 'center', padding: SPACING.lg },
  content:           { gap: SPACING.xl },
  brand:             { alignItems: 'center', gap: SPACING.sm },
  logoRing:          {
    width: 72, height: 72, borderRadius: 36,
    borderWidth: 2, borderColor: COLORS.accent,
    backgroundColor: COLORS.accentGlow,
    alignItems: 'center', justifyContent: 'center',
    ...SHADOW.accentGlow,
  },
  logoText:          { ...TEXT.h2, color: COLORS.accent, letterSpacing: 2 },
  brandName:         { ...TEXT.h1, color: COLORS.text, letterSpacing: 3 },
  brandTagline:      { ...TEXT.label, color: COLORS.textMuted },
  form:              {
    backgroundColor: COLORS.surface,
    borderRadius: RADIUS.xl,
    padding: SPACING.lg,
    borderWidth: 1,
    borderColor: COLORS.border,
    gap: SPACING.md,
    ...SHADOW.md,
  },
  formTitle:         { ...TEXT.h2, color: COLORS.text, marginBottom: SPACING.xs },
  errorBox:          {
    flexDirection: 'row', alignItems: 'center', gap: SPACING.sm,
    backgroundColor: COLORS.lossDim,
    borderRadius: RADIUS.sm, padding: SPACING.sm,
    borderWidth: 1, borderColor: COLORS.loss + '44',
  },
  errorText:         { ...TEXT.bodySM, color: COLORS.loss, flex: 1 },
  inputGroup:        { gap: SPACING.xs },
  inputLabel:        { ...TEXT.label, color: COLORS.textMuted },
  inputWrap:         {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: COLORS.surfaceAlt,
    borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border,
    paddingHorizontal: SPACING.sm,
  },
  inputIcon:         { marginRight: SPACING.xs },
  input:             {
    flex: 1, height: 48,
    color: COLORS.text, fontSize: 15,
    fontFamily: 'System',
  },
  inputPassword:     { paddingRight: 40 },
  eyeBtn:            { position: 'absolute', right: SPACING.sm, padding: 4 },
  forgotBtn:         { alignSelf: 'flex-end' },
  forgotText:        { ...TEXT.bodySM, color: COLORS.accent },
  loginBtn:          {
    backgroundColor: COLORS.accent,
    borderRadius: RADIUS.md, height: 52,
    alignItems: 'center', justifyContent: 'center',
    marginTop: SPACING.xs,
    ...SHADOW.accentGlow,
  },
  loginBtnDisabled:  { opacity: 0.5 },
  loginBtnText:      { color: COLORS.black, fontWeight: '800', fontSize: 15, letterSpacing: 2 },
  biometricBtn:      {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: SPACING.sm, height: 48,
    borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.borderAccent,
    backgroundColor: COLORS.accentGlow,
  },
  biometricText:     { ...TEXT.body, color: COLORS.accent, fontWeight: '600' },
  registerRow:       { flexDirection: 'row', justifyContent: 'center', marginTop: SPACING.xs },
  registerPrompt:    { ...TEXT.bodySM, color: COLORS.textMuted },
  registerLink:      { ...TEXT.bodySM, color: COLORS.accent, fontWeight: '700' },
  footer:            { ...TEXT.captionSM, color: COLORS.textDim, textAlign: 'center' },
});
