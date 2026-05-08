import React from 'react';
import { Share2 } from 'lucide-react';

export const Hero: React.FC = () => {
  return (
    <header className="flex flex-col items-center text-center">
      <div className="glass mb-4 flex h-14 w-14 items-center justify-center rounded-2xl">
        <span className="text-2xl">⬇️</span>
      </div>
      <h1 className="text-3xl font-extrabold tracking-tight text-white sm:text-4xl">
        Fetch<span className="text-accent-end">.</span>
      </h1>
      <p className="mt-2 max-w-md text-sm text-white/60 sm:text-base">
        Paste a video link or share to Fetch. We&apos;ll show every format we can pull and let you
        download it in one tap.
      </p>
      <p className="mt-3 inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs font-semibold text-white/70">
        <Share2 className="h-3.5 w-3.5" />
        Install as an app to share URLs from anywhere
      </p>
    </header>
  );
};
