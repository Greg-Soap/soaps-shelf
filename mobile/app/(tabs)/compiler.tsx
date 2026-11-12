import * as Linking from 'expo-linking';
import { useCallback, useRef, useState } from 'react';
import { FlatList, StyleSheet, Text, View } from 'react-native';
import { useFocusEffect } from 'expo-router';

import { ErrorText, Field, Loading, Muted, PrimaryButton, Screen, Title } from '@/components/ui';
import { compileUrl, epubDownloadUrl, getCompileJob, listCompileJobs } from '@/lib/api';
import type { CompileJob } from '@/lib/types';
import { palette, spacing } from '@/constants/theme';

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function CompilerScreen() {
  const [url, setUrl] = useState('');
  const [limit, setLimit] = useState('3');
  const [jobs, setJobs] = useState<CompileJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const pollingRef = useRef(false);

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await listCompileJobs(20));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load jobs');
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      loadJobs();
    }, [loadJobs]),
  );

  async function pollJob(jobId: number) {
    pollingRef.current = true;
    try {
      for (let attempt = 0; attempt < 180; attempt += 1) {
        const job = await getCompileJob(jobId);
        setMessage(`Job #${jobId} · ${job.status}`);
        if (job.status === 'ready') {
          const download = epubDownloadUrl(job.epub_path);
          setMessage(
            `Ready · job #${jobId}` +
              (job.chapter_count ? ` · ${job.chapter_count} chapters` : ''),
          );
          if (download) await Linking.openURL(download);
          return;
        }
        if (job.status === 'failed') {
          throw new Error(job.error || 'Compile failed');
        }
        await sleep(2000);
      }
      throw new Error('Timed out waiting for compile job');
    } finally {
      pollingRef.current = false;
    }
  }

  async function onCompile() {
    const fictionUrl = url.trim();
    if (!fictionUrl || busy) return;
    setBusy(true);
    setError('');
    setMessage('Queuing compile…');
    try {
      const parsedLimit = Number(limit);
      const result = await compileUrl({
        url: fictionUrl,
        limit: Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : null,
      });
      const jobId = result.job_id || result.job?.id;
      if (!jobId) throw new Error('No job id returned');
      setMessage(`Queued job #${jobId}`);
      await pollJob(jobId);
      await loadJobs();
    } catch (err) {
      setMessage('');
      setError(err instanceof Error ? err.message : 'Compile failed');
      await loadJobs();
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <Loading />;

  return (
    <Screen>
      <Title>Compile</Title>
      <Muted>
        Any WebToEpub-supported fiction URL → EPUB. Use limit 3 to test; 0 for the full book.
      </Muted>

      <Field
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="https://…"
        value={url}
        onChangeText={setUrl}
      />
      <Field
        keyboardType="number-pad"
        placeholder="Chapter limit (0 = all)"
        value={limit}
        onChangeText={setLimit}
      />
      <PrimaryButton
        label={busy ? 'Working…' : 'Compile EPUB'}
        onPress={onCompile}
        disabled={busy}
      />

      {message ? <Text style={styles.ok}>{message}</Text> : null}
      {error ? <ErrorText message={error} /> : null}

      <Text style={styles.section}>Recent jobs</Text>
      <FlatList
        data={jobs}
        keyExtractor={(item) => String(item.id)}
        ListEmptyComponent={<Muted>No jobs yet.</Muted>}
        renderItem={({ item }) => (
          <View style={styles.job}>
            <Text style={styles.jobStatus}>{item.status}</Text>
            <Text style={styles.jobUrl} numberOfLines={2}>
              {item.source_url}
            </Text>
            <Text style={styles.jobMeta}>
              {item.adapter}
              {item.chapter_count ? ` · ${item.chapter_count} ch` : ''}
            </Text>
            {item.epub_path ? (
              <Text
                style={styles.link}
                onPress={() => {
                  const href = epubDownloadUrl(item.epub_path);
                  if (href) Linking.openURL(href);
                }}
              >
                Download EPUB
              </Text>
            ) : null}
            {item.error ? <Text style={styles.jobError}>{item.error}</Text> : null}
          </View>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  ok: {
    color: palette.success,
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  section: {
    color: palette.ink,
    fontSize: 18,
    fontWeight: '600',
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  job: {
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: 14,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    backgroundColor: palette.bgElevated,
    gap: 3,
  },
  jobStatus: {
    color: palette.accent,
    textTransform: 'uppercase',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  jobUrl: {
    color: palette.ink,
    fontSize: 14,
  },
  jobMeta: {
    color: palette.muted,
    fontSize: 12,
  },
  link: {
    color: palette.accent,
    marginTop: 4,
    fontWeight: '600',
  },
  jobError: {
    color: palette.danger,
    fontSize: 12,
  },
});
