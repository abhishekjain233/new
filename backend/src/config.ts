import 'dotenv/config';
import path from 'node:path';

function envInt(key: string, fallback: number): number {
  const raw = process.env[key];
  if (raw == null || raw === '') return fallback;
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

function envStr(key: string, fallback: string): string {
  const raw = process.env[key];
  return raw && raw.length > 0 ? raw : fallback;
}

export interface AppConfig {
  port: number;
  redisUrl: string;
  ytdlpPath: string;
  tempDir: string;
  fileTtlMinutes: number;
  rateLimitMax: number;
  rateLimitWindowMs: number;
  maxConcurrentDownloads: number;
  progressKeyTtlSeconds: number;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
  nodeEnv: string;
  // Optional Netscape-format cookies, base64-encoded. When set, materialised
  // to disk on startup and passed to yt-dlp via --cookies. Required for
  // most YouTube / Instagram URLs from datacenter IPs since 2025.
  cookiesB64: string;
}

const logLevelRaw = envStr('LOG_LEVEL', 'info');
const logLevel: AppConfig['logLevel'] =
  logLevelRaw === 'debug' || logLevelRaw === 'warn' || logLevelRaw === 'error' ? logLevelRaw : 'info';

export const config: AppConfig = {
  port: envInt('PORT', 3000),
  redisUrl: envStr('REDIS_URL', 'redis://localhost:6379'),
  ytdlpPath: envStr('YTDLP_PATH', 'yt-dlp'),
  tempDir: path.resolve(envStr('TEMP_DIR', '/tmp')),
  fileTtlMinutes: envInt('FILE_TTL_MINUTES', 10),
  rateLimitMax: envInt('RATE_LIMIT_MAX', 20),
  rateLimitWindowMs: envInt('RATE_LIMIT_WINDOW_MS', 60_000),
  maxConcurrentDownloads: envInt('MAX_CONCURRENT_DOWNLOADS', 5),
  progressKeyTtlSeconds: envInt('PROGRESS_KEY_TTL_SECONDS', 900),
  logLevel,
  nodeEnv: envStr('NODE_ENV', 'development'),
  cookiesB64: envStr('YTDLP_COOKIES_B64', ''),
};
