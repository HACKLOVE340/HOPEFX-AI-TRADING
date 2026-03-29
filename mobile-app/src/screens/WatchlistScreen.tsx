// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * screens/WatchlistScreen.tsx
 * ============================
 * Live price watchlist with add/remove and quick-trade navigation.
 */

import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, RefreshControl,
  TouchableOpacity, TextInput, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useWatchlist } from '../hooks/useWatchlist';
import { Card } from '../components/Card';
import { COLORS, SPACING, RADIUS } from '../utils/theme';
import { formatPct } from '../utils/formatters';
import { TradingStackParamList } from '../types';

type TradingNav = NativeStackNavigationProp<TradingStackParamList>;

export function WatchlistScreen() {
  const navigation = useNavigation<TradingNav>();
  const { symbols, quotes, isLoading, addSymbol, removeSymbol } = useWatchlist();
  const [newSymbol, setNewSymbol] = useState('');
  const [showInput, setShowInput] = useState(false);

  const handleAdd = async () => {
    const sym = newSymbol.trim().toUpperCase().replace('/', '');
    if (!sym) return;
    await addSymbol(sym);
    setNewSymbol('');
    setShowInput(false);
  };

  const handleRemove = (symbol: string) => {
    Alert.alert('Remove', `Remove ${symbol} from watchlist?`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: () => removeSymbol(symbol) },
    ]);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl refreshing={isLoading} onRefresh={() => {}} tintColor={COLORS.accent} />
        }
      >
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.pageTitle}>Watchlist</Text>
          <TouchableOpacity
            style={styles.addBtn}
            onPress={() => setShowInput((v) => !v)}
          >
            <Ionicons name={showInput ? 'close' : 'add'} size={20} color={COLORS.accent} />
          </TouchableOpacity>
        </View>

        {/* Add symbol input */}
        {showInput && (
          <View style={styles.inputRow}>
            <TextInput
              style={styles.input}
              value={newSymbol}
              onChangeText={setNewSymbol}
              placeholder="e.g. USDJPY"
              placeholderTextColor={COLORS.textMuted}
              autoCapitalize="characters"
              autoFocus
              onSubmitEditing={handleAdd}
            />
            <TouchableOpacity style={styles.inputBtn} onPress={handleAdd}>
              <Text style={styles.inputBtnText}>Add</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Symbol rows */}
        {symbols.map((symbol) => {
          const q = quotes[symbol];
          const isUp = (q?.change_pct ?? 0) >= 0;

          return (
            <Card key={symbol} style={styles.symbolCard}>
              <View style={styles.symbolRow}>
                {/* Left: symbol + change */}
                <View style={styles.symbolLeft}>
                  <Text style={styles.symbolName}>{symbol}</Text>
                  {q && (
                    <Text style={[styles.changePct, { color: isUp ? COLORS.profit : COLORS.loss }]}>
                      {formatPct(q.change_pct)}
                    </Text>
                  )}
                </View>

                {/* Center: bid/ask */}
                {q ? (
                  <View style={styles.priceBlock}>
                    <View style={styles.priceCol}>
                      <Text style={styles.priceLabel}>BID</Text>
                      <Text style={[styles.priceValue, { color: COLORS.sell }]}>
                        {q.bid.toFixed(2)}
                      </Text>
                    </View>
                    <View style={styles.spreadCol}>
                      <Text style={styles.spreadLabel}>SPR</Text>
                      <Text style={styles.spreadValue}>{q.spread.toFixed(1)}</Text>
                    </View>
                    <View style={styles.priceCol}>
                      <Text style={styles.priceLabel}>ASK</Text>
                      <Text style={[styles.priceValue, { color: COLORS.buy }]}>
                        {q.ask.toFixed(2)}
                      </Text>
                    </View>
                  </View>
                ) : (
                  <Text style={styles.noPrice}>—</Text>
                )}

                {/* Right: trade + remove */}
                <View style={styles.actions}>
                  <TouchableOpacity
                    style={styles.tradeBtn}
                    onPress={() =>
                      navigation.navigate('PlaceOrder', { symbol, side: 'buy' })
                    }
                  >
                    <Ionicons name="trending-up" size={14} color={COLORS.accent} />
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={styles.removeBtn}
                    onPress={() => handleRemove(symbol)}
                    hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                  >
                    <Ionicons name="close" size={14} color={COLORS.textMuted} />
                  </TouchableOpacity>
                </View>
              </View>
            </Card>
          );
        })}

        {symbols.length === 0 && (
          <Text style={styles.emptyText}>
            No symbols in watchlist. Tap + to add one.
          </Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe:        { flex: 1, backgroundColor: COLORS.background },
  content:     { padding: SPACING.md, gap: SPACING.sm, paddingBottom: SPACING.xl },
  header:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: SPACING.xs },
  pageTitle:   { color: COLORS.text, fontSize: 24, fontWeight: '800' },
  addBtn:      { width: 36, height: 36, borderRadius: 18, borderWidth: 1, borderColor: COLORS.accent, alignItems: 'center', justifyContent: 'center' },
  inputRow:    { flexDirection: 'row', gap: SPACING.sm },
  input:       { flex: 1, backgroundColor: COLORS.surfaceAlt, borderRadius: RADIUS.md, padding: SPACING.sm, color: COLORS.text, fontSize: 15, borderWidth: 1, borderColor: COLORS.border },
  inputBtn:    { backgroundColor: COLORS.accent, borderRadius: RADIUS.md, paddingHorizontal: SPACING.md, justifyContent: 'center' },
  inputBtnText:{ color: COLORS.white, fontWeight: '700', fontSize: 14 },
  symbolCard:  { padding: SPACING.sm },
  symbolRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACING.sm },
  symbolLeft:  { width: 72 },
  symbolName:  { color: COLORS.text, fontSize: 14, fontWeight: '700' },
  changePct:   { fontSize: 12, fontWeight: '600', marginTop: 2 },
  priceBlock:  { flex: 1, flexDirection: 'row', justifyContent: 'center', gap: SPACING.sm },
  priceCol:    { alignItems: 'center' },
  priceLabel:  { color: COLORS.textMuted, fontSize: 10, textTransform: 'uppercase' },
  priceValue:  { fontSize: 14, fontWeight: '700', fontFamily: 'Courier', marginTop: 2 },
  spreadCol:   { alignItems: 'center' },
  spreadLabel: { color: COLORS.textMuted, fontSize: 10 },
  spreadValue: { color: COLORS.textMuted, fontSize: 12, fontWeight: '600', marginTop: 2 },
  noPrice:     { flex: 1, color: COLORS.textMuted, textAlign: 'center' },
  actions:     { flexDirection: 'row', gap: SPACING.xs, alignItems: 'center' },
  tradeBtn:    { width: 30, height: 30, borderRadius: 15, borderWidth: 1, borderColor: COLORS.accent, alignItems: 'center', justifyContent: 'center' },
  removeBtn:   { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  emptyText:   { color: COLORS.textMuted, textAlign: 'center', paddingVertical: SPACING.xl },
});
