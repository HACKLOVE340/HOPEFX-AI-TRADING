// Fixture for scripts/find_tdz_reads.mjs — NOT application code.
//
// Everything here is legal and must NOT be reported. It pins the checker's
// three exemptions, each of which was a false positive on the first version:
//
//   1. the declaration precedes the render-time read (the fix);
//   2. an event handler may close over a const declared later — it runs after
//      the body has finished evaluating;
//   3. a name in a type position (`as { msg?: string }`) is erased at compile
//      time and is not a runtime read at all;
//   4. a `const` in an inner block shadows an outer one of the same name.
import React, { useState } from 'react';

const P: React.FC = () => {
  const [items] = useState<{ symbol: string; history: number[] }[]>([]);
  const [tickHistory] = useState<Record<string, number[]>>({});

  const enriched = items.map((item) => ({
    ...item,
    history: tickHistory[item.symbol] ?? item.history,
  }));

  // (2) legal: runs after the body evaluates.
  const onClick = () => console.log(laterConst);
  const laterConst = 42;

  // (3) `msg` here is a type member, not a variable read.
  const parse = (raw: unknown): string => {
    const d = raw as { msg?: string };
    return d.msg ?? '';
  };

  // (4) the inner `get` shadows the outer one declared below.
  function rates(source: Record<string, number>): number {
    if (source.nested) {
      const get = (k: string): number => source[k] ?? 0;
      return get('BTC');
    }
    const get = (k: string): number => source[k.toLowerCase()] ?? 0;
    return get('BTC');
  }

  return <div onClick={onClick}>{enriched.length}{parse('')}{rates({})}</div>;
};

export default P;
