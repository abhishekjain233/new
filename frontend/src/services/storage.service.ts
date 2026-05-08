import AsyncStorage from '@react-native-async-storage/async-storage';

import type { Platform } from '@/constants/platforms';

const PERMISSION_KEY = 'fetch_media_permission';
const DOWNLOADS_KEY = 'fetch_recent_downloads';

const MAX_DOWNLOADS = 50;

export type PermissionState = 'granted' | 'denied';

export async function readPermissionState(): Promise<PermissionState | null> {
  const raw = await AsyncStorage.getItem(PERMISSION_KEY);
  if (raw === 'granted' || raw === 'denied') return raw;
  return null;
}

export async function writePermissionState(state: PermissionState): Promise<void> {
  await AsyncStorage.setItem(PERMISSION_KEY, state);
}

export interface RecentDownload {
  id: string;
  title: string;
  platform: Platform;
  filename?: string;
  localUri?: string;
  savedAt: number;
}

export async function readRecentDownloads(): Promise<RecentDownload[]> {
  const raw = await AsyncStorage.getItem(DOWNLOADS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item: unknown): item is RecentDownload => {
      if (!item || typeof item !== 'object') return false;
      const r = item as Partial<RecentDownload>;
      return (
        typeof r.id === 'string' &&
        typeof r.title === 'string' &&
        typeof r.savedAt === 'number' &&
        (r.platform === 'youtube' || r.platform === 'instagram' || r.platform === 'snapchat')
      );
    });
  } catch {
    return [];
  }
}

export async function appendRecentDownload(item: RecentDownload): Promise<RecentDownload[]> {
  const current = await readRecentDownloads();
  const next = [item, ...current.filter((c) => c.id !== item.id)].slice(0, MAX_DOWNLOADS);
  await AsyncStorage.setItem(DOWNLOADS_KEY, JSON.stringify(next));
  return next;
}

export async function clearRecentDownloads(): Promise<void> {
  await AsyncStorage.removeItem(DOWNLOADS_KEY);
}
