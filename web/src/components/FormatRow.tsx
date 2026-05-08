import React from 'react';
import { CheckCircle2, Download, Loader2, AlertCircle } from 'lucide-react';

import { cn } from '@/lib/cn';
import { formatBytes, formatKindBadge, formatLabel } from '@/lib/format';
import type { MediaFormat } from '@/lib/api';

export type FormatRowState =
  | { kind: 'idle' }
  | { kind: 'queued' }
  | { kind: 'downloading'; progress: number; speed?: string; eta?: string }
  | { kind: 'complete' }
  | { kind: 'failed'; message: string };

interface FormatRowProps {
  format: MediaFormat;
  state: FormatRowState;
  onDownload: (format: MediaFormat) => void;
}

export const FormatRow: React.FC<FormatRowProps> = ({ format, state, onDownload }) => {
  const isVideo = !format.audioOnly;
  const sizeLabel = formatBytes(format.filesize);
  const status = renderStatus(state);

  return (
    <div
      className={cn(
        'relative flex items-center gap-3 overflow-hidden rounded-xl border border-border-subtle bg-white/[0.03] p-3',
        'transition hover:border-border-strong',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-white/5 px-2 py-0.5 text-xs font-bold uppercase text-white/80">
            {format.ext}
          </span>
          <span className="text-sm font-bold text-white">{formatLabel(format)}</span>
          {format.fps && format.fps > 0 && isVideo ? (
            <span className="text-xs text-white/50">{format.fps} fps</span>
          ) : null}
        </div>
        <p className="mt-1 truncate text-xs text-white/50">
          {[formatKindBadge(format), sizeLabel, format.note]
            .filter((x) => x && x !== '—')
            .join(' · ')}
        </p>
        {state.kind === 'downloading' ? (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
            <div
              className="h-full rounded-full bg-gradient-to-r from-accent-start to-accent-end transition-[width] duration-300"
              style={{ width: `${Math.max(2, Math.min(100, state.progress * 100))}%` }}
            />
          </div>
        ) : null}
        {state.kind === 'failed' ? (
          <p className="mt-1 text-xs text-red-400">{state.message}</p>
        ) : null}
      </div>
      <button
        type="button"
        disabled={state.kind === 'downloading' || state.kind === 'queued'}
        onClick={() => onDownload(format)}
        className={cn(
          'flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-bold transition',
          state.kind === 'complete'
            ? 'bg-emerald-500/10 text-emerald-300'
            : state.kind === 'failed'
              ? 'bg-red-500/10 text-red-300'
              : 'bg-white/10 text-white hover:bg-white/15',
          'disabled:cursor-not-allowed disabled:opacity-70',
        )}
      >
        {status.icon}
        <span>{status.label}</span>
      </button>
    </div>
  );
};

function renderStatus(state: FormatRowState): { icon: React.ReactNode; label: string } {
  switch (state.kind) {
    case 'idle':
      return { icon: <Download className="h-3.5 w-3.5" />, label: 'Download' };
    case 'queued':
      return { icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, label: 'Queued' };
    case 'downloading': {
      const pct = Math.round(state.progress * 100);
      return { icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, label: `${pct}%` };
    }
    case 'complete':
      return { icon: <CheckCircle2 className="h-3.5 w-3.5" />, label: 'Saved' };
    case 'failed':
      return { icon: <AlertCircle className="h-3.5 w-3.5" />, label: 'Retry' };
  }
}
