// Fixture for scripts/find_tdz_reads.mjs — NOT application code.
//
// This is the exact shape that shipped in Watchlist.tsx and crashed the page
// with "Cannot access 'N' before initialization". It is kept outside `src` so
// `tsc --noEmit` (include: ["src"]) never compiles it, and so the checker's own
// sweep of `src` stays clean.
//
// If the checker stops reporting this file, the checker is blind.
import React, { useState } from 'react';

const P: React.FC = () => {
  const [items] = useState<{ symbol: string; history: number[] }[]>([]);

  // Reads `tickHistory` during render, above its declaration → throws.
  const enriched = items.map((item) => ({
    ...item,
    history: tickHistory[item.symbol] ?? item.history,
  }));

  const [tickHistory] = useState<Record<string, number[]>>({});

  return <div>{enriched.length}{Object.keys(tickHistory).length}</div>;
};

export default P;
