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
];

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
  return null;
}

export function isPlatformAllowed(platform: string): platform is Platform {
  return platform === 'youtube' || platform === 'instagram' || platform === 'snapchat';
}
