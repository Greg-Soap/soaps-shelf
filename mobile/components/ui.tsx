import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewProps,
} from 'react-native';

import { palette, spacing } from '@/constants/theme';

export function Screen({ children, style, ...rest }: ViewProps) {
  return (
    <View style={[styles.screen, style]} {...rest}>
      {children}
    </View>
  );
}

export function Title({ children }: { children: string }) {
  return <Text style={styles.title}>{children}</Text>;
}

export function Muted({ children }: { children: string }) {
  return <Text style={styles.muted}>{children}</Text>;
}

export function Field(props: TextInputProps) {
  return (
    <TextInput
      placeholderTextColor={palette.muted}
      {...props}
      style={[styles.input, props.style]}
    />
  );
}

export function PrimaryButton({
  label,
  onPress,
  disabled,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        styles.button,
        disabled && styles.buttonDisabled,
        pressed && !disabled && { opacity: 0.85 },
      ]}
    >
      <Text style={styles.buttonLabel}>{label}</Text>
    </Pressable>
  );
}

export function Loading() {
  return (
    <View style={[styles.loading, { backgroundColor: palette.bg }]}>
      <ActivityIndicator color={palette.accent} />
    </View>
  );
}

export function ErrorText({ message }: { message: string }) {
  return <Text style={styles.error}>{message}</Text>;
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: palette.bg,
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
  },
  title: {
    color: palette.ink,
    fontSize: 32,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  muted: {
    color: palette.muted,
    fontSize: 15,
    lineHeight: 21,
    marginBottom: spacing.md,
  },
  input: {
    backgroundColor: palette.bgElevated,
    borderColor: palette.border,
    borderWidth: 1,
    borderRadius: 14,
    color: palette.ink,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontSize: 16,
    marginBottom: spacing.sm,
  },
  button: {
    backgroundColor: palette.accent,
    borderRadius: 999,
    paddingVertical: 13,
    paddingHorizontal: 18,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.55,
  },
  buttonLabel: {
    color: '#1a1208',
    fontWeight: '700',
    fontSize: 16,
  },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  error: {
    color: palette.danger,
    marginBottom: spacing.sm,
  },
});
