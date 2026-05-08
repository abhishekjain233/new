import React from 'react';
import { Platform, StyleSheet, View, type ViewProps, type ViewStyle } from 'react-native';
import { BlurView } from 'expo-blur';

import { colors, radii } from '@/constants/colors';

interface Props extends ViewProps {
  radius?: number;
  intensity?: number;
  borderColor?: string;
  surfaceColor?: string;
  innerStyle?: ViewStyle;
}

/**
 * Apple Liquid Glass-ish surface. Uses BlurView on iOS where it's effective and
 * a translucent fallback on Android (where backdrop blur is unreliable).
 */
export const GlassSurface: React.FC<Props> = ({
  radius = radii.card,
  intensity = 24,
  borderColor = colors.glassBorder,
  surfaceColor = colors.glassSurface,
  style,
  innerStyle,
  children,
  ...rest
}) => {
  const supportsBlur = Platform.OS === 'ios';
  return (
    <View
      {...rest}
      style={[
        styles.outer,
        {
          borderRadius: radius,
          borderColor,
          backgroundColor: supportsBlur ? 'transparent' : surfaceColor,
        },
        style,
      ]}
    >
      {supportsBlur ? (
        <BlurView intensity={intensity} tint="dark" style={[StyleSheet.absoluteFill]}>
          <View
            pointerEvents="none"
            style={[StyleSheet.absoluteFill, { backgroundColor: surfaceColor }]}
          />
        </BlurView>
      ) : null}
      <View style={[styles.inner, innerStyle]}>{children}</View>
    </View>
  );
};

const styles = StyleSheet.create({
  outer: {
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth,
  },
  inner: {
    flex: 1,
  },
});
