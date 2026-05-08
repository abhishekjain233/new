import React, { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { accentGradient, colors, radii } from '@/constants/colors';

interface Props {
  progress: number;
  indeterminate?: boolean;
  height?: number;
}

export const ProgressBar: React.FC<Props> = React.memo(({ progress, indeterminate, height = 4 }) => {
  const fill = useSharedValue(0);
  const shimmer = useSharedValue(-1);

  useEffect(() => {
    fill.value = withTiming(Math.max(0, Math.min(1, progress)), {
      duration: 220,
      easing: Easing.out(Easing.quad),
    });
  }, [progress, fill]);

  useEffect(() => {
    shimmer.value = -1;
    shimmer.value = withRepeat(
      withTiming(2, { duration: 1500, easing: Easing.linear }),
      -1,
      false,
    );
  }, [shimmer]);

  const fillStyle = useAnimatedStyle(() => ({
    width: `${fill.value * 100}%`,
  }));

  const shimmerStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: shimmer.value * 200 }],
  }));

  return (
    <View style={[styles.track, { height, borderRadius: height }]}>
      <Animated.View style={[styles.fillWrap, fillStyle]}>
        <LinearGradient
          colors={[...accentGradient]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 0 }}
          style={[styles.fill, { borderRadius: height }]}
        />
        {indeterminate && (
          <Animated.View pointerEvents="none" style={[styles.shimmer, shimmerStyle]} />
        )}
      </Animated.View>
    </View>
  );
});

ProgressBar.displayName = 'ProgressBar';

const styles = StyleSheet.create({
  track: {
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.08)',
    overflow: 'hidden',
    borderRadius: radii.pill,
  },
  fillWrap: {
    height: '100%',
    overflow: 'hidden',
  },
  fill: {
    flex: 1,
  },
  shimmer: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    left: 0,
    width: 80,
    backgroundColor: colors.primaryText,
    opacity: 0.18,
  },
});
