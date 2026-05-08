import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Clock, ExternalLink, User2, X } from 'lucide-react';

import { fileUrl, getProgress, startDownload, type MediaFormat, type MediaInfo } from '@/lib/api';
import { formatDuration } from '@/lib/format';
import { saveRecent, type RecentItem } from '@/lib/recent';

import { FormatRow, type FormatRowState } from './FormatRow';
import { PlatformBadge } from './PlatformBadge';

interface DetailsModalProps {
  info: MediaInfo;
  open: boolean;
  onClose: () => void;
  onDownloaded?: (item: RecentItem) => void;
}

const POLL_INTERVAL_MS = 800;

export const DetailsModal: React.FC<DetailsModalProps> = ({ info, open, onClose, onDownloaded }) => {
  const [states, setStates] = useState<Record<string, FormatRowState>>({});
  const pollers = useRef<Record<string, number>>({});

  const stopPoller = useCallback((formatId: string) => {
    const handle = pollers.current[formatId];
    if (handle) {
      window.clearInterval(handle);
      delete pollers.current[formatId];
    }
  }, []);

  useEffect(() => {
    if (!open) {
      Object.keys(pollers.current).forEach(stopPoller);
      setStates({});
    }
  }, [open, stopPoller]);

  useEffect(() => {
    return () => {
      Object.keys(pollers.current).forEach(stopPoller);
    };
  }, [stopPoller]);

  useEffect(() => {
    if (!open) return undefined;
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, onClose]);

  const handleDownload = useCallback(
    async (format: MediaFormat) => {
      setStates((prev) => ({ ...prev, [format.id]: { kind: 'queued' } }));
      try {
        const { jobId } = await startDownload(info.url, format.id);
        const handle = window.setInterval(async () => {
          try {
            const p = await getProgress(jobId);
            if (p.status === 'failed') {
              setStates((prev) => ({
                ...prev,
                [format.id]: {
                  kind: 'failed',
                  message: p.errorMessage ?? p.errorCode ?? 'Download failed',
                },
              }));
              stopPoller(format.id);
              return;
            }
            if (p.status === 'complete') {
              setStates((prev) => ({ ...prev, [format.id]: { kind: 'complete' } }));
              stopPoller(format.id);
              triggerBrowserDownload(jobId, p.filename ?? safeName(info.title, format.ext));
              const rec: RecentItem = {
                id: `${info.id}_${format.id}`,
                url: info.url,
                title: info.title,
                thumbnail: info.thumbnail,
                uploader: info.uploader,
                platform: info.platform,
                durationSec: info.duration,
                formatLabel: format.audioOnly ? 'Audio' : format.resolution ?? format.ext,
                filename: p.filename,
                at: Date.now(),
              };
              saveRecent(rec);
              onDownloaded?.(rec);
              return;
            }
            setStates((prev) => ({
              ...prev,
              [format.id]: {
                kind: 'downloading',
                progress: p.progress,
                speed: p.speed,
                eta: p.eta,
              },
            }));
          } catch {
            // Transient errors during polling — ignore; the next tick may succeed.
          }
        }, POLL_INTERVAL_MS);
        pollers.current[format.id] = handle;
      } catch (err) {
        const message =
          err instanceof Error ? err.message : 'Could not start download. Please try again.';
        setStates((prev) => ({ ...prev, [format.id]: { kind: 'failed', message } }));
      }
    },
    [info, onDownloaded, stopPoller],
  );

  const grouped = useMemo(() => groupFormats(info.formats), [info.formats]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="details-title"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 px-3 py-4 sm:items-center sm:px-6"
      onClick={onClose}
    >
      <div
        className="glass relative max-h-[92vh] w-full max-w-xl overflow-hidden rounded-3xl shadow-glass animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 p-4 sm:p-5">
          {info.thumbnail ? (
            <img
              src={info.thumbnail}
              alt=""
              loading="lazy"
              className="h-20 w-32 shrink-0 rounded-xl object-cover sm:h-24 sm:w-40"
            />
          ) : (
            <div className="h-20 w-32 shrink-0 rounded-xl bg-white/5 sm:h-24 sm:w-40" />
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <PlatformBadge platform={info.platform} />
            </div>
            <h2
              id="details-title"
              className="mt-1.5 line-clamp-2 text-base font-extrabold leading-tight text-white sm:text-lg"
            >
              {info.title}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-white/60">
              {info.uploader ? (
                <span className="inline-flex items-center gap-1.5">
                  <User2 className="h-3 w-3" />
                  {info.uploader}
                </span>
              ) : null}
              {info.duration ? (
                <span className="inline-flex items-center gap-1.5">
                  <Clock className="h-3 w-3" />
                  {formatDuration(info.duration)}
                </span>
              ) : null}
              <a
                href={info.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 text-white/50 hover:text-white"
              >
                <ExternalLink className="h-3 w-3" />
                Open source
              </a>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="absolute right-3 top-3 rounded-full bg-white/5 p-1.5 text-white/70 hover:bg-white/10 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-t border-border-subtle px-4 pb-4 pt-3 sm:px-5 sm:pb-5">
          <div className="scrollbar-thin max-h-[58vh] space-y-4 overflow-y-auto pr-1">
            {grouped.map((group) =>
              group.items.length > 0 ? (
                <section key={group.label}>
                  <h3 className="mb-2 text-[11px] font-bold uppercase tracking-[0.18em] text-white/40">
                    {group.label}
                  </h3>
                  <div className="flex flex-col gap-2">
                    {group.items.map((f) => (
                      <FormatRow
                        key={f.id}
                        format={f}
                        state={states[f.id] ?? { kind: 'idle' }}
                        onDownload={handleDownload}
                      />
                    ))}
                  </div>
                </section>
              ) : null,
            )}
            {info.formats.length === 0 ? (
              <p className="text-sm text-white/60">
                No downloadable formats were found for this URL.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};

interface FormatGroup {
  label: string;
  items: MediaFormat[];
}

function groupFormats(formats: MediaFormat[]): FormatGroup[] {
  const muxed: MediaFormat[] = [];
  const videoOnly: MediaFormat[] = [];
  const audioOnly: MediaFormat[] = [];
  for (const f of formats) {
    if (f.audioOnly) audioOnly.push(f);
    else if (f.videoOnly) videoOnly.push(f);
    else muxed.push(f);
  }
  const byHeightDesc = (a: MediaFormat, b: MediaFormat) => (b.height ?? 0) - (a.height ?? 0);
  return [
    { label: 'Video + Audio', items: muxed.sort(byHeightDesc) },
    { label: 'Video (high quality, merged with audio server-side)', items: videoOnly.sort(byHeightDesc) },
    { label: 'Audio only', items: audioOnly },
  ];
}

function safeName(title: string, ext: string): string {
  const base = title.replace(/[^a-z0-9._-]+/gi, '_').slice(0, 80);
  return `${base || 'fetch'}.${ext}`;
}

function triggerBrowserDownload(jobId: string, filename: string): void {
  const a = document.createElement('a');
  a.href = fileUrl(jobId);
  a.download = filename;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
