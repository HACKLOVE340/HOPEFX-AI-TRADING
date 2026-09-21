/**
 * hub/pronunciation.ts — saying the terms out loud so they mean something.
 *
 * §17 asks for "a pronunciation dictionary for names and financial terms".
 * This is not cosmetic. The presence speaks unprompted in exactly one
 * situation — an alert — and "XAUUSD" read letter by letter, or worse
 * phonetically, is unintelligible precisely when the operator most needs to
 * hear it without looking. A spoken alert the operator has to read anyway is
 * not a spoken alert.
 *
 * ## Whole tokens only
 *
 * A naive `replace` turns `PIPELINE` into `point-in-percentageELINE`. The
 * boundary check is the whole reason this is a module rather than three lines
 * at the call site.
 *
 * ## It never returns nothing
 *
 * A dictionary that could empty an utterance would silence an alert, which is
 * a worse failure than mispronouncing it.
 */

/** Term to spoken form. Keys are matched case-insensitively as whole tokens. */
export const PRONUNCIATIONS: Record<string, string> = {
  XAUUSD: 'gold',
  XAGUSD: 'silver',
  'P&L': 'profit and loss',
  PNL: 'profit and loss',
  SL: 'stop loss',
  TP: 'take profit',
  DD: 'drawdown',
  VAR: 'value at risk',
  CVAR: 'conditional value at risk',
  OMS: 'order management system',
  FX: 'foreign exchange',
  PIP: 'point in percentage',
  BPS: 'basis points',
  ATR: 'average true range',
  RSI: 'relative strength index',
  EMA: 'exponential moving average',
  MTM: 'mark to market',
  FTMO: 'F-T-M-O',
  OANDA: 'oh-anda',
  MT5: 'MetaTrader 5',
  IBKR: 'Interactive Brokers',
};

/** Characters that may sit inside a term, so `P&L` matches as one token. */
const TOKEN = /[A-Za-z0-9&]+/g;

export function pronounce(utterance: string): string {
  if (!utterance) return utterance;

  const spoken = utterance.replace(TOKEN, (token) => {
    const replacement = PRONUNCIATIONS[token.toUpperCase()];
    return replacement ?? token;
  });

  // A dictionary that could empty an utterance would silence an alert, which
  // is worse than mispronouncing one.
  return spoken.trim() ? spoken : utterance;
}
