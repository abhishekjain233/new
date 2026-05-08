# Fetch.

> **Download Anything. Keep Everything.**

Fetch. is a full-stack mobile video downloader for YouTube, Instagram and Snapchat. It pairs an Apple-Liquid-Glass dark React Native UI with a hardened Node + yt-dlp backend that streams downloads back to the device on demand.

```
fetch/
├── backend/    Node 20 · Express · TypeScript · yt-dlp · Bull · Redis
└── frontend/   Expo / React Native · TypeScript · Reanimated 2 · expo-media-library
```

## What's in the box

* **Three platform cards** with platform-coloured glass surfaces (YouTube red gradient, Instagram conic, Snapchat yellow).
* **Permission modal** on first launch (`AsyncStorage` key `fetch_media_permission`, never re-prompts).
* **Download toast** with four stages — Fetching → Downloading → Done → Save to Device — driven by spring/shimmer/successPop animations.
* **Recent Downloads** glass list, persisted via `@react-native-async-storage/async-storage`.
* **Backend pipeline**: `POST /api/fetch-info` → `POST /api/download` (Bull job) → `GET /api/progress/:jobId` polled at 500 ms → `GET /api/file/:jobId` ranged streaming → auto-delete after 10 min.
* **Manrope** typography wired through Google Fonts.
* No unnecessary re-renders — `React.memo`, `useMemo`, `useCallback` everywhere; all timers / intervals cleaned up on unmount.

## Quick start

### 1. Backend

```bash
cd backend
cp .env.example .env
docker compose up --build         # runs Redis + the API on :3000
```

Or without Docker:

```bash
# Requires: Node 20, redis-server, ffmpeg, yt-dlp on $PATH
cd backend
npm install
npm run dev
```

Health check: `curl http://localhost:3000/health` → `{ "success": true, "data": { "status": "ok" } }`.

### 2. Frontend

```bash
cd frontend
npm install
# Tell the app where the backend lives. By default we use http://localhost:3000.
# Override per-build via app.json `extra.apiBaseUrl`, e.g.:
#   "extra": { "apiBaseUrl": "http://192.168.1.42:3000" }
npx expo start
```

Open the QR code with Expo Go on iOS / Android, or run `npm run ios` / `npm run android` for a dev client build.

> ℹ️ When testing on a physical phone, replace `localhost` with your dev machine's LAN IP in `app.json`'s `extra.apiBaseUrl`. The phone cannot reach `localhost` on your laptop.

## API contract

| Method | Path | Body / Params | Returns |
| --- | --- | --- | --- |
| `POST` | `/api/fetch-info` | `{ url, platform }` | `{ id, title, thumbnail, duration, uploader, platform, url, formats[] }` |
| `POST` | `/api/download` | `{ url, platform, formatId? }` | `{ jobId }` (HTTP 202) |
| `GET`  | `/api/progress/:jobId` | — | `{ jobId, status, progress, speed?, eta?, downloadUrl?, errorCode?, errorMessage? }` |
| `GET`  | `/api/file/:jobId` | Optional `Range:` header | Streams the merged MP4, `Content-Disposition: attachment` |

All non-`200`/`202` responses follow the shape `{ success: false, error, message }`. Error codes include `INVALID_URL`, `PRIVATE_VIDEO`, `GEO_BLOCKED`, `NOT_FOUND`, `RATE_LIMITED`, `JOB_NOT_FOUND`, `NOT_READY`.

Rate limit: **20 requests / minute / IP** on `/api/*` (except `/api/file/*` which is doubled).

## Configuration

`backend/.env` — see [`backend/.env.example`](backend/.env.example):

| Var | Default | Purpose |
| --- | --- | --- |
| `PORT` | `3000` | HTTP port |
| `REDIS_URL` | `redis://localhost:6379` | Bull + progress store |
| `YTDLP_PATH` | `/usr/local/bin/yt-dlp` | yt-dlp binary |
| `TEMP_DIR` | `/tmp` | Where merged files live |
| `FILE_TTL_MINUTES` | `10` | Auto-delete TTL after first download |
| `RATE_LIMIT_MAX` | `20` | Requests per window per IP |
| `RATE_LIMIT_WINDOW_MS` | `60000` | Rate window |
| `MAX_CONCURRENT_DOWNLOADS` | `5` | Bull worker concurrency |

Frontend points at the backend through `app.json` → `expo.extra.apiBaseUrl`, which is read at runtime via `expo-constants`.

## Project layout

```
backend/src/
├── index.ts                   Express bootstrap, graceful shutdown
├── config.ts                  Typed env loader
├── routes/
│   ├── fetchInfo.ts           POST /api/fetch-info
│   ├── download.ts            POST /api/download
│   ├── progress.ts            GET  /api/progress/:jobId
│   └── file.ts                GET  /api/file/:jobId (Range support)
├── services/
│   ├── ytdlp.service.ts       yt-dlp spawn + progress-template parsing
│   ├── queue.service.ts       Bull queue + worker
│   ├── redis.service.ts       Shared ioredis connections
│   └── cleanup.service.ts     /tmp sweep + scheduled deletion
├── middlewares/
│   ├── rateLimiter.ts         express-rate-limit
│   ├── validateUrl.ts         URL & platform validation
│   └── errorHandler.ts        Maps YtDlpError → 4xx
└── utils/
    ├── parseProgress.ts       PRG + fallback line parser
    ├── detectPlatform.ts      Hostname → platform
    ├── generateJobId.ts       URL-safe random id
    └── logger.ts              JSONL logger

frontend/src/
├── App.tsx                    Permission gate + font loader
├── screens/
│   ├── HomeScreen.tsx         Header + cards + recent + toast
│   └── PermissionScreen.tsx   First-launch overlay
├── components/
│   ├── CategoryCard.tsx       YouTube / Instagram / Snapchat card
│   ├── DownloadToast.tsx      Bottom toast (4 stages)
│   ├── PermissionModal.tsx    Glass modal
│   ├── DownloadItem.tsx       Recent downloads row
│   ├── ProgressBar.tsx        Animated gradient + shimmer
│   ├── GlassSurface.tsx       Apple Liquid Glass primitive
│   ├── PlatformIcon.tsx       SVG platform glyphs
│   └── Text.tsx               Manrope-defaulted Text
├── services/
│   ├── api.service.ts         Backend client
│   └── storage.service.ts     AsyncStorage wrappers
├── hooks/
│   ├── useDownload.ts         Toast state machine + polling
│   └── usePermission.ts       Media library permission flow
├── constants/
│   ├── colors.ts              Liquid-glass palette + radii
│   ├── typography.ts          Manrope text styles
│   └── platforms.ts           Platform descriptors + URL detector
└── animations/springConfigs.ts  Reanimated spring/timing presets
```

## Behaviour notes

* **First launch** — `App.tsx` reads `fetch_media_permission` from AsyncStorage; if absent, `PermissionScreen` is shown over `HomeScreen` and the result is persisted regardless of choice.
* **Detect platform from URL locally** — `detectPlatform()` in `frontend/src/constants/platforms.ts` is invoked when the user presses the download button, so a YouTube link in the Snapchat card still routes correctly.
* **Polling** — `useDownload` polls `/api/progress/:jobId` every 500 ms and tears the interval down on unmount or dismiss.
* **Streaming downloads** — `routes/file.ts` uses `fs.createReadStream` and supports `Range: bytes=…` so the device can resume. `scheduleFileDeletion` then deletes the file after `FILE_TTL_MINUTES`.
* **Memory** — yt-dlp writes straight to `/tmp` and Express never buffers the file in memory.

## Development scripts

| Command | Where | What |
| --- | --- | --- |
| `npm run dev` | `backend` | tsx watcher |
| `npm run typecheck` | both | `tsc --noEmit` |
| `npm run lint` | both | ESLint |
| `npm run build` | `backend` | Compile to `dist/` |
| `npm start` | `backend` | Run compiled JS |
| `npx expo start` | `frontend` | Metro bundler |

## License

Private / personal use only — yt-dlp and the platform terms of service apply.
