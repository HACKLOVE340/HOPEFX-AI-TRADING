/**
 * pages/GeopoliticalRiskPage.tsx
 *
 * Full-page geopolitical risk intelligence dashboard.
 * Wires /api/news/geopolitical/* endpoints via GeopoliticalPanel.
 */

import React from 'react';
import { GeopoliticalPanel } from '../features/chart-bot';

const GeopoliticalRiskPage: React.FC = () => (
  <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
    <h1 style={{ color: '#e2e8f0', fontFamily: 'monospace', marginBottom: 20 }}>
      Geopolitical Risk Intelligence
    </h1>
    <GeopoliticalPanel />
  </div>
);

export default GeopoliticalRiskPage;
