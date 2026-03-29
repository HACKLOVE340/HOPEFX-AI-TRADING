// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * hooks/useOrders.ts
 * ==================
 * Fetch and manage open orders with optimistic cancel support.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTradingStore } from '../store/tradingStore';
import { Order } from '../types';

export function useOrders() {
  const { orders, fetchOrders, cancelOrder, isLoading, error } = useTradingStore();
  const [cancelling, setCancelling] = useState<string | null>(null);

  useEffect(() => {
    fetchOrders();
  }, []);

  const handleCancel = useCallback(
    async (orderId: string) => {
      setCancelling(orderId);
      try {
        await cancelOrder(orderId);
      } finally {
        setCancelling(null);
      }
    },
    [cancelOrder]
  );

  const openOrders = orders.filter(
    (o) => o.status === 'open' || o.status === 'pending'
  );
  const filledOrders = orders.filter((o) => o.status === 'filled');

  return {
    orders,
    openOrders,
    filledOrders,
    isLoading,
    error,
    cancelling,
    refresh: fetchOrders,
    cancelOrder: handleCancel,
  };
}
