/**
 * Parses progress lines emitted by yt-dlp. We invoke yt-dlp with a custom
 * --progress-template so each progress line looks like:
 *
 *   PRG <pct>%|<speed>|<eta>|<dl_bytes>|<total_bytes>
 *
 * Any field can be `NA`. As a fallback we also recognise the default human
 * readable lines like:
 *
 *   [download]  43.2% of 18.45MiB at  2.30MiB/s ETA 00:05
 */

export interface ParsedProgress {
  /** 0..1 */
  progress: number;
  speed?: string;
  eta?: string;
  bytesDownloaded?: number;
  bytesTotal?: number;
}

const PCT_RE = /(\d+(?:\.\d+)?)%/;
const SPEED_RE = /(\d+(?:\.\d+)?\s*[KMG]?i?B\/s)/i;
const ETA_RE = /ETA\s+([\d:]+)/i;
const SIZE_RE = /of\s+(\d+(?:\.\d+)?\s*[KMG]?i?B)/i;
const SIZE_VALUE_RE = /^(\d+(?:\.\d+)?)\s*([KMG]?i?B)$/i;

export function parseProgressLine(line: string): ParsedProgress | null {
  const cleaned = line.replace(/\r$/, '').trim();
  if (!cleaned) return null;

  if (cleaned.startsWith('PRG ')) {
    return parseTemplate(cleaned.slice(4));
  }

  if (!cleaned.includes('%')) return null;
  const pctMatch = PCT_RE.exec(cleaned);
  if (!pctMatch) return null;
  const pct = clamp(Number.parseFloat(pctMatch[1]) / 100);
  if (!Number.isFinite(pct)) return null;
  const speedMatch = SPEED_RE.exec(cleaned);
  const etaMatch = ETA_RE.exec(cleaned);
  const sizeMatch = SIZE_RE.exec(cleaned);
  return {
    progress: pct,
    speed: speedMatch?.[1],
    eta: etaMatch?.[1],
    bytesTotal: sizeMatch ? parseSizeStr(sizeMatch[1]) : undefined,
  };
}

function parseTemplate(payload: string): ParsedProgress | null {
  const fields = payload.split('|').map((s) => s.trim());
  if (fields.length < 5) return null;
  const [pctStr, speedStr, etaStr, dlStr, totalStr] = fields;
  const pct = parsePercent(pctStr);
  if (pct == null) return null;
  return {
    progress: pct,
    speed: cleanField(speedStr),
    eta: cleanField(etaStr),
    bytesDownloaded: parseIntField(dlStr),
    bytesTotal: parseIntField(totalStr),
  };
}

function parsePercent(s: string): number | null {
  if (!s || s === 'NA') return null;
  const m = /^([\d.]+)%$/.exec(s);
  if (!m) return null;
  const n = Number.parseFloat(m[1]);
  if (!Number.isFinite(n)) return null;
  return clamp(n / 100);
}

function cleanField(s: string | undefined): string | undefined {
  if (!s || s === 'NA') return undefined;
  return s.replace(/\s+/g, ' ').trim();
}

function parseIntField(s: string | undefined): number | undefined {
  if (!s || s === 'NA') return undefined;
  const n = Number.parseInt(s, 10);
  return Number.isFinite(n) ? n : undefined;
}

function parseSizeStr(s: string): number | undefined {
  const m = SIZE_VALUE_RE.exec(s.trim());
  if (!m) return undefined;
  const n = Number.parseFloat(m[1]);
  if (!Number.isFinite(n)) return undefined;
  return Math.round(n * unitMultiplier(m[2]));
}

function unitMultiplier(unit: string): number {
  switch (unit.toUpperCase()) {
    case 'B':
      return 1;
    case 'KB':
    case 'KIB':
      return 1024;
    case 'MB':
    case 'MIB':
      return 1024 * 1024;
    case 'GB':
    case 'GIB':
      return 1024 * 1024 * 1024;
    default:
      return 1;
  }
}

function clamp(n: number): number {
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}
