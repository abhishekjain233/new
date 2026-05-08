import React from 'react';
import { StyleSheet, View } from 'react-native';

import { PermissionModal } from '@/components/PermissionModal';
import { colors } from '@/constants/colors';

interface Props {
  onAllow: () => void;
  onDeny: () => void;
}

export const PermissionScreen: React.FC<Props> = ({ onAllow, onDeny }) => {
  return (
    <View style={styles.root}>
      <PermissionModal visible onAllow={onAllow} onDeny={onDeny} />
    </View>
  );
};

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
});
