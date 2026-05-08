import fs from 'node:fs';
import path from 'node:path';

import { config } from '../config';
import { logger } from '../utils/logger';

const log = logger.child('cookies');

let materializedPath: string | null = null;

/**
 * Decode the YTDLP_COOKIES_B64 env var (Netscape cookies.txt format) and
 * write it to a file on disk. The file path is then passed to yt-dlp via
 * --cookies. Called once at startup. Safe to call multiple times.
 *
 * Set this env var to bypass YouTube's "Sign in to confirm you're not a bot"
 * wall on datacenter IPs (Railway, Fly, Render, etc.) and to download
 * Instagram / Snapchat content that requires a logged-in session.
 *
 * Export instructions: install the "Get cookies.txt LOCALLY" browser
 * extension, log into youtube.com (and instagram.com if needed), export
 * cookies.txt, then `base64 -w0 cookies.txt` and paste the output as the
 * value of YTDLP_COOKIES_B64.
 */
export function initCookiesFile(): string | null {
  if (materializedPath) return materializedPath;
  const b64 = config.cookiesB64;
  if (!b64) return null;

  const decoded = Buffer.from(b64, 'base64').toString('utf8');
  if (!decoded.includes('# Netscape HTTP Cookie File') && !decoded.includes('\t')) {
    log.warn(
      'YTDLP_COOKIES_B64 is set but does not look like a Netscape cookies.txt — ignoring',
    );
    return null;
  }

  const target = path.join(config.tempDir, 'fetch_cookies.txt');
  fs.writeFileSync(target, decoded, { mode: 0o600 });
  materializedPath = target;
  log.info(`cookies file ready at ${target} (${decoded.length} bytes)`);
  return materializedPath;
}

export function getCookiesPath(): string | null {
  return materializedPath;
}
