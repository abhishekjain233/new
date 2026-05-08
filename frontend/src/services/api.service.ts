import Constants from 'expo-constants';

import type { Platform } from '@/constants/platforms';

const FALLBACK_API_BASE = 'http://localhost:3000';

function resolveBaseUrl(): string {
  const fromExpo = Constants.expoConfig?.extra?.apiBaseUrl;
  if (typeof fromExpo === 'string' && fromExpo.length > 0) return fromExpo.replace(/\/$/, '');
  return FALLBACK_API_BASE;
}

export const API_BASE_URL = resolveBaseUrl();

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

export interface ProgressPayload {
  jobId: string;
  status: 'queued' | 'downloading' | 'complete' | 'failed';
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

export class ApiError extends Error {
  constructor(public code: string, message: string, public status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

interface SuccessEnvelope<T> { success: true; data: T; }
interface FailureEnvelope { success: false; error: string; message: string; }
type Envelope<T> = SuccessEnvelope<T> | FailureEnvelope;

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  return handleEnvelope<T>(response);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  });
  return handleEnvelope<T>(response);
}

async function handleEnvelope<T>(response: Response): Promise<T> {
  let envelope: Envelope<T> | null = null;
  try {
    envelope = (await response.json()) as Envelope<T>;
  } catch {
    throw new ApiError('PARSE_ERROR', 'Server returned an invalid response.', response.status);
  }
  if (!envelope || typeof envelope !== 'object') {
    throw new ApiError('PARSE_ERROR', 'Server returned an empty response.', response.status);
  }
  if (envelope.success) return envelope.data;
  throw new ApiError(envelope.error || 'API_ERROR', envelope.message || 'Request failed.', response.status);
}

export const api = {
  fetchInfo(url: string, platform: Platform, signal?: AbortSignal): Promise<MediaInfo> {
    return postJson<MediaInfo>('/api/fetch-info', { url, platform }, signal);
  },
  startDownload(
    url: string,
    platform: Platform,
    formatId?: string,
    signal?: AbortSignal,
  ): Promise<{ jobId: string }> {
    return postJson<{ jobId: string }>(
      '/api/download',
      { url, platform, formatId },
      signal,
    );
  },
  getProgress(jobId: string, signal?: AbortSignal): Promise<ProgressPayload> {
    return getJson<ProgressPayload>(`/api/progress/${encodeURIComponent(jobId)}`, signal);
  },
  fileUrl(jobId: string): string {
    return `${API_BASE_URL}/api/file/${encodeURIComponent(jobId)}`;
  },
};
