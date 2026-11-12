import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  FadeIn,
  FadeOut,
  SlideInDown,
  SlideOutDown,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { palette, spacing } from '@/constants/theme';

const easeOut = Easing.out(Easing.cubic);

export function Sheet({
  visible,
  title,
  onClose,
  children,
}: {
  visible: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const insets = useSafeAreaInsets();

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose}>
      <View style={styles.root}>
        <Animated.View
          entering={FadeIn.duration(160).easing(easeOut)}
          exiting={FadeOut.duration(120).easing(easeOut)}
          style={StyleSheet.absoluteFill}
        >
          <Pressable style={styles.backdrop} onPress={onClose} />
        </Animated.View>
        <Animated.View
          entering={SlideInDown.duration(260).easing(easeOut)}
          exiting={SlideOutDown.duration(180).easing(easeOut)}
          style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) + 8 }]}
        >
          <View style={styles.handle} />
          <Text style={styles.title}>{title}</Text>
          {children}
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(8, 5, 3, 0.62)',
  },
  sheet: {
    backgroundColor: palette.bgElevated,
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderColor: palette.border,
    maxHeight: '78%',
  },
  handle: {
    alignSelf: 'center',
    width: 42,
    height: 4,
    borderRadius: 999,
    backgroundColor: 'rgba(243,235,224,0.25)',
    marginBottom: spacing.sm,
  },
  title: {
    color: palette.ink,
    fontSize: 20,
    fontWeight: '700',
    marginBottom: spacing.md,
  },
});
