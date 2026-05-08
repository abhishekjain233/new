export const colors = {
  background: '#080810',
  glassSurface: 'rgba(255,255,255,0.07)',
  glassBorder: 'rgba(255,255,255,0.12)',
  glassDeepBg: 'rgba(28,28,40,0.92)',
  glassDeepBorder: 'rgba(255,255,255,0.14)',
  toastBg: 'rgba(22,22,32,0.90)',

  primaryText: '#f5f5f7',
  secondaryText: 'rgba(245,245,247,0.50)',
  faintText: 'rgba(245,245,247,0.30)',

  accentStart: '#7c5cfc',
  accentEnd: '#4facfe',

  success: '#30d158',
  error: '#ff453a',

  overlay: 'rgba(0,0,0,0.72)',

  youtube: '#FF0000',
  youtubeStart: '#ff4444',
  youtubeEnd: '#cc0000',

  instagramStart: '#833ab4',
  instagramMid: '#fd1d1d',
  instagramEnd: '#fcb045',

  snapchat: '#FFFC00',
  snapchatDark: '#1a1a1a',

  inputBg: 'rgba(255,255,255,0.06)',
  inputBorder: 'rgba(255,255,255,0.10)',
  inputBgFocus: 'rgba(255,255,255,0.10)',

  shadowCard: 'rgba(0,0,0,0.25)',
  shadowModal: 'rgba(0,0,0,0.60)',
} as const;

export const radii = {
  modal: 28,
  card: 22,
  input: 13,
  button: 16,
  toast: 20,
  pill: 999,
} as const;

export const accentGradient = [colors.accentStart, colors.accentEnd] as const;
export const youtubeGradient = [colors.youtubeStart, colors.youtubeEnd] as const;
export const instagramGradient = [
  colors.instagramStart,
  colors.instagramMid,
  colors.instagramEnd,
] as const;
