/**
 * News & Sentiment — market news feed with AI sentiment scoring.
 *
 * Wires to the roadmap news router:
 *   GET /api/sentiment/latest
 *   GET /api/news/feed
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { newsApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

interface Sentiment {
  symbol?: string; overall_score?: number; news_count?: number;
  bullish_pct?: number; bearish_pct?: number; neutral_pct?: number; nuclear_alert?: boolean;
}
interface Article {
  id?: string; title?: string; source?: string; published_at?: string; url?: string;
  sentiment?: string; impact?: string; nuclear_score?: number; summary?: string;
}

const SENT_COLOR: Record<string, string> = {
  bullish: '#4ade80', positive: '#4ade80', bearish: '#f87171', negative: '#f87171', neutral: '#94a3b8',
};
const IMPACT_COLOR: Record<string, string> = { high: '#f87171', medium: '#fbbf24', low: '#64748b' };

const NewsSentiment: React.FC = () => {
  const [sentiment, setSentiment] = useState<Sentiment | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const mountedRef = useRef(true);

  const load = useCallback(async () => {
    setErr('');
    const [s, f] = await Promise.allSettled([newsApi.sentimentLatest(), newsApi.feed({ limit: 50 })]);
    if (!mountedRef.current) return;
    if (s.status === 'fulfilled') setSentiment(s.value.data ?? null);
    if (f.status === 'fulfilled') setArticles(f.value.data?.articles ?? []);
    if (s.status === 'rejected' && f.status === 'rejected') {
      setErr(extractApiError(f.reason, 'Failed to load news & sentiment.'));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    load();
    const id = window.setInterval(load, 60000);
    return () => { mountedRef.current = false; window.clearInterval(id); };
  }, [load]);

  const tiles = [
    { label: 'Sentiment', value: sentiment?.overall_score != null ? sentiment.overall_score.toFixed(1) : '—' },
    { label: 'Bullish', value: sentiment?.bullish_pct != null ? `${sentiment.bullish_pct}%` : '—' },
    { label: 'Bearish', value: sentiment?.bearish_pct != null ? `${sentiment.bearish_pct}%` : '—' },
    { label: 'Articles', value: sentiment?.news_count != null ? String(sentiment.news_count) : '—' },
  ];

  return (
    <div style={{ padding: 20, maxWidth: 900, margin: '0 auto', color: '#e2e8f0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>📰 News & Sentiment</h1>
        <button onClick={load} style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>↻ Refresh</button>
      </div>

      {sentiment?.nuclear_alert && (
        <div style={{ padding: '10px 14px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16, fontWeight: 600 }}>
          ☢️ Nuclear sentiment alert active for {sentiment.symbol ?? 'the market'}.
        </div>
      )}

      {loading && <div style={{ color: '#64748b', padding: 20 }}>Loading news…</div>}
      {!loading && err && (
        <div style={{ padding: '12px 16px', background: '#2a1215', border: '1px solid #7f1d1d', borderRadius: 8, color: '#fca5a5', marginBottom: 16 }}>{err}</div>
      )}

      {!loading && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, marginBottom: 20 }}>
            {tiles.map((t) => (
              <div key={t.label} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{t.label}</div>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{t.value}</div>
              </div>
            ))}
          </div>

          {articles.length === 0 ? (
            <div style={{ color: '#64748b', padding: 20, textAlign: 'center', background: '#1e293b', border: '1px solid #334155', borderRadius: 10 }}>No recent news.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {articles.map((a, i) => (
                <a key={a.id ?? i} href={a.url || undefined} target="_blank" rel="noreferrer"
                  style={{ display: 'block', background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '12px 16px', textDecoration: 'none', color: 'inherit' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ flex: 1, minWidth: 200, fontWeight: 600 }}>{a.title || '(untitled)'}</span>
                    {a.sentiment && <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: SENT_COLOR[a.sentiment.toLowerCase()] ?? '#94a3b8' }}>{a.sentiment}</span>}
                    {a.impact && <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', color: IMPACT_COLOR[a.impact.toLowerCase()] ?? '#64748b' }}>{a.impact}</span>}
                  </div>
                  {a.summary && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{a.summary}</div>}
                  <div style={{ fontSize: 11, color: '#475569', marginTop: 4 }}>{a.source ?? ''}{a.published_at ? ` · ${a.published_at}` : ''}</div>
                </a>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default NewsSentiment;
