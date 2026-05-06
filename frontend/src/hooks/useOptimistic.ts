/**
 * hooks/useOptimistic.ts
 *
 * Lightweight optimistic-update helper for list mutations.
 * Applies an immediate local state change, then rolls back on error.
 *
 * Usage:
 *   const [items, optimistic] = useOptimistic(serverItems);
 *
 *   // Add optimistically
 *   optimistic.add(newItem);
 *
 *   // Remove optimistically
 *   optimistic.remove((i) => i.id !== deletedId);
 *
 *   // Update optimistically
 *   optimistic.update((i) => i.id === id ? { ...i, ...patch } : i);
 *
 *   // Rollback on error
 *   optimistic.rollback();
 *
 *   // Commit (accept server state)
 *   optimistic.commit(serverItems);
 */

import { useCallback, useRef, useState } from 'react';

interface OptimisticActions<T> {
  /** Append an item to the local list immediately. */
  add:      (item: T) => void;
  /** Remove items matching the predicate immediately. */
  remove:   (predicate: (item: T) => boolean) => void;
  /** Map over items to apply a patch immediately. */
  update:   (mapper: (item: T) => T) => void;
  /** Restore the last committed server state. */
  rollback: () => void;
  /** Accept new server state as the committed baseline. */
  commit:   (items: T[]) => void;
}

export function useOptimistic<T>(
  serverItems: T[],
): [T[], OptimisticActions<T>] {
  const [items, setItems] = useState<T[]>(serverItems);
  const committedRef = useRef<T[]>(serverItems);

  // Sync when server data changes (e.g. query refetch)
  const prevServerRef = useRef<T[]>(serverItems);
  if (prevServerRef.current !== serverItems) {
    prevServerRef.current = serverItems;
    committedRef.current  = serverItems;
    setItems(serverItems);
  }

  const add = useCallback((item: T) => {
    setItems((prev) => [...prev, item]);
  }, []);

  const remove = useCallback((predicate: (item: T) => boolean) => {
    setItems((prev) => prev.filter(predicate));
  }, []);

  const update = useCallback((mapper: (item: T) => T) => {
    setItems((prev) => prev.map(mapper));
  }, []);

  const rollback = useCallback(() => {
    setItems(committedRef.current);
  }, []);

  const commit = useCallback((newItems: T[]) => {
    committedRef.current = newItems;
    setItems(newItems);
  }, []);

  return [items, { add, remove, update, rollback, commit }];
}
