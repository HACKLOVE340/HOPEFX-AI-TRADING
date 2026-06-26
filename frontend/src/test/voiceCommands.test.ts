/**
 * voiceCommands — tests for the spoken-command intent parser.
 *
 * The parser is pure and never executes anything; these tests pin down how raw
 * speech maps to intents, that trade/kill-switch are flagged privileged, and
 * that unrecognised speech falls back to a harmless chat intent.
 */
import { describe, it, expect } from 'vitest';
import { parseVoiceCommand, describeIntent } from '../lib/voiceCommands';

describe('parseVoiceCommand — trades', () => {
  it('parses "buy 1 lot gold"', () => {
    const i = parseVoiceCommand('buy 1 lot gold');
    expect(i).toMatchObject({ kind: 'trade', side: 'buy', quantity: 1, symbol: 'XAUUSD', privileged: true });
  });

  it('parses "sell 0.5 XAUUSD"', () => {
    const i = parseVoiceCommand('sell 0.5 XAUUSD');
    expect(i).toMatchObject({ kind: 'trade', side: 'sell', quantity: 0.5, symbol: 'XAUUSD' });
  });

  it('maps "short" to sell and "long" to buy', () => {
    expect(parseVoiceCommand('short two silver')).toMatchObject({ kind: 'trade', side: 'sell', quantity: 2, symbol: 'XAGUSD' });
    expect(parseVoiceCommand('long three euro')).toMatchObject({ kind: 'trade', side: 'buy', quantity: 3, symbol: 'EURUSD' });
  });

  it('resolves spelled-out quantities', () => {
    expect(parseVoiceCommand('buy two lots gold')).toMatchObject({ quantity: 2, symbol: 'XAUUSD' });
  });

  it('accepts a raw 6-letter pair', () => {
    expect(parseVoiceCommand('buy 1 audusd')).toMatchObject({ kind: 'trade', symbol: 'AUDUSD' });
  });

  it('does NOT produce a trade without a quantity', () => {
    // "buy gold" alone has no qty → not a trade; falls through to chat.
    expect(parseVoiceCommand('buy gold').kind).toBe('chat');
  });
});

describe('parseVoiceCommand — kill switch', () => {
  it.each([
    'kill switch',
    'emergency stop',
    'stop all trading',
    'halt trading',
    'flatten everything',
  ])('recognises "%s"', (phrase) => {
    const i = parseVoiceCommand(phrase);
    expect(i).toMatchObject({ kind: 'kill_switch', privileged: true });
  });
});

describe('parseVoiceCommand — queries (not privileged)', () => {
  it('parses P&L', () => {
    expect(parseVoiceCommand("what's my pnl")).toMatchObject({ kind: 'query', topic: 'pnl', privileged: false });
  });
  it('parses balance', () => {
    expect(parseVoiceCommand('show my balance')).toMatchObject({ kind: 'query', topic: 'balance' });
  });
  it('parses positions', () => {
    expect(parseVoiceCommand('what is open')).toMatchObject({ kind: 'query', topic: 'positions' });
  });
  it('parses risk', () => {
    expect(parseVoiceCommand('what is my drawdown')).toMatchObject({ kind: 'query', topic: 'risk' });
  });
});

describe('parseVoiceCommand — fallback', () => {
  it('falls back to chat for unrecognised speech', () => {
    const i = parseVoiceCommand('tell me a joke about gold');
    expect(i).toMatchObject({ kind: 'chat', privileged: false });
    if (i.kind === 'chat') expect(i.text).toContain('joke');
  });

  it('handles empty input safely', () => {
    expect(parseVoiceCommand('').kind).toBe('chat');
  });
});

describe('describeIntent', () => {
  it('summarises a trade', () => {
    const i = parseVoiceCommand('buy 1 lot gold');
    expect(describeIntent(i)).toBe('BUY 1 XAUUSD');
  });
  it('summarises the kill switch', () => {
    expect(describeIntent(parseVoiceCommand('kill switch'))).toMatch(/KILL SWITCH/);
  });
});
