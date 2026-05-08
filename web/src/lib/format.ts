import type { MediaFormat } from './api';

export function formatBytes(bytes: number | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatDuration(seconds: number | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatLabel(f: MediaFormat): string {
  if (f.audioOnly) {
    return f.note ? `Audio · ${f.note}` : 'Audio';
  }
  if (f.resolution) return f.resolution;
  if (f.height) return `${f.height}p${f.fps && f.fps > 30 ? f.fps : ''}`;
  return f.note ?? f.id;
}

export function formatKindBadge(f: MediaFormat): string {
  if (f.audioOnly) return 'Audio only';
  if (f.videoOnly) return 'Video only';
  return 'Video + Audio';
}
