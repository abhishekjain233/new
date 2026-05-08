import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import {
  Manrope_500Medium,
  Manrope_600SemiBold,
  Manrope_700Bold,
  Manrope_800ExtraBold,
  useFonts,
} from '@expo-google-fonts/manrope';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { HomeScreen } from '@/screens/HomeScreen';
import { PermissionScreen } from '@/screens/PermissionScreen';
import { colors } from '@/constants/colors';
import { usePermission } from '@/hooks/usePermission';

export default function App() {
  const [fontsLoaded] = useFonts({
    Manrope_500Medium,
    Manrope_600SemiBold,
    Manrope_700Bold,
    Manrope_800ExtraBold,
  });
  const { ready, state, request, deny } = usePermission();
  const [forceShown, setForceShown] = useState(false);

  useEffect(() => {
    if (ready && state === null) {
      setForceShown(true);
    }
  }, [ready, state]);

  const handleAllow = useCallback(async () => {
    await request();
    setForceShown(false);
  }, [request]);

  const handleDeny = useCallback(async () => {
    await deny();
    setForceShown(false);
  }, [deny]);

  const showPermission = useMemo(() => forceShown && ready, [forceShown, ready]);
  const isLoading = !fontsLoaded || !ready;

  return (
    <GestureHandlerRootView style={styles.root}>
      <SafeAreaProvider>
        <StatusBar style="light" backgroundColor={colors.background} />
        {isLoading ? (
          <View style={styles.loading}>
            <ActivityIndicator size="large" color={colors.accentStart} />
          </View>
        ) : (
          <>
            <HomeScreen />
            {showPermission ? (
              <PermissionScreen onAllow={handleAllow} onDeny={handleDeny} />
            ) : null}
          </>
        )}
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },
});
