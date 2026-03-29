// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/AlertsScreen.tsx
 * ========================
 * Price alerts management: create, view, and delete price alerts.
 * Wired to /api/alerts endpoints on the backend.
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, TextInput, Alert, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { apiClient } from '../services/apiClient';
import { Card } from '../components/Card';
import { ErrorBanner } from '../components/ErrorBanner';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import { formatDateTime } from '../utils/formatters';

interface PriceAlert {
  id: string;
  symbol: string;
  condition: 'above' | 'below';
  price: number;
  triggered: boolean;
  triggered_at: string | null;
  created_at: string;
  note: string;
}

const SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD'];

export function AlertsScreen() {
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [symbol, setSymbol] = useState('XAUUSD');
  const [condition, setCondition] = useState<'above' | 'below'>('above');
  const [price, setPrice] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<PriceAlert[]>('/api/alerts');
      setAlerts(res.data ?? []);
    } catch {
      setError('Failed to load alerts');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    const priceNum = parseFloat(price);
    if (!price || isNaN(priceNum) || priceNum <= 0) {
      Alert.alert('Invalid Price', 'Enter a valid price above 0.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiClient.post<PriceAlert>('/api/alerts', {
        symbol,
        condition,
        price: priceNum,
        note,
      });
      setAlerts((prev) => [res.data, ...prev]);
      setShowForm(false);
      setPrice('');
      setNote('');
    } catch {
      Alert.alert('Error', 'Failed to create alert. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = (alertId: string) => {
    Alert.alert('Delete Alert', 'Remove this price alert?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.delete(`/api/alerts/${alertId}`);
            setAlerts((prev) => prev.filter((a) => a.id !== alertId));
          } catch {
            Alert.alert('Error', 'Failed to delete alert.');
          }
        },
      },
    ]);
  };

  const active = alerts.filter((a) => !a.triggered);
  const triggered = alerts.filter((a) => a.triggered);

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={isLoading} onRefresh={load} tintColor={COLORS.accent} />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.pageTitle}>Price Alerts</Text>
          <TouchableOpacity
            style={styles.addBtn}
            onPress={() => setShowForm((v) => !v)}
          >
            <Ionicons
              name={showForm ? 'close' : 'add'}
              size={20}
              color={COLORS.accent}
            />
            <Text style={styles.addBtnText}>{showForm ? 'Cancel' : 'New Alert'}</Text>
          </TouchableOpacity>
        </View>

        {error && <ErrorBanner message={error} />}

        {/* Create form */}
        {showForm && (
          <Card style={styles.formCard}>
            <Text style={styles.formTitle}>New Price Alert</Text>

            {/* Symbol picker */}
            <Text style={styles.fieldLabel}>Symbol</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
              {SYMBOLS.map((s) => (
                <TouchableOpacity
                  key={s}
                  style={[styles.chip, symbol === s && styles.chipActive]}
                  onPress={() => setSymbol(s)}
                >
                  <Text style={[styles.chipText, symbol === s && styles.chipTextActive]}>{s}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>

            {/* Condition */}
            <Text style={styles.fieldLabel}>Condition</Text>
            <View style={styles.conditionRow}>
              {(['above', 'below'] as const).map((c) => (
                <TouchableOpacity
                  key={c}
                  style={[styles.condBtn, condition === c && styles.condBtnActive]}
                  onPress={() => setCondition(c)}
                >
                  <Ionicons
                    name={c === 'above' ? 'arrow-up' : 'arrow-down'}
                    size={14}
                    color={condition === c ? COLORS.white : COLORS.textMuted}
                  />
                  <Text style={[styles.condText, condition === c && styles.condTextActive]}>
                    Price {c}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Price input */}
            <Text style={styles.fieldLabel}>Target Price</Text>
            <TextInput
              style={styles.input}
              value={price}
              onChangeText={setPrice}
              keyboardType="decimal-pad"
              placeholder="e.g. 2050.00"
              placeholderTextColor={COLORS.textMuted}
            />

            {/* Note */}
            <Text style={styles.fieldLabel}>Note (optional)</Text>
            <TextInput
              style={styles.input}
              value={note}
              onChangeText={setNote}
              placeholder="e.g. Key resistance level"
              placeholderTextColor={COLORS.textMuted}
            />

            <TouchableOpacity
              style={[styles.submitBtn, submitting && styles.submitBtnDisabled]}
              onPress={handleCreate}
              disabled={submitting}
            >
              {submitting ? (
                <ActivityIndicator color={COLORS.white} size="small" />
              ) : (
                <Text style={styles.submitBtnText}>Create Alert</Text>
              )}
            </TouchableOpacity>
          </Card>
        )}

        {/* Active alerts */}
        <Text style={styles.sectionTitle}>
          Active ({active.length})
        </Text>
        {active.length === 0 ? (
          <Text style={styles.emptyText}>No active alerts. Tap "New Alert" to create one.</Text>
        ) : (
          active.map((alert) => (
            <AlertRow key={alert.id} alert={alert} onDelete={handleDelete} />
          ))
        )}

        {/* Triggered alerts */}
        {triggered.length > 0 && (
          <>
            <Text style={styles.sectionTitle}>Triggered ({triggered.length})</Text>
            {triggered.map((alert) => (
              <AlertRow key={alert.id} alert={alert} onDelete={handleDelete} triggered />
            ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function AlertRow({
  alert,
  onDelete,
  triggered = false,
}: {
  alert: PriceAlert;
  onDelete: (id: string) => void;
  triggered?: boolean;
}) {
  return (
    <Card style={[styles.alertCard, triggered && styles.alertTriggered]}>
      <View style={styles.alertRow}>
        <View style={styles.alertLeft}>
          <View style={styles.alertSymbolRow}>
            <Text style={styles.alertSymbol}>{alert.symbol}</Text>
            <View style={[
              styles.conditionBadge,
              { backgroundColor: alert.condition === 'above' ? COLORS.profit + '22' : COLORS.loss + '22' },
            ]}>
              <Ionicons
                name={alert.condition === 'above' ? 'arrow-up' : 'arrow-down'}
                size={10}
                color={alert.condition === 'above' ? COLORS.profit : COLORS.loss}
              />
              <Text style={[
                styles.conditionBadgeText,
                { color: alert.condition === 'above' ? COLORS.profit : COLORS.loss },
              ]}>
                {alert.condition}
              </Text>
            </View>
          </View>
          <Text style={styles.alertPrice}>{alert.price.toFixed(2)}</Text>
          {alert.note ? <Text style={styles.alertNote}>{alert.note}</Text> : null}
          <Text style={styles.alertMeta}>
            {triggered && alert.triggered_at
              ? `Triggered ${formatDateTime(alert.triggered_at)}`
              : `Created ${formatDateTime(alert.created_at)}`}
          </Text>
        </View>
        <TouchableOpacity
          style={styles.deleteBtn}
          onPress={() => onDelete(alert.id)}
          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        >
          <Ionicons name="trash-outline" size={18} color={COLORS.loss} />
        </TouchableOpacity>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  safe:              { flex: 1, backgroundColor: COLORS.background },
  content:           { padding: SPACING.md, gap: SPACING.md, paddingBottom: SPACING.xl },
  header:            { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  pageTitle:         { color: COLORS.text, fontSize: 24, fontWeight: '800' },
  addBtn:            { flexDirection: 'row', alignItems: 'center', gap: 4, padding: SPACING.sm, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.accent },
  addBtnText:        { color: COLORS.accent, fontSize: 13, fontWeight: '700' },
  formCard:          { gap: SPACING.sm },
  formTitle:         { color: COLORS.text, fontSize: 16, fontWeight: '700' },
  fieldLabel:        { color: COLORS.textMuted, fontSize: 12, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.3 },
  chipRow:           { flexDirection: 'row' },
  chip:              { paddingHorizontal: SPACING.md, paddingVertical: 6, borderRadius: RADIUS.full, borderWidth: 1, borderColor: COLORS.border, marginRight: SPACING.xs },
  chipActive:        { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  chipText:          { color: COLORS.textMuted, fontSize: 12, fontWeight: '600' },
  chipTextActive:    { color: COLORS.white },
  conditionRow:      { flexDirection: 'row', gap: SPACING.sm },
  condBtn:           { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4, paddingVertical: SPACING.sm, borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  condBtnActive:     { backgroundColor: COLORS.accent, borderColor: COLORS.accent },
  condText:          { color: COLORS.textMuted, fontSize: 13, fontWeight: '600' },
  condTextActive:    { color: COLORS.white },
  input:             { backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, padding: SPACING.sm, color: COLORS.text, fontSize: 15, borderWidth: 1, borderColor: COLORS.border },
  submitBtn:         { backgroundColor: COLORS.accent, borderRadius: RADIUS.md, padding: SPACING.md, alignItems: 'center' },
  submitBtnDisabled: { opacity: 0.6 },
  submitBtnText:     { color: COLORS.white, fontWeight: '700', fontSize: 15 },
  sectionTitle:      { color: COLORS.text, fontSize: 16, fontWeight: '700' },
  emptyText:         { color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.xl },
  alertCard:         { padding: SPACING.sm },
  alertTriggered:    { opacity: 0.6 },
  alertRow:          { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  alertLeft:         { flex: 1, gap: 3 },
  alertSymbolRow:    { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  alertSymbol:       { color: COLORS.text, fontSize: 15, fontWeight: '700' },
  conditionBadge:    { flexDirection: 'row', alignItems: 'center', gap: 2, paddingHorizontal: 6, paddingVertical: 2, borderRadius: RADIUS.sm },
  conditionBadgeText:{ fontSize: 11, fontWeight: '700' },
  alertPrice:        { color: COLORS.text, fontSize: 18, fontWeight: '800', fontFamily: 'Courier' },
  alertNote:         { color: COLORS.textMuted, fontSize: 12 },
  alertMeta:         { color: COLORS.textDim, fontSize: 11 },
  deleteBtn:         { padding: SPACING.sm },
});
