import fs from 'node:fs/promises';
import path from 'node:path';

import { config } from '../config';
import { logger } from '../utils/logger';
import { deleteProgress, readProgress } from './redis.service';

const log = logger.child('cleanup');

let timer: NodeJS.Timeout | null = null;

const SCAN_INTERVAL_MS = 60_000;
const PREFIX = 'fetch_';

export function startCleanupSweeper(): void {
  if (timer) return;
  timer = setInterval(() => {
    void sweepOnce().catch((err) =>
      log.error('sweep failed', { error: (err as Error).message }),
    );
  }, SCAN_INTERVAL_MS);
  if (typeof timer.unref === 'function') timer.unref();
  log.info(`sweeper started (every ${SCAN_INTERVAL_MS / 1000}s, ttl=${config.fileTtlMinutes}m)`);
}

export function stopCleanupSweeper(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

export async function sweepOnce(): Promise<void> {
  let entries: string[];
  try {
    entries = await fs.readdir(config.tempDir);
  } catch (err) {
    log.warn('readdir failed', { error: (err as Error).message });
    return;
  }
  const ttlMs = config.fileTtlMinutes * 60_000;
  const now = Date.now();
  for (const name of entries) {
    if (!name.startsWith(PREFIX)) continue;
    const fp = path.join(config.tempDir, name);
    try {
      const stat = await fs.stat(fp);
      if (now - stat.mtimeMs > ttlMs) {
        await fs.unlink(fp);
        const jobId = extractJobId(name);
        if (jobId) await deleteProgress(jobId);
        log.info('removed expired file', { file: name });
      }
    } catch (err) {
      log.debug('stat/unlink failed', { file: name, error: (err as Error).message });
    }
  }
}

function extractJobId(filename: string): string | null {
  // Filenames look like fetch_<jobId>.<ext> or fetch_<jobId>.<other>.mp4
  const m = /^fetch_([A-Za-z0-9_-]+)\./.exec(filename);
  return m ? m[1] : null;
}

export async function scheduleFileDeletion(filePath: string, jobId: string): Promise<void> {
  const ttlMs = config.fileTtlMinutes * 60_000;
  const t = setTimeout(() => {
    void (async () => {
      try {
        const progress = await readProgress(jobId);
        if (progress?.filePath && progress.filePath !== filePath) return;
        await fs.unlink(filePath).catch(() => undefined);
        await deleteProgress(jobId);
        log.info('scheduled deletion executed', { file: path.basename(filePath) });
      } catch (err) {
        log.warn('scheduled deletion failed', { error: (err as Error).message });
      }
    })();
  }, ttlMs);
  if (typeof t.unref === 'function') t.unref();
}
