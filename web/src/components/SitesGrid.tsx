import React from 'react';

import { cn } from '@/lib/cn';
import { PLATFORMS } from '@/lib/platforms';

export const SitesGrid: React.FC = () => {
  return (
    <section className="w-full">
      <h2 className="mb-3 px-1 text-xs font-bold uppercase tracking-[0.18em] text-white/50">
        Supported sites
      </h2>
      <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
        {PLATFORMS.map((p) => (
          <li key={p.id}>
            <a
              href={p.homepage}
              target="_blank"
              rel="noreferrer noopener"
              className="glass flex h-full flex-col items-center justify-center gap-2 rounded-2xl p-3 text-center transition hover:border-border-strong"
            >
              <span
                className={cn(
                  'flex h-10 w-10 items-center justify-center rounded-full text-xs font-bold uppercase text-black',
                  p.badge,
                )}
              >
                {p.label.charAt(0)}
              </span>
              <span className="text-xs font-semibold text-white/90">{p.label}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
};
