import React, { useEffect, useMemo } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { springConfigs } from '@/animations/springConfigs';
import { GlassSurface } from '@/components/GlassSurface';
import { ProgressBar } from '@/components/ProgressBar';
import Text from '@/components/Text';
import { accentGradient, colors, radii } from '@/constants/colors';
import { typography } from '@/constants/typography';
import type { Stage, ToastState } from '@/hooks/useDownload';

interface Props {
  state: ToastState;
  onSave: () => void;
  onDismiss: () => void;
}

export const DownloadToast: React.FC<Props> = React.memo(({ state, onSave, onDismiss }) => {
  const opacity = useSharedValue(0);
  const translate = useSharedValue(80);
  const scale = useSharedValue(0.92);

  useEffect(() => {
    if (state.visible) {
      opacity.value = withTiming(1, { duration: 350, easing: Easing.out(Easing.cubic) });
      translate.value = withSpring(0, springConfigs.toast);
      scale.value = withSpring(1, springConfigs.toast);
    } else {
      opacity.value = withTiming(0, { duration: 320, easing: Easing.in(Easing.quad) });
      translate.value = withTiming(40, { duration: 320, easing: Easing.in(Easing.quad) });
      scale.value = withTiming(0.94, { duration: 320, easing: Easing.in(Easing.quad) });
    }
  }, [opacity, scale, state.visible, translate]);

  const containerStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ translateY: translate.value }, { scale: scale.value }],
  }));

  if (!state.visible) return null;

  return (
    <View pointerEvents="box-none" style={styles.wrapper}>
      <Animated.View style={[styles.toast, containerStyle]}>
        <GlassSurface
          radius={radii.toast}
          surfaceColor={colors.toastBg}
          intensity={30}
          style={styles.glass}
        >
          <View style={styles.content}>
            <ToastHeader state={state} />
            <ToastBody state={state} />
            {state.stage === 'savePrompt' ? (
              <SaveButton onSave={onSave} />
            ) : null}
            {state.stage === 'error' ? (
              <Pressable onPress={onDismiss} style={styles.errorClose} hitSlop={8}>
                <Text style={styles.errorCloseText}>Dismiss</Text>
              </Pressable>
            ) : null}
          </View>
        </GlassSurface>
      </Animated.View>
    </View>
  );
});

DownloadToast.displayName = 'DownloadToast';

const ToastHeader: React.FC<{ state: ToastState }> = React.memo(({ state }) => {
  const meta = useMemo(() => labelFor(state.stage), [state.stage]);
  return (
    <View style={styles.headerRow}>
      <ToastIcon stage={state.stage} />
      <View style={styles.headerText}>
        <Text style={[typography.toastLabel, meta.color ? { color: meta.color } : null]}>
          {meta.label}
        </Text>
        <Text style={typography.toastTitle}>{state.title}</Text>
      </View>
    </View>
  );
});
ToastHeader.displayName = 'ToastHeader';

const ToastBody: React.FC<{ state: ToastState }> = React.memo(({ state }) => {
  if (state.stage === 'fetching') {
    return (
      <View style={styles.body}>
        <ProgressBar progress={0.25} indeterminate height={3} />
      </View>
    );
  }
  if (state.stage === 'downloading' || state.stage === 'saving') {
    const pctText = `${Math.round(Math.max(0, Math.min(1, state.progress)) * 100)}%`;
    return (
      <View style={styles.body}>
        <ProgressBar progress={state.progress} indeterminate={false} height={6} />
        <View style={styles.metaRow}>
          <Text style={typography.meta}>{pctText}</Text>
          {state.speed ? <Text style={typography.meta}>{state.speed}</Text> : null}
          {state.eta ? <Text style={typography.meta}>ETA {state.eta}</Text> : null}
        </View>
      </View>
    );
  }
  return null;
});
ToastBody.displayName = 'ToastBody';

const ToastIcon: React.FC<{ stage: Stage }> = React.memo(({ stage }) => {
  const scale = useSharedValue(1);
  useEffect(() => {
    scale.value = 1;
    if (stage === 'fetching') {
      scale.value = withRepeat(
        withSequence(
          withTiming(1.08, { duration: 600, easing: Easing.inOut(Easing.ease) }),
          withTiming(1, { duration: 600, easing: Easing.inOut(Easing.ease) }),
        ),
        -1,
        false,
      );
    } else if (stage === 'downloading') {
      scale.value = withRepeat(
        withSequence(
          withTiming(1.12, { duration: 350, easing: Easing.out(Easing.cubic) }),
          withTiming(1, { duration: 450, easing: Easing.in(Easing.cubic) }),
        ),
        -1,
        false,
      );
    } else if (stage === 'done' || stage === 'savePrompt') {
      scale.value = withSequence(
        withTiming(0.6, { duration: 0 }),
        withSpring(1.15, springConfigs.bouncy),
        withSpring(1, springConfigs.bouncy),
      );
    } else if (stage === 'error') {
      scale.value = withSequence(
        withTiming(1.1, { duration: 120 }),
        withTiming(1, { duration: 180 }),
      );
    }
  }, [scale, stage]);

  const animatedStyle = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));
  const emoji = iconFor(stage);
  return (
    <Animated.View style={[styles.icon, animatedStyle]}>
      <Text style={styles.iconText}>{emoji}</Text>
    </Animated.View>
  );
});
ToastIcon.displayName = 'ToastIcon';

const SaveButton: React.FC<{ onSave: () => void }> = React.memo(({ onSave }) => {
  const press = useSharedValue(1);
  const onPressIn = () => {
    press.value = withSpring(0.95, springConfigs.press);
  };
  const onPressOut = () => {
    press.value = withSpring(1, springConfigs.press);
  };
  const style = useAnimatedStyle(() => ({ transform: [{ scale: press.value }] }));
  return (
    <Animated.View style={[styles.saveButtonWrap, style]}>
      <Pressable
        onPress={onSave}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        accessibilityRole="button"
        style={styles.saveButton}
      >
        <LinearGradient
          colors={[...accentGradient]}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={StyleSheet.absoluteFill}
        />
        <Text style={styles.saveButtonText}>📥  Save to Device</Text>
      </Pressable>
    </Animated.View>
  );
});
SaveButton.displayName = 'SaveButton';

function iconFor(stage: Stage): string {
  switch (stage) {
    case 'fetching':
      return '🔍';
    case 'downloading':
      return '⬇️';
    case 'done':
    case 'savePrompt':
      return '✅';
    case 'saving':
      return '💾';
    case 'error':
      return '⚠️';
    default:
      return '⬇️';
  }
}

function labelFor(stage: Stage): { label: string; color?: string } {
  switch (stage) {
    case 'fetching':
      return { label: 'Detecting Video' };
    case 'downloading':
      return { label: 'Downloading' };
    case 'done':
    case 'savePrompt':
      return { label: 'Download Complete!', color: colors.success };
    case 'saving':
      return { label: 'Saving' };
    case 'error':
      return { label: 'Something went wrong', color: colors.error };
    default:
      return { label: '' };
  }
}

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 40,
    alignItems: 'center',
    paddingHorizontal: 16,
  },
  toast: {
    width: '100%',
    maxWidth: 360,
  },
  glass: {
    overflow: 'hidden',
    borderColor: colors.glassBorder,
  },
  content: {
    paddingVertical: 18,
    paddingHorizontal: 22,
    gap: 14,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  headerText: {
    flexShrink: 1,
    gap: 2,
  },
  icon: {
    width: 36,
    height: 36,
    borderRadius: 14,
    backgroundColor: 'rgba(255,255,255,0.08)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconText: {
    fontSize: 18,
  },
  body: {
    gap: 8,
  },
  metaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
  },
  saveButtonWrap: {
    width: '100%',
  },
  saveButton: {
    height: 50,
    borderRadius: 14,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButtonText: {
    color: '#ffffff',
    fontSize: 15,
    fontFamily: 'Manrope_700Bold',
  },
  errorClose: {
    alignSelf: 'flex-end',
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  errorCloseText: {
    fontSize: 12,
    fontFamily: 'Manrope_700Bold',
    color: 'rgba(245,245,247,0.65)',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
});
