/**
 * pages/NuclearDashboardPage.tsx
 * Route wrapper for the nuclear AI trading dashboard.
 * Accessible at /nuclear
 */

import React from 'react';
import { NuclearDashboard } from '../features/chart-bot';

const NuclearDashboardPage: React.FC = () => (
  <div style={{ height: '100%', width: '100%', overflow: 'hidden' }}>
    <NuclearDashboard />
  </div>
);

export default NuclearDashboardPage;
