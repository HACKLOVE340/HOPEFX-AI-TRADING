// HOPEFX-AI-TRADING — AGPL-3.0
import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useAuthStore } from '../../store/authStore';
import { COLORS, SPACING, RADIUS, TEXT, SHADOW } from '../../utils/theme';
import { AuthStackParamList } from '../../types';

type Nav = NativeStackNavigationProp<AuthStackParamList>;

export function RegisterScreen() {
  const navigation = useNavigation<Nav>();
  const { register, isLoading, error, clearError } = useAuthStore();
  const [username, setUsername] = useState('');
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);

  const handleRegister = async () => {
    if (!username || !email || !password) return;
    clearError();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    await register(email.trim().toLowerCase(), password, username.trim());
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <TouchableOpacity style={styles.backBtn} onPress={() => navigation.goBack()}>
            <Ionicons name="arrow-back" size={22} color={COLORS.textSecondary} />
          </TouchableOpacity>
          <Text style={styles.title}>Create Account</Text>
          <Text style={styles.subtitle}>Join HopeFX institutional trading</Text>

          {error && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          {[
            { label: 'USERNAME', value: username, setter: setUsername, placeholder: 'trader_name', icon: 'person-outline', type: 'default' as const },
            { label: 'EMAIL',    value: email,    setter: setEmail,    placeholder: 'you@hopefx.io', icon: 'mail-outline',   type: 'email-address' as const },
          ].map(({ label, value, setter, placeholder, icon, type }) => (
            <View key={label} style={styles.inputGroup}>
              <Text style={styles.inputLabel}>{label}</Text>
              <View style={styles.inputWrap}>
                <Ionicons name={icon as any} size={18} color={COLORS.textMuted} style={styles.inputIcon} />
                <TextInput style={styles.input} value={value} onChangeText={setter} placeholder={placeholder} placeholderTextColor={COLORS.textDim} keyboardType={type} autoCapitalize="none" selectionColor={COLORS.accent} />
              </View>
            </View>
          ))}

          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>PASSWORD</Text>
            <View style={styles.inputWrap}>
              <Ionicons name="lock-closed-outline" size={18} color={COLORS.textMuted} style={styles.inputIcon} />
              <TextInput style={[styles.input, { paddingRight: 40 }]} value={password} onChangeText={setPassword} placeholder="Min 8 characters" placeholderTextColor={COLORS.textDim} secureTextEntry={!showPass} selectionColor={COLORS.accent} />
              <TouchableOpacity onPress={() => setShowPass(!showPass)} style={styles.eyeBtn}>
                <Ionicons name={showPass ? 'eye-off-outline' : 'eye-outline'} size={18} color={COLORS.textMuted} />
              </TouchableOpacity>
            </View>
          </View>

          <TouchableOpacity style={[styles.btn, isLoading && styles.btnDisabled]} onPress={handleRegister} disabled={isLoading || !username || !email || !password}>
            {isLoading ? <ActivityIndicator color={COLORS.black} /> : <Text style={styles.btnText}>CREATE ACCOUNT</Text>}
          </TouchableOpacity>

          <View style={styles.loginRow}>
            <Text style={styles.loginPrompt}>Already have an account? </Text>
            <TouchableOpacity onPress={() => navigation.navigate('Login')}>
              <Text style={styles.loginLink}>Sign In</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: COLORS.background },
  flex:        { flex: 1 },
  scroll:      { flexGrow: 1, padding: SPACING.lg, gap: SPACING.md },
  backBtn:     { width: 40, height: 40, alignItems: 'center', justifyContent: 'center', marginBottom: SPACING.sm },
  title:       { ...TEXT.h1, color: COLORS.text },
  subtitle:    { ...TEXT.body, color: COLORS.textMuted },
  errorBox:    { backgroundColor: COLORS.lossDim, borderRadius: RADIUS.sm, padding: SPACING.sm, borderWidth: 1, borderColor: COLORS.loss + '44' },
  errorText:   { ...TEXT.bodySM, color: COLORS.loss },
  inputGroup:  { gap: SPACING.xs },
  inputLabel:  { ...TEXT.label, color: COLORS.textMuted },
  inputWrap:   { flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border, paddingHorizontal: SPACING.sm },
  inputIcon:   { marginRight: SPACING.xs },
  input:       { flex: 1, height: 48, color: COLORS.text, fontSize: 15 },
  eyeBtn:      { position: 'absolute', right: SPACING.sm, padding: 4 },
  btn:         { backgroundColor: COLORS.accent, borderRadius: RADIUS.md, height: 52, alignItems: 'center', justifyContent: 'center', ...SHADOW.accentGlow },
  btnDisabled: { opacity: 0.5 },
  btnText:     { color: COLORS.black, fontWeight: '800', fontSize: 15, letterSpacing: 2 },
  loginRow:    { flexDirection: 'row', justifyContent: 'center' },
  loginPrompt: { ...TEXT.bodySM, color: COLORS.textMuted },
  loginLink:   { ...TEXT.bodySM, color: COLORS.accent, fontWeight: '700' },
});
