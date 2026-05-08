# Fetch. — Web

A web port of the Fetch. mobile app: paste a video URL (or share one from any app
on Android via the PWA share target), see every format the backend can pull, and
download in one tap.

## Stack

- Vite + React 18 + TypeScript
- Tailwind CSS
- lucide-react for icons
- Talks to the existing Node + yt-dlp backend in `../backend`

## Run locally

```bash
# 1. start the backend (in another terminal)
cd ../backend
npm install
npm run dev          # listens on http://localhost:3000

# 2. start the web app
cd ../web
cp .env.example .env # edits not required for the default local backend
npm install
npm run dev          # opens http://localhost:5173
```

By default the dev server points at `http://localhost:3000`. Override per-build
with `VITE_API_BASE_URL` in `.env`.

## "Forwarding from app" — share target

Once installed as a PWA on Android, Fetch shows up in the system share sheet.
Sharing any URL from another app forwards it to `/share?url=…&text=…&title=…`,
which the SPA reads on mount and pipes straight into the fetch flow — the
details modal opens automatically with the thumbnail, title, uploader,
duration, platform and the full list of formats.

On iOS the share-sheet integration isn't supported yet (no PWA share-target
support); users can still paste from clipboard via the input bar.

## Build for production

```bash
npm run build      # writes to web/dist
npm run preview    # serve dist/ locally
```

`web/dist` is a static bundle — deploy to any static host (Netlify, Vercel,
Cloudflare Pages, GitHub Pages, S3+CloudFront, etc.) and point
`VITE_API_BASE_URL` at the deployed backend. Make sure the host serves
`index.html` for unknown paths (SPA fallback) so `/share` works.

## Lint / typecheck

```bash
npm run typecheck
npm run lint
```
