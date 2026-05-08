export interface MediaFormat {
  id: string;
  ext: string;
  resolution?: string;
  width?: number;
  height?: number;
  fps?: number;
  filesize?: number;
  videoOnly: boolean;
  audioOnly: boolean;
  note?: string;
}

export type Platform =
  | 'youtube'
  | 'instagram'
  | 'snapchat'
  | 'tiktok'
  | 'facebook'
  | 'twitter'
  | 'vimeo'
  | 'dailymotion'
  | 'reddit'
  | 'twitch'
  | 'soundcloud'
  | 'generic';

export interface MediaInfo {
  id: string;
  title: string;
  thumbnail?: string;
  duration?: number;
  uploader?: string;
  platform: Platform;
  url: string;
  formats: MediaFormat[];
}

export type JobStatus = 'queued' | 'downloading' | 'complete' | 'failed';

export interface JobProgress {
  jobId: string;
  status: JobStatus;
  progress: number;
  speed?: string;
  eta?: string;
  bytesDownloaded?: number;
  bytesTotal?: number;
  downloadUrl?: string;
  filename?: string;
  errorCode?: string;
  errorMessage?: string;
}

export interface ApiError {
  success: false;
  error: string;
  message: string;
}

export interface ApiSuccess<T> {
  success: true;
  data: T;
}

export type ApiResponse<T> = ApiSuccess<T> | ApiError;

export class ApiClientError extends Error {
  constructor(
    public code: string,
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = 'ApiClientError';
  }
}

const RAW_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim();
export const API_BASE_URL = RAW_BASE.replace(/\/+$/, '');

function buildUrl(path: string): string {
  if (!API_BASE_URL) return path;
  return `${API_BASE_URL}${path}`;
}

async function parseJson<T>(res: Response): Promise<T> {
  const body = (await res.json().catch(() => null)) as ApiResponse<T> | null;
  if (!body) {
    throw new ApiClientError('NETWORK_ERROR', `Unexpected response (${res.status})`, res.status);
  }
  if (!body.success) {
    throw new ApiClientError(body.error, body.message || 'Request failed', res.status);
  }
  return body.data;
}

export async function fetchInfo(url: string, signal?: AbortSignal): Promise<MediaInfo> {
  const res = await fetch(buildUrl('/api/fetch-info'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
    signal,
  });
  return parseJson<MediaInfo>(res);
}

export async function startDownload(
  url: string,
  formatId?: string,
): Promise<{ jobId: string }> {
  const res = await fetch(buildUrl('/api/download'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, formatId }),
  });
  return parseJson<{ jobId: string }>(res);
}

export async function getProgress(jobId: string): Promise<JobProgress> {
  const res = await fetch(buildUrl(`/api/progress/${encodeURIComponent(jobId)}`));
  return parseJson<JobProgress>(res);
}

export function fileUrl(jobId: string): string {
  return buildUrl(`/api/file/${encodeURIComponent(jobId)}`);
}
