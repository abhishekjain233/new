import type { Platform } from './api';

export interface PlatformDescriptor {
  id: Platform;
  label: string;
  hint: string;
  homepage: string;
  /** Tailwind class for the colored dot/badge accent. */
  badge: string;
}

export const PLATFORMS: PlatformDescriptor[] = [
  { id: 'youtube',     label: 'YouTube',     hint: 'youtube.com / youtu.be',    homepage: 'https://m.youtube.com/',     badge: 'bg-red-500' },
  { id: 'instagram',   label: 'Instagram',   hint: 'instagram.com / reels',     homepage: 'https://www.instagram.com/', badge: 'bg-pink-500' },
  { id: 'facebook',    label: 'Facebook',    hint: 'facebook.com / fb.watch',   homepage: 'https://m.facebook.com/',    badge: 'bg-blue-500' },
  { id: 'tiktok',      label: 'TikTok',      hint: 'tiktok.com',                homepage: 'https://www.tiktok.com/',    badge: 'bg-zinc-200' },
  { id: 'twitter',     label: 'Twitter / X', hint: 'twitter.com / x.com',       homepage: 'https://x.com/',             badge: 'bg-sky-400' },
  { id: 'snapchat',    label: 'Snapchat',    hint: 'snapchat.com',              homepage: 'https://www.snapchat.com/',  badge: 'bg-yellow-400' },
  { id: 'reddit',      label: 'Reddit',      hint: 'reddit.com',                homepage: 'https://www.reddit.com/',    badge: 'bg-orange-500' },
  { id: 'vimeo',       label: 'Vimeo',       hint: 'vimeo.com',                 homepage: 'https://vimeo.com/',         badge: 'bg-cyan-400' },
  { id: 'dailymotion', label: 'Dailymotion', hint: 'dailymotion.com',           homepage: 'https://www.dailymotion.com/', badge: 'bg-blue-300' },
  { id: 'twitch',      label: 'Twitch',      hint: 'twitch.tv / clips',         homepage: 'https://www.twitch.tv/',     badge: 'bg-purple-500' },
  { id: 'soundcloud',  label: 'SoundCloud',  hint: 'soundcloud.com',            homepage: 'https://soundcloud.com/',    badge: 'bg-orange-400' },
];

export const PLATFORM_BY_ID: Record<string, PlatformDescriptor> = Object.fromEntries(
  PLATFORMS.map((p) => [p.id, p]),
);

export function platformLabel(id: string): string {
  return PLATFORM_BY_ID[id]?.label ?? 'Generic';
}
