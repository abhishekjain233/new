import React, { useEffect } from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { BlurView } from 'expo-blur';
import { LinearGradient } from 'expo-linear-gradient';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { springConfigs } from '@/animations/springConfigs';
import Text from '@/components/Text';
import { accentGradient, colors, radii } from '@/constants/colors';
import { typography } from '@/constants/typography';

interface Props {
  visible: boolean;
  onAllow: () => void;
  onDeny: () => void;
}

export const PermissionModal: React.FC<Props> = React.memo(({ visible, onAllow, onDeny }) => {
  const opacity = useSharedValue(0);
  const translate = useSharedValue(80);

  useEffect(() => {
    if (visible) {
      opacity.value = withTiming(1, { duration: 350, easing: Easing.out(Easing.cubic) });
      translate.value = withSpring(0, springConfigs.bouncy);
    } else {
      opacity.value = 0;
      translate.value = 80;
    }
  }, [opacity, translate, visible]);

  const overlayStyle = useAnimatedStyle(() => ({ opacity: opacity.value }));
  const cardStyle = useAnimatedStyle(() => ({
    opacity: opacity.value,
    transform: [{ translateY: translate.value }],
  }));

  return (
    <Modal visible={visible} transparent statusBarTranslucent animationType="none">
      <View style={styles.root}>
        <Animated.View style={[StyleSheet.absoluteFill, overlayStyle]}>
          <BlurView intensity={30} tint="dark" style={StyleSheet.absoluteFill} />
          <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.overlay }]} />
        </Animated.View>
        <Animated.View style={[styles.card, cardStyle]}>
          <View style={styles.iconWrap}>
            <LinearGradient
              colors={[...accentGradient]}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={StyleSheet.absoluteFill}
            />
            <Text style={styles.iconEmoji}>📁</Text>
          </View>
          <Text style={[typography.modalTitle, styles.title]}>“Fetch” Wants to Access Your Media</Text>
          <Text style={[typography.body, styles.body]}>
            Fetch needs access to your media library and storage so it can save downloaded videos to
            your device. You can change this anytime in Settings.
          </Text>
          <Pressable
            accessibilityRole="button"
            onPress={onAllow}
            style={styles.allowButton}
          >
            <LinearGradient
              colors={[...accentGradient]}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 1 }}
              style={StyleSheet.absoluteFill}
            />
            <Text style={styles.allowButtonText}>Allow Access</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            onPress={onDeny}
            style={styles.denyButton}
          >
            <Text style={styles.denyButtonText}>Not Now</Text>
          </Pressable>
        </Animated.View>
      </View>
    </Modal>
  );
});

PermissionModal.displayName = 'PermissionModal';

const styles = StyleSheet.create({
  root: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  card: {
    width: 340,
    maxWidth: '100%',
    borderRadius: radii.modal,
    backgroundColor: colors.glassDeepBg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.glassDeepBorder,
    paddingTop: 36,
    paddingBottom: 28,
    paddingHorizontal: 28,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.6,
    shadowRadius: 80,
    shadowOffset: { width: 0, height: 40 },
    elevation: 40,
  },
  iconWrap: {
    width: 72,
    height: 72,
    borderRadius: 22,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.accentStart,
    shadowOpacity: 0.4,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 12 },
    elevation: 16,
  },
  iconEmoji: {
    fontSize: 32,
  },
  title: {
    marginTop: 18,
    textAlign: 'center',
  },
  body: {
    marginTop: 10,
    textAlign: 'center',
  },
  allowButton: {
    width: '100%',
    height: 52,
    borderRadius: radii.button,
    marginTop: 22,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  allowButtonText: {
    fontFamily: 'Manrope_700Bold',
    color: '#ffffff',
    fontSize: 15,
  },
  denyButton: {
    width: '100%',
    height: 50,
    borderRadius: radii.button,
    marginTop: 10,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.glassBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  denyButtonText: {
    fontFamily: 'Manrope_600SemiBold',
    fontSize: 15,
    color: 'rgba(245,245,247,0.50)',
  },
});
