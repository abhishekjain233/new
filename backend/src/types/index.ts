export type Platform = 'youtube' | 'instagram' | 'snapchat';

export interface MediaFormat {
  id: string;
  ext: string;
  resolution?: string;
  width?: number;
  height?: number;
  fps?: number;
  filesize?: number;
  vcodec?: string;
  acodec?: string;
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

export type JobStatus = 'queued' | 'downloading' | 'complete' | 'failed';

export interface JobProgress {
  jobId: string;
  status: JobStatus;
  progress: number;
  speed?: string;
  eta?: string;
  bytesDownloaded?: number;
  bytesTotal?: number;
  errorCode?: string;
  errorMessage?: string;
  filePath?: string;
  downloadUrl?: string;
  filename?: string;
  updatedAt: number;
}

export interface DownloadJobData {
  jobId: string;
  url: string;
  platform: Platform;
  formatId?: string;
  outputBasename: string;
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
