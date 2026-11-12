import { SymbolView } from 'expo-symbols';
import { useCallback, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect } from 'expo-router';
import Animated, { Easing, FadeIn, FadeInDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Sheet } from '@/components/Sheet';
import { ErrorText, Field, Loading, Muted, PrimaryButton, Screen } from '@/components/ui';
import { createCategory, deleteCategory, listCategories } from '@/lib/api';
import type { Category } from '@/lib/types';
import { palette, spacing } from '@/constants/theme';

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);
const easeOut = Easing.out(Easing.cubic);

export default function CategoriesScreen() {
  const insets = useSafeAreaInsets();
  const [categories, setCategories] = useState<Category[]>([]);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [addOpen, setAddOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      setCategories(await listCategories());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load categories');
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      load();
    }, [load]),
  );

  async function onCreate() {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      await createCategory({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      setName('');
      setDescription('');
      setAddOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create category');
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id: number) {
    setError('');
    try {
      await deleteCategory(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete');
    }
  }

  if (loading) return <Loading />;

  return (
    <Screen style={[styles.screen, { paddingTop: Math.max(insets.top, 12) }]}>
      <Text style={styles.brand}>Categories</Text>
      <Muted>Tap a book on the shelf to assign these tags.</Muted>
      {error ? <ErrorText message={error} /> : null}

      <FlatList
        style={styles.list}
        contentContainerStyle={{ paddingBottom: 100 }}
        data={categories}
        keyExtractor={(item) => String(item.id)}
        ListEmptyComponent={<Muted>No categories yet — create one with +.</Muted>}
        renderItem={({ item, index }) => (
          <Animated.View
            entering={FadeInDown.delay(Math.min(index, 10) * 24).duration(220).easing(easeOut)}
            style={styles.row}
          >
            <View
              style={[
                styles.swatch,
                { backgroundColor: item.color || palette.accent },
              ]}
            />
            <View style={{ flex: 1 }}>
              <Text style={styles.name}>{item.name}</Text>
              <Text style={styles.meta}>
                {item.book_count ?? 0} books
                {item.description ? ` · ${item.description}` : ''}
              </Text>
            </View>
            <Pressable onPress={() => onDelete(item.id)} hitSlop={10}>
              <Text style={styles.delete}>Delete</Text>
            </Pressable>
          </Animated.View>
        )}
      />

      <AnimatedPressable
        entering={FadeIn.duration(220).easing(easeOut)}
        onPress={() => setAddOpen(true)}
        style={[styles.fab, { bottom: Math.max(insets.bottom, 12) + 12 }]}
      >
        <SymbolView
          name={{ ios: 'plus', android: 'add', web: 'add' }}
          tintColor="#1a1208"
          size={28}
        />
      </AnimatedPressable>

      <Sheet visible={addOpen} title="New category" onClose={() => setAddOpen(false)}>
        <Field autoFocus placeholder="Name" value={name} onChangeText={setName} />
        <Field
          placeholder="Description (optional)"
          value={description}
          onChangeText={setDescription}
        />
        <PrimaryButton
          label={busy ? 'Saving…' : 'Create category'}
          onPress={onCreate}
          disabled={busy}
        />
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    paddingBottom: 0,
  },
  brand: {
    color: palette.ink,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: -0.4,
    marginBottom: 4,
  },
  list: {
    flex: 1,
  },
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: palette.border,
  },
  swatch: {
    width: 10,
    height: 36,
    borderRadius: 999,
  },
  name: {
    color: palette.ink,
    fontSize: 16,
    fontWeight: '600',
  },
  meta: {
    color: palette.muted,
    fontSize: 12,
    marginTop: 2,
  },
  delete: {
    color: palette.danger,
    fontWeight: '600',
  },
  fab: {
    position: 'absolute',
    right: spacing.md,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: palette.accent,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOpacity: 0.35,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 8 },
    elevation: 6,
  },
});
