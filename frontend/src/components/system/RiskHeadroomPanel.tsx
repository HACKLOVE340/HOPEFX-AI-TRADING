/**
 * The live wiring for RiskHeadroom.
 *
 * Kept separate from the presentational component so the bar can be tested
 * without a network, and so the one rule that matters here lives in one place:
 * **when there is nothing measured, this renders nothing.**
 *
 * That is not a styling preference. `/api/risk/prop-firm-status` is gated to
 * the professional plan, so a 403 is an ordinary outcome, and the endpoint's
 * own fallback describes a default $100K account when no trades have been
 * recorded. A bar drawn from any of those would be a confident picture of
 * somebody else's account. Returning null is the honest render, and the
 * dashboard keeps its shape either way.
 */

import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { RiskHeadroom } from './RiskHeadroom';
import { Surface } from './Surface';
import { deriveConstraints, type PropFirmHeadroom } from '../../lib/risk_headroom';
import { propFirmApi } from '../../hooks/useApi';
import { useStore, selectAccount, selectIsAuth } from '../../store';
import { fmtPnl } from '../../lib/utils';

/** Money without a leading plus: headroom is a quantity, not a change. */
const money = (v: number): string => fmtPnl(v).replace(/^\+/, '');

export const RiskHeadroomPanel: React.FC<{ className?: string }> = ({ className = '' }) => {
  const isAuth = useStore(selectIsAuth);
  const account = useStore(selectAccount);

  const { data } = useQuery<PropFirmHeadroom | null>({
    queryKey: ['prop-firm-headroom'],
    queryFn: async () => {
      try {
        return ((await propFirmApi.status()).data ?? null) as PropFirmHeadroom | null;
      } catch {
        // A 403 is the expected answer below the professional plan, and a
        // failure here must never take the dashboard down with it. Unknown,
        // not zero — the margin constraint below still stands on its own.
        return null;
      }
    },
    enabled: isAuth,
    staleTime: 15_000,
    retry: false,
  });

  const constraints = deriveConstraints(data, account ?? undefined);
  if (constraints.length === 0) return null;

  return (
    <Surface className={className}>
      <RiskHeadroom constraints={constraints} format={money} />
    </Surface>
  );
};
