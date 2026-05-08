import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { springConfigs } from '@/animations/springConfigs';
import { GlassSurface } from '@/components/GlassSurface';
import { PlatformIcon } from '@/components/PlatformIcon';
import { colors, instagramGradient, radii, youtubeGradient } from '@/constants/colors';
import {
  detectPlatform,
  type Platform,
  type PlatformDescriptor,
} from '@/constants/platforms';
import { typography } from '@/constants/typography';
import Text from '@/components/Text';

interface Props {
  descriptor: PlatformDescriptor;
  delayMs: number;
  onSubmit: (url: string, platform: Platform) => void;
}

const PRESS_SCALE = 0.9;

export const CategoryCard: React.FC<Props> = React.memo(({ descriptor, delayMs, onSubmit }) => {
  const enter = useSharedValue(0);
  const press = useSharedValue(1);
  const [value, setValue] = useState('');
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    enter.value = withDelay(
      delayMs,
      withTiming(1, { duration: 600, easing: Easing.bezier(0.34, 1.2, 0.64, 1) }),
    );
  }, [delayMs, enter]);

  const enterStyle = useAnimatedStyle(() => ({
    opacity: enter.value,
    transform: [{ translateY: (1 - enter.value) * 30 }],
  }));

  const buttonStyle = useAnimatedStyle(() => ({
    transform: [{ scale: press.value }],
  }));

  const handleFocusInput = useCallback(() => {
    inputRef.current?.focus();
  }, []);

  const handlePaste = useCallback(async () => {
    try {
      const text = await Clipboard.getStringAsync();
      if (text) setValue(text.trim());
    } catch {
      // ignore — best effort
    }
  }, []);

  const submit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed) return;
    const detected = detectPlatform(trimmed);
    const platform = detected ?? descriptor.id;
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
    onSubmit(trimmed, platform);
    setValue('');
  }, [descriptor.id, onSubmit, value]);

  const onPressIn = useCallback(() => {
    press.value = withSpring(PRESS_SCALE, springConfigs.press);
  }, [press]);

  const onPressOut = useCallback(() => {
    press.value = withSpring(1, springConfigs.press);
  }, [press]);

  const buttonGradient = useMemo<readonly [string, string, ...string[]] | null>(() => {
    if (descriptor.id === 'youtube') return [youtubeGradient[0], youtubeGradient[1]];
    if (descriptor.id === 'instagram')
      return [instagramGradient[0], instagramGradient[1], instagramGradient[2]];
    return null;
  }, [descriptor.id]);

  const buttonColor = descriptor.id === 'snapchat' ? colors.snapchat : undefined;
  const buttonIconColor = descriptor.id === 'snapchat' ? colors.snapchatDark : '#ffffff';
  const inputProps: TextInputProps = {
    placeholder: descriptor.inputPlaceholder,
    placeholderTextColor: 'rgba(245,245,247,0.30)',
    autoCapitalize: 'none',
    autoCorrect: false,
    returnKeyType: 'go',
    keyboardAppearance: 'dark',
    keyboardType: 'url',
    spellCheck: false,
    selectionColor: colors.accentStart,
    onSubmitEditing: submit,
  };

  const containerStyle: ViewStyle = useMemo(
    () => ({ ...styles.cardOuter }),
    [],
  );

  return (
    <Animated.View style={[containerStyle, enterStyle]}>
      <GlassSurface style={styles.card} radius={radii.card}>
        <View style={styles.header}>
          <PlatformIcon platform={descriptor.id} size={48} />
          <View style={styles.headerText}>
            <Text style={typography.cardTitle}>{descriptor.label}</Text>
            <Text style={typography.cardSubtitle}>{descriptor.subtitle}</Text>
          </View>
        </View>
        <View style={styles.row}>
          <Pressable style={styles.inputWrap} onPress={handleFocusInput}>
            <TextInput
              ref={inputRef}
              style={styles.input}
              value={value}
              onChangeText={setValue}
              {...inputProps}
            />
            {value.length === 0 && (
              <Pressable hitSlop={8} onPress={handlePaste} style={styles.pasteHint}>
                <Text style={styles.pasteHintText}>Paste</Text>
              </Pressable>
            )}
          </Pressable>
          <Animated.View style={buttonStyle}>
            <Pressable
              accessibilityRole="button"
              onPress={submit}
              onPressIn={onPressIn}
              onPressOut={onPressOut}
              disabled={value.trim().length === 0}
              style={[
                styles.button,
                value.trim().length === 0 ? styles.buttonDisabled : null,
                buttonColor ? { backgroundColor: buttonColor } : null,
              ]}
            >
              {buttonGradient ? (
                <LinearGradient
                  colors={buttonGradient}
                  start={{ x: 0, y: 0 }}
                  end={{ x: 1, y: 1 }}
                  style={styles.buttonGradient}
                />
              ) : null}
              <Text style={[styles.buttonIcon, { color: buttonIconColor }]}>↓</Text>
            </Pressable>
          </Animated.View>
        </View>
      </GlassSurface>
    </Animated.View>
  );
});

CategoryCard.displayName = 'CategoryCard';

const styles = StyleSheet.create({
  cardOuter: {
    width: '100%',
  },
  card: {
    padding: 20,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 16,
    gap: 12,
  },
  headerText: {
    flexShrink: 1,
    gap: 2,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  inputWrap: {
    flex: 1,
    height: 46,
    borderRadius: radii.input,
    backgroundColor: colors.inputBg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.inputBorder,
    paddingHorizontal: 14,
    justifyContent: 'center',
  },
  input: {
    color: colors.primaryText,
    fontSize: 14,
    fontFamily: 'Manrope_500Medium',
  },
  pasteHint: {
    position: 'absolute',
    right: 10,
    top: 11,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: radii.pill,
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  pasteHintText: {
    color: 'rgba(245,245,247,0.65)',
    fontSize: 11,
    fontFamily: 'Manrope_700Bold',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
  button: {
    width: 46,
    height: 46,
    borderRadius: radii.input,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonDisabled: {
    opacity: 0.45,
  },
  buttonGradient: {
    ...StyleSheet.absoluteFillObject,
  },
  buttonIcon: {
    fontSize: 22,
    fontWeight: '900',
  },
});
