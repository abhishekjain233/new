---
name: testing-fetch-web
description: Bring up the Fetch. backend + web/ frontend locally and exercise the paste-URL/details-modal/download/recents/share flows end-to-end. Use when verifying changes in `web/` or to `backend/` extraction routes.
---

# Testing the Fetch. web frontend

This covers the `web/` Vite app (introduced in PR #1) plus the Express + yt-dlp + Bull backend it talks to.

## Prereqs on the VM

- `redis-server` listening on `127.0.0.1:6379`. Verify with `redis-cli ping` → `PONG`.
  - On Ubuntu: `sudo apt-get install -y redis-server`. systemd may be blocked (`policy-rc.d returned 101`); the `redis-server` daemon usually starts automatically post-install. If not, run `redis-server --daemonize yes`.
- `yt-dlp` on PATH. Verify with `yt-dlp --version`. Install with `pip install -q yt-dlp` if missing.
- `ffmpeg` on PATH. Almost always pre-installed; `which ffmpeg`.

## Boot order

1. Backend `.env` (copy `.env.example`, then override):
   ```
   PORT=3000
   REDIS_URL=redis://127.0.0.1:6379
   YTDLP_PATH=$(which yt-dlp)
   TEMP_DIR=/tmp
   RATE_LIMIT_MAX=200          # raise for testing so polling doesn't 429
   NODE_ENV=development
   ```
   Then `cd backend && npm install && npm run dev`. Expect `fetch backend listening on :3000`.
2. Web `.env.local`:
   ```
   VITE_API_BASE_URL=http://localhost:3000
   ```
   Then `cd web && npm install && npm run dev`. Expect Vite ready on `http://localhost:5173`.

## Test URLs

- **Vimeo (recommended)** — `https://vimeo.com/76979871`. Public, stable, exercises the new `vimeo` host rule and the Video+Audio modal grouping. Does **not** require cookies.
- **SoundCloud (audio-only fallback)** — `https://soundcloud.com/forss/flickermood`. Useful if you want to exercise the Audio-only grouping section.
- **YouTube** — avoid on datacenter VMs (Railway/Fly/etc.). yt-dlp returns `BOT_CHECK_REQUIRED` unless you set `YTDLP_COOKIES_B64` to a base64 of a logged-in `cookies.txt`. The PR doesn't change the YouTube path, so testing on Vimeo is sufficient for `web/` changes.

## What to assert (and why)

1. **Modal title comes from yt-dlp** — paste the Vimeo URL, modal heading should contain the substring `"Vimeo Player"`. A hard-coded loader or stale state cannot fake the live title.
2. **Format-row state machine** — click Download on a format. The button text must transition `Download` → `Queued` (briefly) → `\d+%` (with progress bar) → `Saved` (green). If it stalls at `Queued`, the Bull worker isn't started or `/api/progress/:jobId` is failing.
3. **Real file written** — `ls -la /tmp/fetch_*.mp4` after Saved should show a non-zero file (yt-dlp's actual output). The browser also fires a download dialog (`triggerBrowserDownload` in `DetailsModal.tsx`).
4. **localStorage `fetch_recent_v1`** — must contain the just-fetched item with `url`, `title`, and `at`. After clicking the trash icon the section disappears.
5. **Web Share Target** — `http://localhost:5173/share?url=<encoded>` auto-fetches and the address bar is rewritten to `/share` (the `?url=` is stripped via `history.replaceState`). Refresh must NOT re-trigger the fetch.

## Known quirks (not bugs)

- For Vimeo, HLS audio streams come back from yt-dlp with `vcodec`/`acodec` flags that produce `videoOnly: false, audioOnly: false`, so they group under **Video + Audio** rather than Audio only. The grouping logic in `DetailsModal.groupFormats` is correct; this is a yt-dlp metadata quirk for HLS audio. Use SoundCloud if you specifically need to populate the Audio-only section.
- The PWA share-target manifest only matters on real Android over HTTPS. On localhost the `/share?url=` route still works and is the right thing to test.

## Devin Secrets Needed

- None for Vimeo/SoundCloud testing.
- `YTDLP_COOKIES_B64` (org-scoped) only if you need to test YouTube specifically. Format is base64 of a Netscape `cookies.txt` exported from a logged-in YouTube session.

## Quick sanity-check commands

```
# detectPlatform unit-call (after `npm run build` in backend/)
node -e "console.log(require('./dist/utils/detectPlatform').detectPlatform('https://vimeo.com/76979871'))"   # -> 'vimeo'
node -e "console.log(require('./dist/utils/detectPlatform').detectPlatform('https://example.com/foo'))"      # -> 'generic'

# Backend round-trip
curl -s -X POST http://localhost:3000/api/fetch-info -H 'Content-Type: application/json' \
  -d '{"url":"https://vimeo.com/76979871"}' | python3 -m json.tool | head

# Web bundle env-bake
grep -ohE 'http://localhost:3000' web/dist/assets/*.js | sort -u
```
