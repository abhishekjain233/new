import React from 'react';
import { Text as RNText, type TextProps } from 'react-native';

import { fontFamily } from '@/constants/typography';

const defaultStyle = {
  fontFamily: fontFamily.medium,
  color: '#f5f5f7',
};

const Text: React.FC<TextProps> = ({ style, ...rest }) => {
  return <RNText {...rest} style={[defaultStyle, style]} />;
};

export default Text;
