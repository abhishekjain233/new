import React from 'react';
import { Trash2 } from 'lucide-react';

import { cn } from '@/lib/cn';
import { formatDuration } from '@/lib/format';
import { PLATFORM_BY_ID } from '@/lib/platforms';
import type { RecentItem } from '@/lib/recent';

interface RecentListProps {
  items: RecentItem[];
  onPick: (item: RecentItem) => void;
  onRemove: (item: RecentItem) => void;
  onClear: () => void;
}

export const RecentList: React.FC<RecentListProps> = ({ items, onPick, onRemove, onClear }) => {
  if (items.length === 0) return null;

  return (
    <section className="w-full">
      <header className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-xs font-bold uppercase tracking-[0.18em] text-white/50">Recent</h2>
        <button
          type="button"
          onClick={onClear}
          className="text-xs font-semibold text-white/40 hover:text-white/80"
        >
          Clear all
        </button>
      </header>
      <ul className="flex flex-col gap-2">
        {items.map((item) => {
          const desc = PLATFORM_BY_ID[item.platform];
          return (
            <li
              key={`${item.id}_${item.at}`}
              className="glass group flex items-center gap-3 rounded-2xl p-2.5 sm:p-3"
            >
              <button
                type="button"
                onClick={() => onPick(item)}
                className="flex flex-1 items-center gap-3 text-left"
              >
                <div className="relative h-12 w-16 shrink-0 overflow-hidden rounded-xl bg-white/5 sm:h-14 sm:w-20">
                  {item.thumbnail ? (
                    <img
                      src={item.thumbnail}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover"
                    />
                  ) : null}
                  <span
                    className={cn(
                      'absolute bottom-1 left-1 h-1.5 w-1.5 rounded-full',
                      desc?.badge ?? 'bg-white/40',
                    )}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-white">{item.title}</p>
                  <p className="truncate text-xs text-white/50">
                    {[
                      desc?.label ?? 'Generic',
                      item.uploader,
                      formatDuration(item.durationSec),
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
              </button>
              <button
                type="button"
                onClick={() => onRemove(item)}
                aria-label="Remove from recents"
                className="rounded-full p-2 text-white/30 transition hover:bg-white/5 hover:text-white"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
};
