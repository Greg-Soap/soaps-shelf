import Constants from 'expo-constants';

import type { Book, Category, CompileJob, CompileResult } from '@/lib/types';

function resolveApiBase(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  if (fromEnv) return fromEnv.replace(/\/$/, '');

  const extra = Constants.expoConfig?.extra as { apiUrl?: string } | undefined;
  if (extra?.apiUrl) return extra.apiUrl.replace(/\/$/, '');

  // Simulator / same machine fallback
  return 'http://127.0.0.1:8000';
}

export const API_BASE = resolveApiBase();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // ignore
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function listBooks(params?: { status?: string; q?: string }): Promise<Book[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set('status', params.status);
  if (params?.q) query.set('q', params.q);
  const suffix = query.toString() ? `?${query}` : '';
  return request<Book[]>(`/api/books${suffix}`);
}

export function getBook(id: number): Promise<Book> {
  return request<Book>(`/api/books/${id}`);
}

export function updateBookStatus(id: number, status: string): Promise<Book> {
  return request<Book>(`/api/books/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
}

export function addBook(title: string, status = 'want_to_read'): Promise<Book> {
  return request<Book>('/api/books', {
    method: 'POST',
    body: JSON.stringify({
      title,
      status,
      source: 'mobile',
      enrich: true,
      use_llm: true,
    }),
  });
}

export function deleteBook(id: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/books/${id}`, { method: 'DELETE' });
}

export function listCategories(): Promise<Category[]> {
  return request<Category[]>('/api/categories');
}

export function createCategory(input: {
  name: string;
  description?: string;
  color?: string;
}): Promise<Category> {
  return request<Category>('/api/categories', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export function deleteCategory(id: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/categories/${id}`, { method: 'DELETE' });
}

export function setBookCategories(bookId: number, categoryIds: number[]): Promise<Category[]> {
  return request<Category[]>(`/api/books/${bookId}/categories`, {
    method: 'POST',
    body: JSON.stringify({ category_ids: categoryIds }),
  });
}

export function listCompileJobs(limit = 20): Promise<CompileJob[]> {
  return request<CompileJob[]>(`/api/compile/jobs?limit=${limit}`);
}

export function getCompileJob(jobId: number): Promise<CompileJob> {
  return request<CompileJob>(`/api/compile/jobs/${jobId}`);
}

export function compileUrl(input: {
  url: string;
  status?: string;
  limit?: number | null;
}): Promise<CompileResult> {
  return request<CompileResult>('/api/compile', {
    method: 'POST',
    body: JSON.stringify({
      url: input.url,
      status: input.status || 'want_to_read',
      limit: input.limit ?? null,
      delay: 0.5,
    }),
  });
}

export function epubDownloadUrl(epubPath: string | null | undefined): string | null {
  if (!epubPath) return null;
  const filename = epubPath.split(/[/\\]/).pop();
  if (!filename) return null;
  return `${API_BASE}/epubs/${encodeURIComponent(filename)}`;
}
