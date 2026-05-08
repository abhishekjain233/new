# Fetch. — Mobile App

Expo + React Native + TypeScript app implementing the full Fetch. design spec.

## Run

```bash
npm install
npx expo start
```

Point the app at your backend by editing `app.json` → `expo.extra.apiBaseUrl`. On a phone, use your dev machine's LAN IP rather than `localhost`.

## Stack

* React 18 + React Native 0.74 (Expo SDK 51)
* `react-native-reanimated` v3 — toast spring, shimmer, successPop, pulse, card stagger
* `expo-blur`, `expo-linear-gradient` — Apple Liquid Glass surfaces
* `expo-media-library` — Save to gallery
* `expo-file-system` — Stream the backend file to disk before the system save
* `@react-native-async-storage/async-storage` — Permission flag + recent downloads
* `@expo-google-fonts/manrope` — Typography

## Notable files

| File | Role |
| --- | --- |
| `App.tsx` | Permission gate, font loader, root provider stack |
| `src/screens/HomeScreen.tsx` | Header / 3 cards / recent list / toast mount point |
| `src/screens/PermissionScreen.tsx` | First-launch overlay wrapper |
| `src/hooks/useDownload.ts` | State machine: fetching → downloading → done → saving + polling cleanup |
| `src/hooks/usePermission.ts` | AsyncStorage + `expo-media-library` permission glue |
| `src/components/DownloadToast.tsx` | All 4 toast stages + gradient save button |
| `src/components/CategoryCard.tsx` | Platform card + paste hint + buttonPress spring |
| `src/components/GlassSurface.tsx` | Liquid-glass primitive (BlurView on iOS, fallback on Android) |
| `src/components/PlatformIcon.tsx` | SVG platform glyphs |
| `src/animations/springConfigs.ts` | Reanimated spring presets ≈ cubic-bezier(0.34,1.56,0.64,1) |

## Performance

* Every component that takes children is `React.memo`-wrapped.
* Polling intervals and timeouts are cleaned up in `useEffect` returns and on `dismiss()`.
* The progress bar's shimmer runs entirely on the UI thread via `useSharedValue` + `useAnimatedStyle`.
* The toast and modal mount only when `visible` so animation graphs aren't kept alive.
