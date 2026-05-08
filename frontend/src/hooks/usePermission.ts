import { useCallback, useEffect, useState } from 'react';
import * as MediaLibrary from 'expo-media-library';

import {
  readPermissionState,
  writePermissionState,
  type PermissionState,
} from '@/services/storage.service';

export interface UsePermissionResult {
  ready: boolean;
  state: PermissionState | null;
  request: () => Promise<PermissionState>;
  deny: () => Promise<void>;
}

export function usePermission(): UsePermissionResult {
  const [ready, setReady] = useState(false);
  const [state, setState] = useState<PermissionState | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await readPermissionState();
      if (cancelled) return;
      setState(stored);
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const request = useCallback(async (): Promise<PermissionState> => {
    const result = await MediaLibrary.requestPermissionsAsync();
    const granted: PermissionState = result.granted ? 'granted' : 'denied';
    await writePermissionState(granted);
    setState(granted);
    return granted;
  }, []);

  const deny = useCallback(async (): Promise<void> => {
    await writePermissionState('denied');
    setState('denied');
  }, []);

  return { ready, state, request, deny };
}
