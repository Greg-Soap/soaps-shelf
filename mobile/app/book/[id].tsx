import * as Linking from 'expo-linking';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import {
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Animated, { Easing, FadeIn } from 'react-native-reanimated';

import { ErrorText, Loading, Muted, PrimaryButton } from '@/components/ui';
import {
  deleteBook,
  epubDownloadUrl,
  getBook,
  listCategories,
  setBookCategories,
  updateBookStatus,
} from '@/lib/api';
import type { Book, Category } from '@/lib/types';
import { STATUS_LABELS, STATUS_OPTIONS } from '@/lib/types';
import { palette, spacing } from '@/constants/theme';

const easeOut = Easing.out(Easing.cubic);

export default function BookDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const bookId = Number(id);
  const [book, setBook] = useState<Book | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!Number.isFinite(bookId)) {
      setError('Invalid book id');
      setLoading(false);
      return;
    }
    setError('');
    try {
      const [nextBook, nextCategories] = await Promise.all([getBook(bookId), listCategories()]);
      setBook(nextBook);
      setCategories(nextCategories);
      setSelectedIds((nextBook.categories || []).map((category) => category.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load book');
    } finally {
      setLoading(false);
    }
  }, [bookId]);

  useEffect(() => {
    load();
  }, [load]);

  async function onStatus(status: string) {
    if (!book || saving) return;
    setSaving(true);
    setError('');
    try {
      setBook(await updateBookStatus(book.id, status));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update status');
    } finally {
      setSaving(false);
    }
  }

  async function onToggleCategory(categoryId: number) {
    if (!book || saving) return;
    const nextIds = selectedIds.includes(categoryId)
      ? selectedIds.filter((id) => id !== categoryId)
      : [...selectedIds, categoryId];
    const previous = selectedIds;
    setSelectedIds(nextIds);
    setSaving(true);
    setError('');
    try {
      const assigned = await setBookCategories(book.id, nextIds);
      setSelectedIds(assigned.map((category) => category.id));
      setBook({ ...book, categories: assigned });
    } catch (err) {
      setSelectedIds(previous);
      setError(err instanceof Error ? err.message : 'Could not update categories');
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!book) return;
    try {
      await deleteBook(book.id);
      router.back();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete');
    }
  }

  if (loading) {
    return (
      <View style={styles.wrap}>
        <Loading />
      </View>
    );
  }

  if (!book) {
    return (
      <View style={styles.wrap}>
        <ErrorText message={error || 'Book not found'} />
      </View>
    );
  }

  const download = epubDownloadUrl(book.epub_path);

  return (
    <ScrollView style={styles.wrap} contentContainerStyle={styles.content}>
      <Animated.View entering={FadeIn.duration(200).easing(easeOut)} style={styles.coverWrap}>
        {book.cover_url ? (
          <Image source={{ uri: book.cover_url }} style={styles.cover} />
        ) : (
          <View style={[styles.cover, styles.coverFallback]}>
            <Text style={styles.coverLetter}>{(book.title || book.raw_title).slice(0, 1)}</Text>
          </View>
        )}
      </Animated.View>

      <Animated.View entering={FadeIn.delay(40).duration(220).easing(easeOut)}>
        <Text style={styles.title}>{book.title || book.raw_title}</Text>
        <Text style={styles.authors}>{book.authors || 'Author unknown'}</Text>
      </Animated.View>

      {error ? <ErrorText message={error} /> : null}

      <Animated.View entering={FadeIn.delay(70).duration(220).easing(easeOut)}>
        <Text style={styles.label}>Status</Text>
        <View style={styles.chips}>
          {STATUS_OPTIONS.map((status) => {
            const active = book.status === status;
            return (
              <Pressable
                key={status}
                onPress={() => onStatus(status)}
                style={[styles.chip, active && styles.chipActive]}
              >
                <Text style={[styles.chipText, active && styles.chipTextActive]}>
                  {STATUS_LABELS[status]}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </Animated.View>

      <Animated.View entering={FadeIn.delay(100).duration(220).easing(easeOut)}>
        <Text style={styles.label}>Categories</Text>
        {categories.length === 0 ? (
          <Muted>Create categories in the Categories tab, then assign them here.</Muted>
        ) : (
          <View style={styles.chips}>
            {categories.map((category) => {
              const active = selectedIds.includes(category.id);
              return (
                <Pressable
                  key={category.id}
                  onPress={() => onToggleCategory(category.id)}
                  style={[
                    styles.chip,
                    active && styles.chipActive,
                    active && category.color
                      ? { backgroundColor: category.color, borderColor: category.color }
                      : null,
                  ]}
                >
                  <Text style={[styles.chipText, active && styles.chipTextActive]}>
                    {category.name}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        )}
      </Animated.View>

      {book.pipeline_status ? (
        <Text style={styles.meta}>Pipeline · {book.pipeline_status}</Text>
      ) : null}
      {book.source_url ? <Text style={styles.meta}>Source · {book.source_url}</Text> : null}
      {book.last_chapter_title ? (
        <Text style={styles.meta}>
          Last chapter · {book.last_chapter_title}
          {book.last_chapter_index != null ? ` (#${book.last_chapter_index + 1})` : ''}
        </Text>
      ) : null}

      {book.synopsis ? (
        <Animated.View entering={FadeIn.delay(130).duration(220).easing(easeOut)}>
          <Text style={styles.label}>Synopsis</Text>
          <Text style={styles.synopsis}>{book.synopsis}</Text>
        </Animated.View>
      ) : null}

      {download ? (
        <PrimaryButton label="Open EPUB" onPress={() => Linking.openURL(download)} />
      ) : null}

      <Pressable onPress={onDelete} style={styles.deleteBtn}>
        <Text style={styles.deleteText}>Delete book</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: palette.bg,
  },
  content: {
    padding: spacing.md,
    paddingBottom: 40,
    gap: spacing.sm,
  },
  coverWrap: {
    alignSelf: 'center',
    marginBottom: spacing.sm,
  },
  cover: {
    width: 140,
    height: 210,
    borderRadius: 6,
    backgroundColor: palette.bgElevated,
  },
  coverFallback: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  coverLetter: {
    color: palette.accent,
    fontSize: 48,
    fontWeight: '700',
  },
  title: {
    color: palette.ink,
    fontSize: 26,
    fontWeight: '700',
    textAlign: 'center',
  },
  authors: {
    color: palette.muted,
    textAlign: 'center',
    marginBottom: spacing.sm,
  },
  label: {
    color: palette.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontSize: 12,
    marginTop: spacing.sm,
    marginBottom: 8,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  chipActive: {
    backgroundColor: palette.accent,
    borderColor: palette.accent,
  },
  chipText: {
    color: palette.muted,
    fontSize: 13,
    fontWeight: '600',
  },
  chipTextActive: {
    color: '#1a1208',
  },
  meta: {
    color: palette.muted,
    fontSize: 13,
  },
  synopsis: {
    color: palette.ink,
    lineHeight: 22,
  },
  deleteBtn: {
    marginTop: spacing.lg,
    alignItems: 'center',
    padding: 12,
  },
  deleteText: {
    color: palette.danger,
    fontWeight: '600',
  },
});
