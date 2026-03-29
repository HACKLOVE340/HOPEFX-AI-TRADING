// HOPEFX-AI-TRADING — AGPL-3.0
import { useCallback } from 'react';
import { useFocusEffect } from '@react-navigation/native';

/** Re-run `fn` every time the screen comes into focus. */
export function useRefreshOnFocus(fn: () => void | Promise<void>) {
  const stableFn = useCallback(() => {
    fn();
  }, [fn]);

  useFocusEffect(stableFn);
}
