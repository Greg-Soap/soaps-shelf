from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "library.db"
CACHE_DIR = DATA_DIR / "cache"
RAW_DIR = DATA_DIR / "raw"
EPUB_DIR = DATA_DIR / "epubs"

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_title TEXT NOT NULL,
    title TEXT,
    authors TEXT,
    status TEXT NOT NULL DEFAULT 'want_to_read',
    cover_url TEXT,
    page_count INTEGER,
    first_publish_year INTEGER,
    subjects TEXT,
    synopsis TEXT,
    source TEXT,
    metadata_source TEXT,
    match_confidence REAL,
    needs_review INTEGER NOT NULL DEFAULT 1,
    enriched_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_books_raw_title_status
    ON books (lower(raw_title), status);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    color TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS book_categories (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (book_id, category_id)
);

CREATE TABLE IF NOT EXISTS compile_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    source_url TEXT NOT NULL,
    adapter TEXT NOT NULL DEFAULT 'webtoepub',
    status TEXT NOT NULL DEFAULT 'queued',
    chapter_from INTEGER,
    chapter_to INTEGER,
    chapter_count INTEGER,
    epub_path TEXT,
    error TEXT,
    options_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);
"""

# Columns added after the original books table shipped
EXTRA_COLUMNS = {
    "synopsis": "TEXT",
    "metadata_source": "TEXT",
    "source_url": "TEXT",
    "adapter": "TEXT",
    "pipeline_status": "TEXT",
    "completion": "TEXT",
    "pov": "TEXT",
    "last_chapter_index": "INTEGER",
    "last_chapter_title": "TEXT",
    "epub_path": "TEXT",
    "epub_built_at": "TEXT",
}

COMPILE_JOB_EXTRA_COLUMNS = {
    "options_json": "TEXT",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EPUB_DIR.mkdir(parents=True, exist_ok=True)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(books)").fetchall()
        }
        for column, col_type in EXTRA_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE books ADD COLUMN {column} {col_type}")
        job_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(compile_jobs)").fetchall()
        }
        for column, col_type in COMPILE_JOB_EXTRA_COLUMNS.items():
            if column not in job_cols:
                conn.execute(f"ALTER TABLE compile_jobs ADD COLUMN {column} {col_type}")
        conn.commit()
