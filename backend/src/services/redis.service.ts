import IORedis, { type Redis, type RedisOptions } from 'ioredis';

import { config } from '../config';
import type { JobProgress } from '../types';
import { logger } from '../utils/logger';

const log = logger.child('redis');

const PROGRESS_KEY_PREFIX = 'fetch:progress:';

let primary: Redis | null = null;
const connections: Redis[] = [];

function buildRedis(role: string): Redis {
  const options: RedisOptions = {
    maxRetriesPerRequest: null,
    enableReadyCheck: false,
    lazyConnect: false,
    // Railway's internal hostnames (e.g. redis.railway.internal) only resolve
    // via IPv6. family: 0 lets Node try both A and AAAA records.
    family: 0,
  };
  const client = new IORedis(config.redisUrl, options);
  client.on('error', (err) => log.error(`${role} error: ${err.message}`));
  client.on('connect', () => log.debug(`${role} connected`));
  client.on('close', () => log.debug(`${role} closed`));
  connections.push(client);
  return client;
}

export function getRedis(): Redis {
  if (!primary) primary = buildRedis('primary');
  return primary;
}

export function createRedisConnection(role: string): Redis {
  return buildRedis(role);
}

export function progressKey(jobId: string): string {
  return `${PROGRESS_KEY_PREFIX}${jobId}`;
}

export async function saveProgress(progress: JobProgress): Promise<void> {
  const redis = getRedis();
  await redis.set(
    progressKey(progress.jobId),
    JSON.stringify(progress),
    'EX',
    config.progressKeyTtlSeconds,
  );
}

export async function readProgress(jobId: string): Promise<JobProgress | null> {
  const redis = getRedis();
  const raw = await redis.get(progressKey(jobId));
  if (!raw) return null;
  try {
    return JSON.parse(raw) as JobProgress;
  } catch (err) {
    log.warn(`failed to parse progress for ${jobId}`, { error: (err as Error).message });
    return null;
  }
}

export async function deleteProgress(jobId: string): Promise<void> {
  const redis = getRedis();
  await redis.del(progressKey(jobId));
}

export async function closeRedis(): Promise<void> {
  await Promise.all(
    connections.map(async (c) => {
      try {
        await c.quit();
      } catch {
        c.disconnect();
      }
    }),
  );
  connections.length = 0;
  primary = null;
}
