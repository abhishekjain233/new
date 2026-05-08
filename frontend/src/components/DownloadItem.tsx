import React, { useEffect, useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';

import { GlassSurface } from '@/components/GlassSurface';
import Text from '@/components/Text';
import { colors, radii } from '@/constants/colors';
import { typography } from '@/constants/typography';
import type { Platform } from '@/constants/platforms';
import type { RecentDownload } from '@/services/storage.service';

interface Props {
  item: RecentDownload;
  index: number;
}

const PLATFORM_EMOJI: Record<Platform, string> = {
  youtube: '📺',
  instagram: '📸',
  snapchat: '👻',
};

const PLATFORM_LABEL: Record<Platform, string> = {
  youtube: 'YouTube',
  instagram: 'Instagram',
  snapchat: 'Snapchat',
};

export const DownloadItem: React.FC<Props> = React.memo(({ item, index }) => {
  const enter = useSharedValue(0);
  useEffect(() => {
    enter.value = withDelay(
      index * 60,
      withTiming(1, { duration: 400, easing: Easing.bezier(0.34, 1.2, 0.64, 1) }),
    );
  }, [enter, index]);

  const style = useAnimatedStyle(() => ({
    opacity: enter.value,
    transform: [{ translateY: (1 - enter.value) * 24 }],
  }));

  const subtitle = useMemo(() => {
    return `${PLATFORM_LABEL[item.platform]} · ${formatRelativeTime(item.savedAt)}`;
  }, [item.platform, item.savedAt]);

  return (
    <Animated.View style={[styles.outer, style]}>
      <GlassSurface radius={16} style={styles.card}>
        <View style={styles.row}>
          <View style={styles.thumb}>
            <Text style={styles.thumbEmoji}>{PLATFORM_EMOJI[item.platform]}</Text>
          </View>
          <View style={styles.text}>
            <Text style={styles.title} numberOfLines={1}>
              {item.title}
            </Text>
            <Text style={[typography.meta, styles.subtitle]}>{subtitle}</Text>
          </View>
          <Text style={styles.check}>✅</Text>
        </View>
      </GlassSurface>
    </Animated.View>
  );
});

DownloadItem.displayName = 'DownloadItem';

function formatRelativeTime(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000) return 'just now';
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

const styles = StyleSheet.create({
  outer: {
    width: '100%',
  },
  card: {
    paddingVertical: 14,
    paddingHorizontal: 16,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  thumb: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.08)',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.glassBorder,
  },
  thumbEmoji: {
    fontSize: 22,
  },
  text: {
    flex: 1,
    gap: 2,
  },
  title: {
    fontSize: 13,
    fontFamily: 'Manrope_600SemiBold',
    color: colors.primaryText,
  },
  subtitle: {
    fontSize: 11,
  },
  check: {
    fontSize: 16,
  },
});

export const DOWNLOAD_ITEM_RADIUS = radii.card;
