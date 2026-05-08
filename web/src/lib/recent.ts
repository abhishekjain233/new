const STORAGE_KEY = 'fetch_recent_v1';
const MAX = 20;

export interface RecentItem {
  id: string;
  url: string;
  title: string;
  thumbnail?: string;
  uploader?: string;
  platform: string;
  durationSec?: number;
  formatLabel?: string;
  filename?: string;
  /** Epoch ms */
  at: number;
}

export function loadRecents(): RecentItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw) as unknown;
    if (!Array.isArray(arr)) return [];
    return arr.filter((x): x is RecentItem => {
      if (typeof x !== 'object' || x === null) return false;
      const r = x as Record<string, unknown>;
      return typeof r.id === 'string' && typeof r.url === 'string' && typeof r.at === 'number';
    });
  } catch {
    return [];
  }
}

export function saveRecent(item: RecentItem): RecentItem[] {
  const list = loadRecents().filter((r) => r.id !== item.id || r.url !== item.url);
  list.unshift(item);
  const trimmed = list.slice(0, MAX);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // Ignore quota errors.
  }
  return trimmed;
}

export function removeRecent(id: string): RecentItem[] {
  const list = loadRecents().filter((r) => r.id !== id);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // Ignore.
  }
  return list;
}

export function clearRecents(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore.
  }
}
