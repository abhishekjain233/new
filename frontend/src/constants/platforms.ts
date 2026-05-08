export type Platform = 'youtube' | 'instagram' | 'snapchat';

export interface PlatformDescriptor {
  id: Platform;
  label: string;
  emoji: string;
  subtitle: string;
  inputPlaceholder: string;
}

export const PLATFORMS: PlatformDescriptor[] = [
  {
    id: 'youtube',
    label: 'YouTube',
    emoji: '📺',
    subtitle: 'Paste a YouTube video link',
    inputPlaceholder: 'Paste link here…',
  },
  {
    id: 'instagram',
    label: 'Instagram',
    emoji: '📸',
    subtitle: 'Paste a Reel or Post link',
    inputPlaceholder: 'Paste link here…',
  },
  {
    id: 'snapchat',
    label: 'Snapchat',
    emoji: '👻',
    subtitle: 'Paste a Spotlight link',
    inputPlaceholder: 'Paste link here…',
  },
];

const PATTERNS: Record<Platform, RegExp[]> = {
  youtube: [/(^|\.)youtube\.com$/i, /(^|\.)youtu\.be$/i, /(^|\.)m\.youtube\.com$/i],
  instagram: [/(^|\.)instagram\.com$/i, /(^|\.)instagr\.am$/i],
  snapchat: [/(^|\.)snapchat\.com$/i, /(^|\.)story\.snapchat\.com$/i],
};

export function detectPlatform(url: string): Platform | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase();
  for (const [platform, patterns] of Object.entries(PATTERNS) as [Platform, RegExp[]][]) {
    if (patterns.some((p) => p.test(host))) return platform;
  }
  return null;
}
