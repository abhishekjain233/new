import { useCallback, useEffect, useRef, useState } from 'react';
import * as FileSystem from 'expo-file-system';
import * as MediaLibrary from 'expo-media-library';

import { api, ApiError, type ProgressPayload } from '@/services/api.service';
import {
  appendRecentDownload,
  readRecentDownloads,
  type RecentDownload,
} from '@/services/storage.service';
import type { Platform } from '@/constants/platforms';

export type Stage = 'idle' | 'fetching' | 'downloading' | 'done' | 'savePrompt' | 'saving' | 'error';

export interface ToastState {
  visible: boolean;
  stage: Stage;
  platform: Platform | null;
  progress: number;
  title: string;
  speed?: string;
  eta?: string;
  errorCode?: string;
  errorMessage?: string;
  jobId: string | null;
  filename?: string;
  videoTitle?: string;
}

const initialState: ToastState = {
  visible: false,
  stage: 'idle',
  platform: null,
  progress: 0,
  title: '',
  jobId: null,
};

const POLL_INTERVAL_MS = 500;
const ERROR_TOAST_MS = 3000;

export interface UseDownloadResult {
  toast: ToastState;
  recent: RecentDownload[];
  start: (url: string, platform: Platform) => Promise<void>;
  save: () => Promise<void>;
  dismiss: () => void;
  cancel: () => void;
}

export function useDownload(): UseDownloadResult {
  const [toast, setToast] = useState<ToastState>(initialState);
  const [recent, setRecent] = useState<RecentDownload[]>([]);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortController = useRef<AbortController | null>(null);
  const cancelled = useRef(false);

  useEffect(() => {
    void readRecentDownloads().then(setRecent);
  }, []);

  const clearTimers = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
    if (dismissTimer.current) {
      clearTimeout(dismissTimer.current);
      dismissTimer.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      clearTimers();
      abortController.current?.abort();
    };
  }, [clearTimers]);

  const dismiss = useCallback(() => {
    clearTimers();
    abortController.current?.abort();
    abortController.current = null;
    cancelled.current = true;
    setToast(initialState);
  }, [clearTimers]);

  const cancel = useCallback(() => {
    dismiss();
  }, [dismiss]);

  const showError = useCallback(
    (platform: Platform | null, code: string, message: string) => {
      clearTimers();
      setToast({
        visible: true,
        stage: 'error',
        platform,
        progress: 0,
        title: message,
        errorCode: code,
        errorMessage: message,
        jobId: null,
      });
      dismissTimer.current = setTimeout(() => {
        setToast(initialState);
      }, ERROR_TOAST_MS);
    },
    [clearTimers],
  );

  const pollProgress = useCallback(
    (jobId: string, platform: Platform, videoTitle: string | undefined) => {
      pollTimer.current = setInterval(async () => {
        try {
          const payload: ProgressPayload = await api.getProgress(jobId);
          if (cancelled.current) return;
          if (payload.status === 'failed') {
            showError(
              platform,
              payload.errorCode ?? 'DOWNLOAD_FAILED',
              payload.errorMessage ?? 'Download failed.',
            );
            return;
          }
          if (payload.status === 'complete') {
            clearTimers();
            setToast({
              visible: true,
              stage: 'done',
              platform,
              progress: 1,
              title: 'Your video is ready',
              jobId,
              filename: payload.filename,
              videoTitle,
            });
            dismissTimer.current = setTimeout(() => {
              setToast((s) =>
                s.stage === 'done' && s.jobId === jobId ? { ...s, stage: 'savePrompt' } : s,
              );
            }, 700);
            return;
          }
          setToast((s) => ({
            ...s,
            visible: true,
            stage: 'downloading',
            platform,
            progress: payload.progress,
            title: 'Please wait…',
            speed: payload.speed,
            eta: payload.eta,
            jobId,
            videoTitle,
          }));
        } catch (err) {
          if (cancelled.current) return;
          if (err instanceof ApiError) {
            showError(platform, err.code, err.message);
          } else {
            showError(platform, 'NETWORK_ERROR', 'Could not reach the server.');
          }
        }
      }, POLL_INTERVAL_MS);
    },
    [clearTimers, showError],
  );

  const start = useCallback(
    async (url: string, platform: Platform): Promise<void> => {
      clearTimers();
      cancelled.current = false;
      abortController.current?.abort();
      abortController.current = new AbortController();
      const signal = abortController.current.signal;

      setToast({
        visible: true,
        stage: 'fetching',
        platform,
        progress: 0,
        title: 'Fetching video info…',
        jobId: null,
      });

      let videoTitle: string | undefined;
      try {
        const info = await api.fetchInfo(url, platform, signal);
        videoTitle = info.title;
      } catch (err) {
        if (cancelled.current) return;
        if (err instanceof ApiError) {
          showError(platform, err.code, err.message);
        } else if (err instanceof Error && err.name === 'AbortError') {
          return;
        } else {
          showError(platform, 'NETWORK_ERROR', 'Could not reach the server.');
        }
        return;
      }

      let jobId: string;
      try {
        const job = await api.startDownload(url, platform, undefined, signal);
        jobId = job.jobId;
      } catch (err) {
        if (cancelled.current) return;
        if (err instanceof ApiError) {
          showError(platform, err.code, err.message);
        } else if (err instanceof Error && err.name === 'AbortError') {
          return;
        } else {
          showError(platform, 'NETWORK_ERROR', 'Could not reach the server.');
        }
        return;
      }

      setToast({
        visible: true,
        stage: 'downloading',
        platform,
        progress: 0,
        title: 'Please wait…',
        jobId,
        videoTitle,
      });
      pollProgress(jobId, platform, videoTitle);
    },
    [clearTimers, pollProgress, showError],
  );

  const save = useCallback(async (): Promise<void> => {
    if (toast.stage !== 'savePrompt' && toast.stage !== 'done') return;
    if (!toast.jobId) return;
    const jobId = toast.jobId;
    const platform = toast.platform;
    const videoTitle = toast.videoTitle ?? toast.filename ?? 'Video';
    setToast((s) => ({ ...s, stage: 'saving', title: 'Saving to gallery…' }));

    try {
      const downloadUrl = api.fileUrl(jobId);
      const filename = toast.filename ?? `fetch_${jobId}.mp4`;
      const dir = FileSystem.cacheDirectory ?? FileSystem.documentDirectory ?? '';
      const localUri = `${dir}${filename}`;
      const { uri } = await FileSystem.downloadAsync(downloadUrl, localUri);

      const permission = await MediaLibrary.getPermissionsAsync();
      if (!permission.granted) {
        const requested = await MediaLibrary.requestPermissionsAsync();
        if (!requested.granted) {
          showError(platform, 'PERMISSION_DENIED', 'Media library permission denied.');
          return;
        }
      }
      const asset = await MediaLibrary.createAssetAsync(uri);
      try {
        await MediaLibrary.createAlbumAsync('Fetch', asset, false);
      } catch {
        // album creation is best-effort; the asset is already saved to camera roll.
      }

      const downloadEntry = {
        id: jobId,
        title: videoTitle,
        platform: platform ?? 'youtube',
        filename,
        localUri: uri,
        savedAt: Date.now(),
      };
      const updated = await appendRecentDownload(downloadEntry);
      setRecent(updated);
      setToast(initialState);
    } catch (err) {
      if (err instanceof ApiError) {
        showError(platform, err.code, err.message);
      } else {
        const message = err instanceof Error ? err.message : 'Failed to save video.';
        showError(platform, 'SAVE_FAILED', message);
      }
    }
  }, [showError, toast.filename, toast.jobId, toast.platform, toast.stage, toast.videoTitle]);

  return { toast, recent, start, save, dismiss, cancel };
}
