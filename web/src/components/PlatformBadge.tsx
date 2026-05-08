import React from 'react';

import { cn } from '@/lib/cn';
import { PLATFORM_BY_ID, platformLabel } from '@/lib/platforms';

interface PlatformBadgeProps {
  platform: string;
  className?: string;
}

export const PlatformBadge: React.FC<PlatformBadgeProps> = ({ platform, className }) => {
  const descriptor = PLATFORM_BY_ID[platform];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-white/80',
        className,
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', descriptor?.badge ?? 'bg-white/40')} />
      {platformLabel(platform)}
    </span>
  );
};
