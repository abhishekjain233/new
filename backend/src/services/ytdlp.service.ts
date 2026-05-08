import { type ChildProcessByStdio, spawn } from 'node:child_process';
import path from 'node:path';
import type { Readable } from 'node:stream';

import { config } from '../config';
import type { MediaInfo, MediaFormat, Platform } from '../types';
import { logger } from '../utils/logger';
import { parseProgressLine, type ParsedProgress } from '../utils/parseProgress';
import { getCookiesPath } from './cookies.service';

const log = logger.child('ytdlp');

export class YtDlpError extends Error {
  constructor(
    public code: string,
    message: string,
    public stderr?: string,
  ) {
    super(message);
    this.name = 'YtDlpError';
  }
}

interface RawFormat {
  format_id: string;
  ext?: string;
  vcodec?: string;
  acodec?: string;
  height?: number;
  width?: number;
  fps?: number;
  filesize?: number;
  filesize_approx?: number;
  format_note?: string;
  resolution?: string;
}

interface RawInfo {
  id: string;
  title?: string;
  description?: string;
  uploader?: string;
  channel?: string;
  thumbnail?: string;
  duration?: number;
  webpage_url?: string;
  formats?: RawFormat[];
}

const COMMON_ARGS = [
  '--no-warnings',
  '--no-call-home',
  '--no-playlist',
  '--ignore-config',
  '--no-color',
];

function buildArgs(extra: string[]): string[] {
  const cookies = getCookiesPath();
  const args: string[] = [...COMMON_ARGS];
  if (cookies) args.push('--cookies', cookies);
  args.push(...extra);
  return args;
}

export async function fetchInfo(url: string, platform: Platform): Promise<MediaInfo> {
  const args = buildArgs(['--dump-single-json', url]);
  const { stdout, stderr, code } = await runCapture(config.ytdlpPath, args);
  if (code !== 0) {
    throw classifyError(stderr, code);
  }
  let raw: RawInfo;
  try {
    raw = JSON.parse(stdout) as RawInfo;
  } catch (err) {
    throw new YtDlpError(
      'PARSE_ERROR',
      `Failed to parse yt-dlp output: ${(err as Error).message}`,
      stderr,
    );
  }
  return mapInfo(raw, url, platform);
}

export interface DownloadOptions {
  url: string;
  platform: Platform;
  jobId: string;
  formatId?: string;
  onProgress: (p: ParsedProgress) => void;
  signal?: AbortSignal;
}

export interface DownloadResult {
  filePath: string;
}

const PROGRESS_TEMPLATE =
  'PRG %(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s';

export async function downloadMedia(opts: DownloadOptions): Promise<DownloadResult> {
  const outputBasename = `fetch_${opts.jobId}`;
  const outputTemplate = path.join(config.tempDir, `${outputBasename}.%(ext)s`);

  const args = buildArgs([
    '--newline',
    '--progress',
    '--progress-template',
    PROGRESS_TEMPLATE,
    '-f',
    opts.formatId ?? defaultFormatSelector(opts.platform),
    ...mergeOutputArgs(opts.platform),
    '-o',
    outputTemplate,
    '--no-part',
    '--no-mtime',
    opts.url,
  ]);

  const files: string[] = [];
  const state: { lastProgress: ParsedProgress | null } = { lastProgress: null };

  const onLine = (line: string) => {
    if (line.startsWith('PRG ')) {
      const p = parseProgressLine(line);
      if (p) {
        state.lastProgress = p;
        opts.onProgress(p);
      }
      return;
    }
    if (line.includes('%') && line.toLowerCase().includes('[download]')) {
      const p = parseProgressLine(line);
      if (p) {
        state.lastProgress = p;
        opts.onProgress(p);
      }
    }
    const dest = parseDestination(line);
    if (dest) files.push(dest);
  };

  const { code, stderr } = await runStream(config.ytdlpPath, args, onLine, opts.signal);
  if (code !== 0) {
    throw classifyError(stderr, code);
  }
  if (state.lastProgress) {
    opts.onProgress({ ...state.lastProgress, progress: 1 });
  }
  const filePath = pickFinal(files, opts.platform, outputBasename);
  return { filePath };
}

function defaultFormatSelector(platform: Platform): string {
  if (platform === 'youtube') {
    return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best';
  }
  return 'best[ext=mp4]/best';
}

function mergeOutputArgs(platform: Platform): string[] {
  if (platform === 'youtube') {
    return ['--merge-output-format', 'mp4'];
  }
  return [];
}

function pickFinal(files: string[], platform: Platform, basename: string): string {
  if (files.length === 0) {
    const fallbackExt = platform === 'youtube' ? 'mp4' : 'mp4';
    return path.join(config.tempDir, `${basename}.${fallbackExt}`);
  }
  return files[files.length - 1];
}

function parseDestination(line: string): string | null {
  let m = /\[\w+\]\s+Destination:\s+(.+)$/.exec(line);
  if (m) return m[1].trim();
  m = /\[Merger\]\s+Merging formats into\s+"(.+)"$/.exec(line);
  if (m) return m[1].trim();
  m = /\[ExtractAudio\]\s+Destination:\s+(.+)$/.exec(line);
  if (m) return m[1].trim();
  return null;
}

function mapInfo(raw: RawInfo, url: string, platform: Platform): MediaInfo {
  const formats = (raw.formats ?? [])
    .map((f) => mapFormat(f))
    .filter((f) => Boolean(f.vcodec) || Boolean(f.acodec));
  return {
    id: raw.id,
    title: raw.title ?? 'Untitled',
    thumbnail: raw.thumbnail,
    duration: raw.duration,
    uploader: raw.uploader ?? raw.channel,
    platform,
    url: raw.webpage_url ?? url,
    formats,
  };
}

function mapFormat(f: RawFormat): MediaFormat {
  const videoOnly = !!(f.vcodec && f.vcodec !== 'none' && (!f.acodec || f.acodec === 'none'));
  const audioOnly = !!(f.acodec && f.acodec !== 'none' && (!f.vcodec || f.vcodec === 'none'));
  const filesize = f.filesize ?? f.filesize_approx;
  const resolution = f.resolution ?? (f.height ? `${f.width ?? '?'}x${f.height}` : undefined);
  return {
    id: f.format_id,
    ext: f.ext ?? 'mp4',
    width: f.width,
    height: f.height,
    fps: f.fps,
    resolution,
    filesize,
    vcodec: f.vcodec,
    acodec: f.acodec,
    videoOnly,
    audioOnly,
    note: f.format_note,
  };
}

function classifyError(stderr: string | undefined, code: number | null): YtDlpError {
  const tail = (stderr ?? '').toLowerCase();
  if (tail.includes("confirm you're not a bot") || tail.includes('confirm you’re not a bot')) {
    return new YtDlpError(
      'BOT_CHECK_REQUIRED',
      'YouTube is asking the server to log in. Set YTDLP_COOKIES_B64 on the backend.',
      stderr,
    );
  }
  if (tail.includes('private') || tail.includes('login required') || tail.includes('sign in')) {
    return new YtDlpError('PRIVATE_VIDEO', 'This video is private or requires authentication.', stderr);
  }
  if (tail.includes('geo') || tail.includes('not available in your country')) {
    return new YtDlpError('GEO_BLOCKED', 'This video is not available in this region.', stderr);
  }
  if (
    tail.includes('unsupported url') ||
    tail.includes('does not appear to be a valid') ||
    tail.includes('unable to extract')
  ) {
    return new YtDlpError('INVALID_URL', 'The provided URL is not supported.', stderr);
  }
  if (tail.includes('http error 404') || tail.includes('not found')) {
    return new YtDlpError('NOT_FOUND', 'The video could not be found.', stderr);
  }
  return new YtDlpError(
    'DOWNLOAD_FAILED',
    `yt-dlp exited with status ${code ?? 'unknown'}`,
    stderr,
  );
}

interface CaptureResult {
  stdout: string;
  stderr: string;
  code: number | null;
}

function runCapture(bin: string, args: string[]): Promise<CaptureResult> {
  return new Promise((resolve, reject) => {
    const proc = spawn(bin, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    proc.stdout.on('data', (c: Buffer) => stdoutChunks.push(c));
    proc.stderr.on('data', (c: Buffer) => stderrChunks.push(c));
    proc.on('error', (err) => reject(err));
    proc.on('close', (code) => {
      resolve({
        stdout: Buffer.concat(stdoutChunks).toString('utf8'),
        stderr: Buffer.concat(stderrChunks).toString('utf8'),
        code,
      });
    });
  });
}

interface StreamResult {
  code: number | null;
  stderr: string;
}

function runStream(
  bin: string,
  args: string[],
  onLine: (line: string) => void,
  signal: AbortSignal | undefined,
): Promise<StreamResult> {
  return new Promise((resolve, reject) => {
    let proc: ChildProcessByStdio<null, Readable, Readable>;
    try {
      proc = spawn(bin, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (err) {
      reject(err);
      return;
    }

    const handleAbort = () => {
      log.warn('aborting yt-dlp via signal');
      proc.kill('SIGTERM');
      setTimeout(() => proc.kill('SIGKILL'), 3000).unref();
    };
    if (signal) {
      if (signal.aborted) handleAbort();
      else signal.addEventListener('abort', handleAbort, { once: true });
    }

    const stderrChunks: string[] = [];
    let stderrLen = 0;

    const eatLines = (stream: Readable) => {
      let buf = '';
      stream.setEncoding('utf8');
      stream.on('data', (chunk: string) => {
        buf += chunk;
        let idx = buf.indexOf('\n');
        while (idx >= 0) {
          const line = buf.slice(0, idx).replace(/\r$/, '');
          buf = buf.slice(idx + 1);
          if (line) onLine(line);
          idx = buf.indexOf('\n');
        }
      });
      stream.on('end', () => {
        const tail = buf.replace(/\r$/, '');
        if (tail) onLine(tail);
      });
    };

    eatLines(proc.stdout);
    proc.stderr.setEncoding('utf8');
    proc.stderr.on('data', (chunk: string) => {
      stderrLen += chunk.length;
      stderrChunks.push(chunk);
      if (stderrLen > 64_000) {
        const drop = stderrChunks.shift();
        stderrLen -= drop ? drop.length : 0;
      }
    });

    proc.on('error', reject);
    proc.on('close', (code) => {
      if (signal) signal.removeEventListener('abort', handleAbort);
      resolve({ code, stderr: stderrChunks.join('') });
    });
  });
}
