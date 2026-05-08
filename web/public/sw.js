// Minimal service worker — required for Web Share Target to be installable as a PWA.
// We deliberately do NOT cache app assets (yet) so updates ship instantly. The
// share-target itself is declared in manifest.webmanifest and is handled by the
// SPA router on /share — the SW is only here so Chrome treats us as installable.

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (_event) => {
  // Network-first; let the browser handle everything.
});
