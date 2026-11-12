export type BookStatus =
  | 'reading'
  | 'want_to_read'
  | 'not_finished'
  | 'read'
  | 'dropped'
  | 'other';

export interface Book {
  id: number;
  raw_title: string;
  title?: string | null;
  authors?: string | null;
  status: BookStatus | string;
  cover_url?: string | null;
  subjects?: string | null;
  synopsis?: string | null;
  source_url?: string | null;
  adapter?: string | null;
  pipeline_status?: string | null;
  completion?: string | null;
  pov?: string | null;
  epub_path?: string | null;
  last_chapter_index?: number | null;
  last_chapter_title?: string | null;
  needs_review?: number | boolean | null;
  metadata_source?: string | null;
  categories?: Category[];
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  description?: string | null;
  color?: string | null;
  book_count?: number;
}

export interface CompileJob {
  id: number;
  book_id?: number | null;
  source_url: string;
  adapter: string;
  status: string;
  chapter_count?: number | null;
  epub_path?: string | null;
  error?: string | null;
  created_at?: string;
}

export interface CompileResult {
  title?: string;
  authors?: string | null;
  chapter_count?: number;
  epub_path?: string;
  book?: Book | null;
  job?: CompileJob | null;
  job_id?: number;
  queued?: boolean;
}

export const STATUS_LABELS: Record<string, string> = {
  reading: 'Reading',
  want_to_read: 'Want to read',
  not_finished: 'Not finished',
  read: 'Read',
  dropped: 'Dropped',
  other: 'Other',
};

export const STATUS_OPTIONS = Object.keys(STATUS_LABELS);
