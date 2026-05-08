import { Platform, type TextStyle } from 'react-native';

export const fontFamily = {
  regular: 'Manrope_500Medium',
  medium: 'Manrope_500Medium',
  semibold: 'Manrope_600SemiBold',
  bold: 'Manrope_700Bold',
  extrabold: 'Manrope_800ExtraBold',
} as const;

const baseLetter = Platform.select({ ios: 0, android: 0, default: 0 });

export const typography: Record<
  | 'appName'
  | 'tagline'
  | 'sectionLabel'
  | 'cardTitle'
  | 'cardSubtitle'
  | 'modalTitle'
  | 'body'
  | 'button'
  | 'toastLabel'
  | 'toastTitle'
  | 'meta',
  TextStyle
> = {
  appName: {
    fontFamily: fontFamily.extrabold,
    fontSize: 38,
    color: '#f5f5f7',
    letterSpacing: -1.5,
  },
  tagline: {
    fontFamily: fontFamily.medium,
    fontSize: 13,
    color: 'rgba(245,245,247,0.50)',
    letterSpacing: baseLetter,
  },
  sectionLabel: {
    fontFamily: fontFamily.bold,
    fontSize: 11,
    color: 'rgba(245,245,247,0.50)',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  cardTitle: {
    fontFamily: fontFamily.bold,
    fontSize: 17,
    color: '#f5f5f7',
  },
  cardSubtitle: {
    fontFamily: fontFamily.medium,
    fontSize: 12,
    color: 'rgba(245,245,247,0.50)',
  },
  modalTitle: {
    fontFamily: fontFamily.bold,
    fontSize: 20,
    color: '#f5f5f7',
  },
  body: {
    fontFamily: fontFamily.medium,
    fontSize: 13.5,
    color: 'rgba(245,245,247,0.50)',
    lineHeight: 19,
  },
  button: {
    fontFamily: fontFamily.bold,
    fontSize: 15,
    color: '#ffffff',
  },
  toastLabel: {
    fontFamily: fontFamily.medium,
    fontSize: 11,
    color: 'rgba(245,245,247,0.50)',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
  toastTitle: {
    fontFamily: fontFamily.bold,
    fontSize: 16,
    color: '#f5f5f7',
  },
  meta: {
    fontFamily: fontFamily.semibold,
    fontSize: 11,
    color: 'rgba(245,245,247,0.50)',
  },
};
