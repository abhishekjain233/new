import type { Platform } from '../types';

const HOST_RULES: Array<{ platform: Platform; pattern: RegExp }> = [
  { platform: 'youtube', pattern: /(^|\.)youtube\.com$/i },
  { platform: 'youtube', pattern: /(^|\.)youtu\.be$/i },
  { platform: 'youtube', pattern: /(^|\.)m\.youtube\.com$/i },
  { platform: 'youtube', pattern: /(^|\.)music\.youtube\.com$/i },
  { platform: 'instagram', pattern: /(^|\.)instagram\.com$/i },
  { platform: 'instagram', pattern: /(^|\.)instagr\.am$/i },
  { platform: 'snapchat', pattern: /(^|\.)snapchat\.com$/i },
  { platform: 'snapchat', pattern: /(^|\.)story\.snapchat\.com$/i },
  { platform: 'tiktok', pattern: /(^|\.)tiktok\.com$/i },
  { platform: 'tiktok', pattern: /(^|\.)vm\.tiktok\.com$/i },
  { platform: 'facebook', pattern: /(^|\.)facebook\.com$/i },
  { platform: 'facebook', pattern: /(^|\.)fb\.watch$/i },
  { platform: 'facebook', pattern: /(^|\.)m\.facebook\.com$/i },
  { platform: 'twitter', pattern: /(^|\.)twitter\.com$/i },
  { platform: 'twitter', pattern: /(^|\.)x\.com$/i },
  { platform: 'twitter', pattern: /(^|\.)t\.co$/i },
  { platform: 'vimeo', pattern: /(^|\.)vimeo\.com$/i },
  { platform: 'dailymotion', pattern: /(^|\.)dailymotion\.com$/i },
  { platform: 'dailymotion', pattern: /(^|\.)dai\.ly$/i },
  { platform: 'reddit', pattern: /(^|\.)reddit\.com$/i },
  { platform: 'reddit', pattern: /(^|\.)redd\.it$/i },
  { platform: 'twitch', pattern: /(^|\.)twitch\.tv$/i },
  { platform: 'twitch', pattern: /(^|\.)clips\.twitch\.tv$/i },
  { platform: 'soundcloud', pattern: /(^|\.)soundcloud\.com$/i },
];

const ALLOWED_PLATFORMS: ReadonlySet<Platform> = new Set<Platform>([
  'youtube',
  'instagram',
  'snapchat',
  'tiktok',
  'facebook',
  'twitter',
  'vimeo',
  'dailymotion',
  'reddit',
  'twitch',
  'soundcloud',
  'generic',
]);

export function detectPlatform(rawUrl: string): Platform | null {
  if (!rawUrl) return null;
  let parsed: URL;
  try {
    parsed = new URL(rawUrl.trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
  const host = parsed.hostname.toLowerCase();
  for (const rule of HOST_RULES) {
    if (rule.pattern.test(host)) return rule.platform;
  }
  return 'generic';
}

export function isPlatformAllowed(platform: string): platform is Platform {
  return ALLOWED_PLATFORMS.has(platform as Platform);
}
