import { SymbolView } from 'expo-symbols';
import { useFocusEffect, useRouter } from 'expo-router';
import { useCallback, useMemo, useRef, useState } from 'react';
import {
  Dimensions,
  FlatList,
  Image,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Animated, { Easing, FadeIn, FadeInDown, LinearTransition } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Sheet } from '@/components/Sheet';
import { ErrorText, Field, Loading, Muted, PrimaryButton, Screen } from '@/components/ui';
import { addBook, listBooks } from '@/lib/api';
import type { Book } from '@/lib/types';
import { STATUS_LABELS, STATUS_OPTIONS } from '@/lib/types';
import { palette, spacing } from '@/constants/theme';

type ViewMode = 'list' | 'grid';
type SortMode = 'status' | 'title_asc' | 'title_desc';

const STATUS_RANK: Record<string, number> = {
  reading: 0,
  want_to_read: 1,
  not_finished: 2,
  read: 3,
  dropped: 4,
  other: 5,
};

const AnimatedPressable = Animated.createAnimatedComponent(Pressable);
const easeOut = Easing.out(Easing.cubic);
const enterList = (index: number) =>
  FadeInDown.delay(Math.min(index, 10) * 24)
    .duration(220)
    .easing(easeOut);
const layoutEase = LinearTransition.duration(180).easing(easeOut);

export default function ShelfScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [books, setBooks] = useState<Book[]>([]);
  const [query, setQuery] = useState('');
  const [draftTitle, setDraftTitle] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [sortMode, setSortMode] = useState<SortMode>('status');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [controlsOpen, setControlsOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');

  const hasLoadedRef = useRef(false);

  const load = useCallback(async (mode: 'initial' | 'silent' | 'pull' = 'silent') => {
    if (mode === 'initial') setLoading(true);
    if (mode === 'pull') setRefreshing(true);
    setError('');
    try {
      setBooks(await listBooks());
      hasLoadedRef.current = true;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load shelf');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      // Keep the list mounted on return so scroll position is preserved.
      load(hasLoadedRef.current ? 'silent' : 'initial');
    }, [load]),
  );

  const visibleBooks = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let rows = [...books];
    if (statusFilter !== 'all') {
      rows = rows.filter((book) => book.status === statusFilter);
    }
    if (needle) {
      rows = rows.filter((book) => {
        const hay = `${book.title || ''} ${book.raw_title || ''} ${book.authors || ''}`.toLowerCase();
        return hay.includes(needle);
      });
    }
    rows.sort((a, b) => {
      const titleA = (a.title || a.raw_title || '').toLowerCase();
      const titleB = (b.title || b.raw_title || '').toLowerCase();
      if (sortMode === 'title_asc') return titleA.localeCompare(titleB);
      if (sortMode === 'title_desc') return titleB.localeCompare(titleA);
      const rank = (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9);
      if (rank !== 0) return rank;
      return titleA.localeCompare(titleB);
    });
    return rows;
  }, [books, query, sortMode, statusFilter]);

  async function onAdd() {
    const title = draftTitle.trim();
    if (!title || adding) return;
    setAdding(true);
    setError('');
    try {
      await addBook(title, 'want_to_read');
      setDraftTitle('');
      setAddOpen(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add book');
    } finally {
      setAdding(false);
    }
  }

  function renderBook(item: Book, index: number) {
    const title = item.title || item.raw_title;
    if (viewMode === 'grid') {
      return (
        <AnimatedPressable
          entering={enterList(index)}
          layout={layoutEase}
          style={styles.gridCard}
          onPress={() => router.push(`/book/${item.id}`)}
        >
          {item.cover_url ? (
            <Image source={{ uri: item.cover_url }} style={styles.gridCover} />
          ) : (
            <View style={[styles.gridCover, styles.coverFallback]}>
              <Text style={styles.coverLetter}>{title.slice(0, 1)}</Text>
            </View>
          )}
          <Text style={styles.gridTitle} numberOfLines={2}>
            {title}
          </Text>
          <Text style={styles.gridStatus}>{STATUS_LABELS[item.status] || item.status}</Text>
        </AnimatedPressable>
      );
    }

    return (
      <AnimatedPressable
        entering={enterList(index)}
        layout={layoutEase}
        style={styles.row}
        onPress={() => router.push(`/book/${item.id}`)}
      >
        {item.cover_url ? (
          <Image source={{ uri: item.cover_url }} style={styles.cover} />
        ) : (
          <View style={[styles.cover, styles.coverFallback]}>
            <Text style={styles.coverLetter}>{title.slice(0, 1)}</Text>
          </View>
        )}
        <View style={styles.meta}>
          <Text style={styles.bookTitle} numberOfLines={2}>
            {title}
          </Text>
          <Text style={styles.bookAuthors} numberOfLines={1}>
            {item.authors || 'Author unknown'}
          </Text>
          <Text style={styles.bookStatus}>
            {STATUS_LABELS[item.status] || item.status}
            {item.pipeline_status === 'ready' ? ' · EPUB ready' : ''}
          </Text>
        </View>
      </AnimatedPressable>
    );
  }

  if (loading) return <Loading />;

  const filterSummary =
    statusFilter === 'all'
      ? sortMode === 'status'
        ? 'All · shelf order'
        : sortMode === 'title_asc'
          ? 'All · A–Z'
          : 'All · Z–A'
      : `${STATUS_LABELS[statusFilter] || statusFilter}`;

  return (
    <Screen style={[styles.screen, { paddingTop: Math.max(insets.top, 12) }]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.brand}>Soap's Shelf</Text>
          <Pressable onPress={() => setControlsOpen(true)} hitSlop={8}>
            <Text style={styles.summary}>{filterSummary} · {visibleBooks.length}</Text>
          </Pressable>
        </View>
        <View style={styles.headerActions}>
          <IconButton
            name={{ ios: 'magnifyingglass', android: 'search', web: 'search' }}
            active={searchOpen || !!query}
            onPress={() => setSearchOpen((value) => !value)}
          />
          <IconButton
            name={{
              ios: viewMode === 'grid' ? 'list.bullet' : 'square.grid.2x2',
              android: viewMode === 'grid' ? 'view_list' : 'grid_view',
              web: viewMode === 'grid' ? 'view_list' : 'grid_view',
            }}
            onPress={() => setViewMode((mode) => (mode === 'list' ? 'grid' : 'list'))}
          />
          <IconButton
            name={{ ios: 'line.3.horizontal.decrease', android: 'tune', web: 'tune' }}
            active={statusFilter !== 'all' || sortMode !== 'status'}
            onPress={() => setControlsOpen(true)}
          />
        </View>
      </View>

      {searchOpen ? (
        <Animated.View entering={FadeInDown.duration(180).easing(easeOut)}>
          <Field
            autoFocus
            placeholder="Search title or author"
            value={query}
            onChangeText={setQuery}
            returnKeyType="search"
            style={styles.searchField}
          />
        </Animated.View>
      ) : null}

      {error ? <ErrorText message={error} /> : null}

      <FlatList
        key={viewMode}
        style={styles.list}
        contentContainerStyle={{ paddingBottom: 100 }}
        data={visibleBooks}
        keyExtractor={(item) => String(item.id)}
        numColumns={viewMode === 'grid' ? 3 : 1}
        columnWrapperStyle={viewMode === 'grid' ? styles.gridRow : undefined}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              load('pull');
            }}
            tintColor={palette.accent}
          />
        }
        ListEmptyComponent={<Muted>No books match these filters.</Muted>}
        renderItem={({ item, index }) => renderBook(item, index)}
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

      <Sheet visible={controlsOpen} title="View & sort" onClose={() => setControlsOpen(false)}>
        <Text style={styles.sheetLabel}>Layout</Text>
        <View style={styles.chips}>
          {(['list', 'grid'] as ViewMode[]).map((mode) => (
            <Chip
              key={mode}
              label={mode === 'list' ? 'List' : 'Grid'}
              active={viewMode === mode}
              onPress={() => setViewMode(mode)}
            />
          ))}
        </View>

        <Text style={styles.sheetLabel}>Status</Text>
        <View style={styles.chips}>
          <Chip label="All" active={statusFilter === 'all'} onPress={() => setStatusFilter('all')} />
          {STATUS_OPTIONS.map((status) => (
            <Chip
              key={status}
              label={STATUS_LABELS[status]}
              active={statusFilter === status}
              onPress={() => setStatusFilter(status)}
            />
          ))}
        </View>

        <Text style={styles.sheetLabel}>Sort</Text>
        <View style={styles.chips}>
          <Chip
            label="Shelf order"
            active={sortMode === 'status'}
            onPress={() => setSortMode('status')}
          />
          <Chip
            label="A–Z"
            active={sortMode === 'title_asc'}
            onPress={() => setSortMode('title_asc')}
          />
          <Chip
            label="Z–A"
            active={sortMode === 'title_desc'}
            onPress={() => setSortMode('title_desc')}
          />
        </View>
        <PrimaryButton label="Done" onPress={() => setControlsOpen(false)} />
      </Sheet>

      <Sheet visible={addOpen} title="Add to shelf" onClose={() => setAddOpen(false)}>
        <Muted>Typos are fine — Gemini can help tidy metadata.</Muted>
        <Field
          autoFocus
          placeholder="Book title"
          value={draftTitle}
          onChangeText={setDraftTitle}
          onSubmitEditing={onAdd}
        />
        <PrimaryButton label={adding ? 'Adding…' : 'Add book'} onPress={onAdd} disabled={adding} />
      </Sheet>
    </Screen>
  );
}

function IconButton({
  name,
  onPress,
  active,
}: {
  name: { ios: string; android: string; web: string };
  onPress: () => void;
  active?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.iconBtn,
        active && styles.iconBtnActive,
        pressed && { opacity: 0.7 },
      ]}
    >
      <SymbolView name={name} tintColor={active ? '#1a1208' : palette.ink} size={18} />
    </Pressable>
  );
}

function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.chip, active && styles.chipActive]}>
      <Text style={[styles.chipText, active && styles.chipTextActive]}>{label}</Text>
    </Pressable>
  );
}

const gridGap = 10;
const gridWidth = (Dimensions.get('window').width - spacing.md * 2 - gridGap * 2) / 3;

const styles = StyleSheet.create({
  screen: {
    paddingBottom: 0,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  brand: {
    color: palette.ink,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: -0.4,
  },
  summary: {
    color: palette.muted,
    fontSize: 13,
    marginTop: 2,
  },
  headerActions: {
    flexDirection: 'row',
    gap: 8,
    paddingTop: 4,
  },
  iconBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: palette.bgElevated,
    borderWidth: 1,
    borderColor: palette.border,
  },
  iconBtnActive: {
    backgroundColor: palette.accent,
    borderColor: palette.accent,
  },
  searchField: {
    marginBottom: spacing.sm,
  },
  list: {
    flex: 1,
  },
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: palette.border,
  },
  cover: {
    width: 54,
    height: 80,
    borderRadius: 4,
    backgroundColor: palette.bgElevated,
  },
  coverFallback: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  coverLetter: {
    color: palette.accent,
    fontSize: 22,
    fontWeight: '700',
  },
  meta: {
    flex: 1,
    justifyContent: 'center',
    gap: 2,
  },
  bookTitle: {
    color: palette.ink,
    fontSize: 16,
    fontWeight: '600',
  },
  bookAuthors: {
    color: palette.muted,
    fontSize: 13,
  },
  bookStatus: {
    color: palette.accent,
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginTop: 2,
  },
  gridRow: {
    gap: gridGap,
  },
  gridCard: {
    width: gridWidth,
    marginBottom: gridGap,
  },
  gridCover: {
    width: '100%',
    aspectRatio: 2 / 3,
    borderRadius: 6,
    backgroundColor: palette.bgElevated,
  },
  gridTitle: {
    color: palette.ink,
    fontSize: 12,
    fontWeight: '600',
    marginTop: 6,
  },
  gridStatus: {
    color: palette.muted,
    fontSize: 10,
    textTransform: 'uppercase',
    marginTop: 2,
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
  sheetLabel: {
    color: palette.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontSize: 12,
    marginBottom: 8,
    marginTop: 4,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: spacing.md,
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
});
