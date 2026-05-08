import Bull, { type Job, type Queue } from 'bull';
import path from 'node:path';

import { config } from '../config';
import type { DownloadJobData, JobProgress, JobStatus } from '../types';
import { logger } from '../utils/logger';
import { saveProgress, readProgress } from './redis.service';
import { downloadMedia, YtDlpError } from './ytdlp.service';

const log = logger.child('queue');

const QUEUE_NAME = 'fetch-downloads';

let queue: Queue<DownloadJobData> | null = null;

export function getQueue(): Queue<DownloadJobData> {
  if (!queue) {
    queue = new Bull<DownloadJobData>(QUEUE_NAME, config.redisUrl, {
      // Railway's internal Redis hostname is IPv6-only. Force ioredis to
      // try both address families so DNS lookup succeeds.
      redis: { family: 0 },
      defaultJobOptions: {
        removeOnComplete: { age: 3600, count: 200 },
        removeOnFail: { age: 86_400, count: 200 },
        attempts: 1,
      },
    });
    queue.on('error', (err) => log.error(`queue error: ${err.message}`));
    queue.on('failed', (job, err) => log.warn(`job ${job?.id} failed`, { error: err.message }));
  }
  return queue;
}

export async function startWorker(): Promise<void> {
  const q = getQueue();
  await q.process(config.maxConcurrentDownloads, async (job: Job<DownloadJobData>) => {
    return processJob(job);
  });
  log.info(`worker started with concurrency ${config.maxConcurrentDownloads}`);
}

async function processJob(job: Job<DownloadJobData>): Promise<JobProgress> {
  const { jobId, url, platform, formatId } = job.data;
  log.info(`starting job ${jobId}`, { url, platform });

  await persistProgress({
    jobId,
    status: 'downloading',
    progress: 0,
    updatedAt: Date.now(),
  });

  try {
    const result = await downloadMedia({
      url,
      platform,
      jobId,
      formatId,
      onProgress: async (p) => {
        await persistProgress({
          jobId,
          status: 'downloading',
          progress: p.progress,
          speed: p.speed,
          eta: p.eta,
          bytesDownloaded: p.bytesDownloaded,
          bytesTotal: p.bytesTotal,
          updatedAt: Date.now(),
        });
      },
    });

    const filename = path.basename(result.filePath);
    const finalProgress: JobProgress = {
      jobId,
      status: 'complete',
      progress: 1,
      filePath: result.filePath,
      filename,
      downloadUrl: `/api/file/${jobId}`,
      updatedAt: Date.now(),
    };
    await persistProgress(finalProgress);
    log.info(`job ${jobId} complete`, { filePath: result.filePath });
    return finalProgress;
  } catch (err) {
    const code = err instanceof YtDlpError ? err.code : 'DOWNLOAD_FAILED';
    const message = err instanceof Error ? err.message : 'Unknown error';
    log.error(`job ${jobId} failed`, { code, message });
    const failed: JobProgress = {
      jobId,
      status: 'failed',
      progress: 0,
      errorCode: code,
      errorMessage: message,
      updatedAt: Date.now(),
    };
    await persistProgress(failed);
    throw err;
  }
}

async function persistProgress(progress: JobProgress): Promise<void> {
  await saveProgress(progress);
}

export async function enqueueDownload(data: DownloadJobData): Promise<string> {
  const q = getQueue();
  await persistProgress({
    jobId: data.jobId,
    status: 'queued',
    progress: 0,
    updatedAt: Date.now(),
  });
  await q.add(data, { jobId: data.jobId });
  return data.jobId;
}

export async function getJobProgress(jobId: string): Promise<JobProgress | null> {
  return readProgress(jobId);
}

export async function getJobStatus(jobId: string): Promise<JobStatus | null> {
  const p = await readProgress(jobId);
  return p ? p.status : null;
}

export async function closeQueue(): Promise<void> {
  if (queue) {
    await queue.close();
    queue = null;
  }
}
