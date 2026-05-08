import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiClientError, fetchInfo, type MediaInfo } from '@/lib/api';
import { clearRecents, loadRecents, removeRecent, type RecentItem } from '@/lib/recent';

import { DetailsModal } from '@/components/DetailsModal';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Hero } from '@/components/Hero';
import { RecentList } from '@/components/RecentList';
import { SitesGrid } from '@/components/SitesGrid';
import { UrlBar } from '@/components/UrlBar';

const App: React.FC = () => {
  const [pendingUrl, setPendingUrl] = useState('');
  const [info, setInfo] = useState<MediaInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [recents, setRecents] = useState<RecentItem[]>(() => loadRecents());
  const fetchAbort = useRef<AbortController | null>(null);

  const sharedUrl = useMemo(() => readSharedUrl(window.location), []);

  const submit = useCallback(async (url: string) => {
    fetchAbort.current?.abort();
    const controller = new AbortController();
    fetchAbort.current = controller;
    setError(null);
    setInfo(null);
    setLoading(true);
    setModalOpen(false);
    setPendingUrl(url);
    try {
      const result = await fetchInfo(url, controller.signal);
      setInfo(result);
      setModalOpen(true);
    } catch (err) {
      if (controller.signal.aborted) return;
      const message =
        err instanceof ApiClientError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not fetch this URL.';
      setError(message);
    } finally {
      if (fetchAbort.current === controller) {
        fetchAbort.current = null;
      }
      setLoading(false);
    }
  }, []);

  // Auto-trigger when arriving from a Web Share Target.
  useEffect(() => {
    if (sharedUrl) {
      // Replace the URL so a refresh doesn't re-trigger the fetch.
      const next = new URL(window.location.href);
      next.searchParams.delete('url');
      next.searchParams.delete('text');
      next.searchParams.delete('title');
      window.history.replaceState({}, '', next.pathname);
      void submit(sharedUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClose = useCallback(() => {
    setModalOpen(false);
  }, []);

  const handleDownloaded = useCallback((rec: RecentItem) => {
    setRecents((prev) => {
      const filtered = prev.filter((r) => r.id !== rec.id || r.url !== rec.url);
      return [rec, ...filtered].slice(0, 20);
    });
  }, []);

  const handlePickRecent = useCallback(
    (item: RecentItem) => {
      void submit(item.url);
    },
    [submit],
  );

  const handleRemoveRecent = useCallback((item: RecentItem) => {
    setRecents(removeRecent(item.id));
  }, []);

  const handleClearRecents = useCallback(() => {
    clearRecents();
    setRecents([]);
  }, []);

  return (
    <div className="relative mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-6 px-4 pb-24 pt-10 sm:gap-8 sm:px-6 sm:pt-14">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[480px] bg-[radial-gradient(ellipse_at_top,rgba(124,92,252,0.22),transparent_60%)]"
      />

      <Hero />
      <UrlBar initialUrl={pendingUrl} loading={loading} onSubmit={submit} />

      {error ? <ErrorBanner message={error} onDismiss={() => setError(null)} /> : null}

      <RecentList
        items={recents}
        onPick={handlePickRecent}
        onRemove={handleRemoveRecent}
        onClear={handleClearRecents}
      />

      <SitesGrid />

      <footer className="mt-auto pt-4 text-center text-xs text-white/30">
        Fetch. — yt-dlp under the hood. For personal use only.
      </footer>

      {info ? (
        <DetailsModal
          info={info}
          open={modalOpen}
          onClose={handleClose}
          onDownloaded={handleDownloaded}
        />
      ) : null}
    </div>
  );
};

function readSharedUrl(loc: Location): string | null {
  const params = new URLSearchParams(loc.search);

  // Direct ?url= param (works on / and on /share — both are SPA routes).
  const direct = params.get('url');
  if (direct && /^https?:\/\//i.test(direct)) return direct;

  // Some share targets only forward 'text' (e.g. iOS).
  const text = params.get('text');
  if (text) {
    const match = text.match(/https?:\/\/\S+/);
    if (match) return match[0];
  }

  // Title fallback (rare).
  const title = params.get('title');
  if (title) {
    const match = title.match(/https?:\/\/\S+/);
    if (match) return match[0];
  }
  return null;
}

export default App;
