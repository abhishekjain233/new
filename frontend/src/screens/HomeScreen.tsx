import React, { useCallback, useMemo } from 'react';
import { Dimensions, ScrollView, StyleSheet, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { SafeAreaView } from 'react-native-safe-area-context';

import { CategoryCard } from '@/components/CategoryCard';
import { DownloadItem } from '@/components/DownloadItem';
import { DownloadToast } from '@/components/DownloadToast';
import { GlassSurface } from '@/components/GlassSurface';
import Text from '@/components/Text';
import { ANIMATION_DELAYS } from '@/animations/springConfigs';
import { colors } from '@/constants/colors';
import { PLATFORMS, type Platform } from '@/constants/platforms';
import { typography } from '@/constants/typography';
import { useDownload } from '@/hooks/useDownload';

const { width: WINDOW_WIDTH } = Dimensions.get('window');
const CARD_WIDTH = Math.min(420, WINDOW_WIDTH * 0.94);

export const HomeScreen: React.FC = () => {
  const { toast, recent, start, save, dismiss } = useDownload();

  const handleSubmit = useCallback(
    (url: string, platform: Platform) => {
      void start(url, platform);
    },
    [start],
  );

  const cards = useMemo(
    () =>
      PLATFORMS.map((p, idx) => (
        <CategoryCard
          key={p.id}
          descriptor={p}
          delayMs={ANIMATION_DELAYS.cardStagger[idx] ?? 100}
          onSubmit={handleSubmit}
        />
      )),
    [handleSubmit],
  );

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
      <View style={styles.bg}>
        <LinearGradient
          pointerEvents="none"
          colors={['rgba(124,92,252,0.22)', 'rgba(8,8,16,0)']}
          start={{ x: 0.5, y: 0 }}
          end={{ x: 0.5, y: 1 }}
          style={styles.radial}
        />
      </View>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <GlassSurface radius={24} style={styles.logo} intensity={28}>
            <View style={styles.logoInner}>
              <Text style={styles.logoEmoji}>⬇️</Text>
            </View>
          </GlassSurface>
          <Text style={[typography.appName, styles.appName]}>Fetch.</Text>
          <Text style={[typography.tagline, styles.tagline]}>Download Anything. Keep Everything.</Text>
        </View>

        <View style={[styles.cards, { width: CARD_WIDTH }]}>{cards}</View>

        {recent.length > 0 ? (
          <View style={[styles.recent, { width: CARD_WIDTH }]}>
            <Text style={[typography.sectionLabel, styles.recentLabel]}>Recent Downloads</Text>
            <View style={styles.recentList}>
              {recent.map((item, idx) => (
                <DownloadItem key={item.id} item={item} index={idx} />
              ))}
            </View>
          </View>
        ) : null}
      </ScrollView>
      <DownloadToast state={toast} onSave={save} onDismiss={dismiss} />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.background,
  },
  bg: {
    ...StyleSheet.absoluteFillObject,
  },
  radial: {
    position: 'absolute',
    top: -100,
    left: 0,
    right: 0,
    height: 480,
  },
  scrollContent: {
    paddingTop: 64,
    paddingBottom: 160,
    alignItems: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: 32,
    paddingHorizontal: 24,
  },
  logo: {
    width: 80,
    height: 80,
  },
  logoInner: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoEmoji: {
    fontSize: 38,
  },
  appName: {
    marginTop: 18,
  },
  tagline: {
    marginTop: 6,
  },
  cards: {
    gap: 14,
    alignSelf: 'center',
  },
  recent: {
    marginTop: 32,
    gap: 12,
    alignSelf: 'center',
  },
  recentLabel: {
    paddingLeft: 4,
  },
  recentList: {
    gap: 10,
  },
});
