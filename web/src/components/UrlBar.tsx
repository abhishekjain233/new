import React, { useCallback, useState } from 'react';
import { ClipboardPaste, Loader2, Search, X } from 'lucide-react';

import { cn } from '@/lib/cn';

interface UrlBarProps {
  initialUrl?: string;
  loading?: boolean;
  onSubmit: (url: string) => void;
  className?: string;
}

export const UrlBar: React.FC<UrlBarProps> = ({ initialUrl = '', loading = false, onSubmit, className }) => {
  const [value, setValue] = useState(initialUrl);

  React.useEffect(() => {
    setValue(initialUrl);
  }, [initialUrl]);

  const submit = useCallback(
    (raw: string) => {
      const trimmed = raw.trim();
      if (!trimmed) return;
      onSubmit(trimmed);
    },
    [onSubmit],
  );

  const handlePaste = useCallback(async () => {
    if (!navigator.clipboard?.readText) return;
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        setValue(text);
        submit(text);
      }
    } catch {
      // Clipboard access denied — silently ignore. The user can still paste manually.
    }
  }, [submit]);

  return (
    <form
      className={cn(
        'glass flex w-full items-center gap-2 rounded-2xl px-3 py-2 sm:px-4 sm:py-3',
        className,
      )}
      onSubmit={(e) => {
        e.preventDefault();
        submit(value);
      }}
    >
      <Search className="h-5 w-5 shrink-0 text-white/50" aria-hidden />
      <input
        type="url"
        inputMode="url"
        autoComplete="off"
        spellCheck={false}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Paste video URL — YouTube, Insta, TikTok, X…"
        className="flex-1 bg-transparent text-sm sm:text-base text-white outline-none placeholder:text-white/40"
        aria-label="Video URL"
      />
      {value ? (
        <button
          type="button"
          aria-label="Clear"
          onClick={() => setValue('')}
          className="rounded-full p-1 text-white/40 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      ) : (
        <button
          type="button"
          aria-label="Paste from clipboard"
          onClick={handlePaste}
          className="rounded-full p-1 text-white/50 hover:text-white"
        >
          <ClipboardPaste className="h-5 w-5" />
        </button>
      )}
      <button
        type="submit"
        disabled={loading || !value.trim()}
        className={cn(
          'flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold text-white transition',
          'bg-gradient-to-br from-accent-start to-accent-end shadow-glass',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        <span>Fetch</span>
      </button>
    </form>
  );
};
