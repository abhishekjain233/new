import React from 'react';
import { StyleSheet, View, type ViewStyle } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Svg, { Path } from 'react-native-svg';

import { colors, instagramGradient } from '@/constants/colors';
import type { Platform } from '@/constants/platforms';

interface Props {
  platform: Platform;
  size?: number;
}

export const PlatformIcon: React.FC<Props> = React.memo(({ platform, size = 48 }) => {
  const radius = Math.round(size * 0.29);
  const containerStyle: ViewStyle = {
    width: size,
    height: size,
    borderRadius: radius,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  };
  const iconSize = Math.round(size * 0.55);
  if (platform === 'instagram') {
    return (
      <View style={containerStyle}>
        <LinearGradient
          colors={[instagramGradient[0], instagramGradient[1], instagramGradient[2]]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={StyleSheet.absoluteFill}
        />
        <InstagramGlyph size={iconSize} color="#ffffff" />
      </View>
    );
  }
  if (platform === 'youtube') {
    return (
      <View style={[containerStyle, { backgroundColor: colors.youtube }]}>
        <YoutubeGlyph size={iconSize} color="#ffffff" />
      </View>
    );
  }
  return (
    <View style={[containerStyle, { backgroundColor: colors.snapchat }]}>
      <SnapchatGlyph size={iconSize} color={colors.snapchatDark} />
    </View>
  );
});

PlatformIcon.displayName = 'PlatformIcon';

const YoutubeGlyph: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <Svg width={size} height={size * 0.7} viewBox="0 0 24 17" fill="none">
    <Path
      d="M23.5 2.6c-.27-1-1.07-1.78-2.07-2.04C19.6 0 12 0 12 0s-7.6 0-9.43.56C1.57.82.77 1.6.5 2.6 0 4.42 0 8.5 0 8.5s0 4.08.5 5.9c.27 1 1.07 1.78 2.07 2.04C4.4 17 12 17 12 17s7.6 0 9.43-.56c1-.26 1.8-1.04 2.07-2.04.5-1.82.5-5.9.5-5.9s0-4.08-.5-5.9zM9.6 12.13V4.87L15.92 8.5l-6.32 3.63z"
      fill={color}
    />
  </Svg>
);

const InstagramGlyph: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <Path
      d="M12 2.16c3.2 0 3.58 0 4.85.07 1.17.05 1.8.25 2.22.41.56.21.96.47 1.38.89.42.42.68.82.89 1.38.16.42.36 1.05.41 2.22.06 1.27.07 1.65.07 4.85 0 3.2 0 3.58-.07 4.85-.05 1.17-.25 1.8-.41 2.22-.21.56-.47.96-.89 1.38-.42.42-.82.68-1.38.89-.42.16-1.05.36-2.22.41-1.27.06-1.65.07-4.85.07-3.2 0-3.58 0-4.85-.07-1.17-.05-1.8-.25-2.22-.41-.56-.21-.96-.47-1.38-.89-.42-.42-.68-.82-.89-1.38-.16-.42-.36-1.05-.41-2.22C2.17 15.58 2.16 15.2 2.16 12c0-3.2 0-3.58.07-4.85.05-1.17.25-1.8.41-2.22.21-.56.47-.96.89-1.38.42-.42.82-.68 1.38-.89.42-.16 1.05-.36 2.22-.41C8.42 2.17 8.8 2.16 12 2.16zM12 0C8.74 0 8.33.01 7.05.07 5.78.13 4.9.33 4.14.63c-.78.3-1.44.71-2.1 1.37C1.38 2.66.97 3.32.67 4.1.37 4.86.17 5.74.11 7.01.05 8.29.04 8.7.04 11.96s.01 3.67.07 4.95c.06 1.27.26 2.15.56 2.91.3.78.71 1.44 1.37 2.1.66.66 1.32 1.07 2.1 1.37.76.3 1.64.5 2.91.56 1.28.06 1.69.07 4.95.07s3.67-.01 4.95-.07c1.27-.06 2.15-.26 2.91-.56.78-.3 1.44-.71 2.1-1.37.66-.66 1.07-1.32 1.37-2.1.3-.76.5-1.64.56-2.91.06-1.28.07-1.69.07-4.95s-.01-3.67-.07-4.95c-.06-1.27-.26-2.15-.56-2.91-.3-.78-.71-1.44-1.37-2.1C21.34 1.38 20.68.97 19.9.67 19.14.37 18.26.17 16.99.11 15.71.05 15.3.04 12.04.04 11.94 0 12 0 12 0z"
      fill={color}
    />
    <Path
      d="M12 5.84a6.16 6.16 0 1 0 0 12.32 6.16 6.16 0 0 0 0-12.32zm0 10.16a4 4 0 1 1 0-8 4 4 0 0 1 0 8z"
      fill={color}
    />
    <Path
      d="M19.85 5.6a1.44 1.44 0 1 1-2.88 0 1.44 1.44 0 0 1 2.88 0z"
      fill={color}
    />
  </Svg>
);

const SnapchatGlyph: React.FC<{ size: number; color: string }> = ({ size, color }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <Path
      d="M12 1.6c2.5 0 4.92 1.45 5.97 3.95.36.85.34 2.27.32 3.42v.07c-.01.34-.02.66-.02.96 0 .12.04.21.16.27.18.08.45.08.74-.04.21-.08.46-.21.66-.21.21 0 .43.04.6.13.5.21.6.66.6.96-.02.7-.91 1.04-1.55 1.27-.13.06-.32.13-.45.21-.13.08-.13.13-.06.34.04.13.91 2.27 3.04 2.6.21.04.34.21.34.43 0 .13-.06.21-.13.34-.36.81-1.91 1.13-2.55 1.21-.06.04-.13.27-.16.43-.04.21-.08.43-.16.66-.06.27-.27.4-.55.4h-.04c-.21 0-.43-.04-.7-.08-.27-.06-.55-.13-.91-.13-.21 0-.43.04-.66.06-.55.13-1.04.43-1.62.81-.81.55-1.74 1.13-3.13 1.13s-2.32-.6-3.13-1.13c-.55-.4-1.04-.7-1.6-.81-.21-.04-.43-.06-.66-.06-.4 0-.7.06-.91.13-.27.06-.55.13-.74.13-.36 0-.55-.21-.6-.43-.04-.21-.13-.43-.16-.66-.04-.16-.13-.4-.16-.43-.66-.06-2.21-.4-2.55-1.21-.06-.13-.13-.21-.13-.34 0-.21.16-.4.34-.43 2.13-.34 3.04-2.49 3.04-2.6.06-.21.06-.27-.06-.34-.13-.06-.32-.16-.45-.21-.66-.27-1.55-.6-1.55-1.27 0-.27.13-.74.6-.96.16-.06.4-.13.6-.13.21 0 .45.13.66.21.27.13.55.16.74.04.13-.06.16-.16.16-.27 0-.27-.02-.6-.04-.96v-.04c-.04-1.13-.06-2.55.32-3.42C7.08 3.05 9.5 1.6 12 1.6z"
      fill={color}
    />
  </Svg>
);
