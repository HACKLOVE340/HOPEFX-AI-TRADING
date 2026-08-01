/**
 * voiceCommands — parse a spoken phrase into a structured intent.
 *
 * Pure and side-effect-free (easy to unit-test). It NEVER executes anything —
 * callers decide what to do, and a trade intent must always be confirmed by the
 * user before it touches the order API (which is itself invariant-gated server
 * side). Trading/admin intents are surfaced only to authorised roles by the UI.
 */

export type VoiceIntentKind = 'trade' | 'kill_switch' | 'query' | 'chat';

export interface TradeIntent {
  kind: 'trade';
  side: 'buy' | 'sell';
  quantity: number;
  symbol: string;
  /** Privileged: routes to the order path; UI restricts to authorised roles. */
  privileged: true;
}
export interface KillSwitchIntent {
  kind: 'kill_switch';
  privileged: true;
}
export interface QueryIntent {
  kind: 'query';
  topic: 'pnl' | 'balance' | 'positions' | 'risk';
  privileged: false;
}
export interface ChatIntent {
  kind: 'chat';
  text: string;
  privileged: false;
}
export type VoiceIntent = TradeIntent | KillSwitchIntent | QueryIntent | ChatIntent;

/** Spoken-word → instrument symbol. Extend as the tradable universe grows. */
const SYMBOL_ALIASES: Record<string, string> = {
  gold: 'XAUUSD', xau: 'XAUUSD', xauusd: 'XAUUSD',
  silver: 'XAGUSD', xag: 'XAGUSD',
  euro: 'EURUSD', eurusd: 'EURUSD',
  cable: 'GBPUSD', pound: 'GBPUSD', gbpusd: 'GBPUSD',
  dollar: 'USD', yen: 'USDJPY', usdjpy: 'USDJPY',
  bitcoin: 'BTCUSD', btc: 'BTCUSD', btcusd: 'BTCUSD',
};

const WORD_NUMBERS: Record<string, number> = {
  a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5,
  six: 6, seven: 7, eight: 8, nine: 9, ten: 10, half: 0.5,
};

function resolveSymbol(token: string): string | null {
  const t = token.toLowerCase().replace(/[^a-z]/g, '');
  if (SYMBOL_ALIASES[t]) return SYMBOL_ALIASES[t];
  if (/^[a-z]{6}$/.test(t)) return t.toUpperCase(); // raw 6-letter pair, e.g. audusd
  return null;
}

function resolveQuantity(token: string): number | null {
  if (WORD_NUMBERS[token] !== undefined) return WORD_NUMBERS[token];
  const n = Number.parseFloat(token);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Parse `raw` into a VoiceIntent. Returns a `chat` intent (the safe default) when
 * nothing trade/admin/query-shaped is recognised.
 */
export function parseVoiceCommand(raw: string): VoiceIntent {
  const text = (raw ?? '').trim();
  const low = text.toLowerCase();

  // Kill switch / emergency stop (highest priority).
  if (/\b(kill switch|emergency stop|stop all (trading|trades|orders)|halt trading|flatten everything)\b/.test(low)) {
    return { kind: 'kill_switch', privileged: true };
  }

  // Trade: "buy/sell <qty> [lot(s)] <symbol>" or "buy <symbol> <qty>".
  const tradeMatch = low.match(
    /\b(buy|long|sell|short)\b\s+(?:([\d.]+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|half)\s+)?(?:lots?\s+(?:of\s+)?)?([a-z]{3,6})/,
  );
  if (tradeMatch) {
    const side: 'buy' | 'sell' = tradeMatch[1] === 'sell' || tradeMatch[1] === 'short' ? 'sell' : 'buy';
    const symbol = resolveSymbol(tradeMatch[3] ?? '');
    // Quantity may precede or follow the symbol ("buy gold 2 lots").
    let qty = tradeMatch[2] ? resolveQuantity(tradeMatch[2]) : null;
    if (qty === null) {
      const after = low.slice(tradeMatch.index ?? 0).match(/\b([\d.]+)\s*lots?\b/);
      if (after?.[1]) qty = resolveQuantity(after[1]);
    }
    if (symbol && qty && qty > 0) {
      return { kind: 'trade', side, quantity: qty, symbol, privileged: true };
    }
  }

  // Read-only queries.
  if (/\b(p\s*&?\s*l|pnl|profit (and|&) loss|how (am i|are we) doing)\b/.test(low)) {
    return { kind: 'query', topic: 'pnl', privileged: false };
  }
  if (/\b(balance|equity|how much (do i have|cash))\b/.test(low)) {
    return { kind: 'query', topic: 'balance', privileged: false };
  }
  if (/\b(positions?|what(?:'s| is) open|open trades?)\b/.test(low)) {
    return { kind: 'query', topic: 'positions', privileged: false };
  }
  if (/\b(risk|drawdown|exposure|var\b)\b/.test(low)) {
    return { kind: 'query', topic: 'risk', privileged: false };
  }

  return { kind: 'chat', text, privileged: false };
}

/** Human-readable confirmation prompt for a privileged intent. */
export function describeIntent(intent: VoiceIntent): string {
  switch (intent.kind) {
    case 'trade':
      return `${intent.side.toUpperCase()} ${intent.quantity} ${intent.symbol}`;
    case 'kill_switch':
      return 'ACTIVATE KILL SWITCH — cancel all orders and halt trading';
    case 'query':
      return `Show ${intent.topic}`;
    default:
      return intent.text;
  }
}
