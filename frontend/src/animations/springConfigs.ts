import { Easing, type WithSpringConfig, type WithTimingConfig } from 'react-native-reanimated';

/**
 * Spring presets that approximate the cubic-bezier(0.34,1.56,0.64,1) "Apple
 * spring" feel from the design spec. We hand-tune mass / damping to keep the
 * overshoot subtle.
 */
export const springConfigs = {
  toast: { mass: 0.9, damping: 16, stiffness: 220 } satisfies WithSpringConfig,
  card: { mass: 0.8, damping: 14, stiffness: 180 } satisfies WithSpringConfig,
  bouncy: { mass: 1, damping: 12, stiffness: 200 } satisfies WithSpringConfig,
  press: { mass: 0.4, damping: 12, stiffness: 250 } satisfies WithSpringConfig,
};

export const timingConfigs = {
  fadeIn: { duration: 350, easing: Easing.out(Easing.quad) } satisfies WithTimingConfig,
  smooth: { duration: 600, easing: Easing.bezier(0.34, 1.2, 0.64, 1) } satisfies WithTimingConfig,
  shimmer: { duration: 1500, easing: Easing.linear } satisfies WithTimingConfig,
  toastOut: { duration: 350, easing: Easing.in(Easing.quad) } satisfies WithTimingConfig,
};

export const ANIMATION_DELAYS = {
  cardStagger: [100, 200, 300],
} as const;
