from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from library.db import get_connection, init_db
from library.enrich import EnrichmentResult, enrich_title

ALLOWED_STATUSES = {
    "reading",
    "want_to_read",
    "not_finished",
    "read",
    "dropped",
    "other",
}


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def normalize_status(status: str) -> str:
    value = (status or "").strip().lower().replace(" ", "_")
    if value not in ALLOWED_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}. Expected one of: {', '.join(sorted(ALLOWED_STATUSES))}"
        )
    return value


def add_book(
    title: str,
    status: str = "want_to_read",
    source: str = "manual",
    *,
    enrich: bool = True,
    use_llm: bool = False,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert or update a book by raw title + status. Optionally enrich metadata."""
    raw_title = title.strip()
    if not raw_title:
        raise ValueError("title is required")

    status = normalize_status(status or "want_to_read")
    init_db(db_path)

    enrichment: EnrichmentResult | None = None
    if enrich:
        enrichment = enrich_title(raw_title, use_llm=use_llm)

    with get_connection(db_path) as conn:
        existing = conn.execute(
            """
            SELECT id FROM books
            WHERE lower(raw_title) = lower(?) AND status = ?
            """,
            (raw_title, status),
        ).fetchone()

        if enrichment:
            fields = {
                "title": enrichment.title or raw_title,
                "authors": enrichment.authors,
                "cover_url": enrichment.cover_url,
                "page_count": enrichment.page_count,
                "first_publish_year": enrichment.first_publish_year,
                "subjects": enrichment.subjects,
                "synopsis": enrichment.synopsis,
                "metadata_source": enrichment.metadata_source,
                "match_confidence": enrichment.match_confidence,
                "needs_review": 1 if enrichment.needs_review else 0,
                "enriched_at": "set",
            }
        else:
            fields = {
                "title": raw_title,
                "authors": None,
                "cover_url": None,
                "page_count": None,
                "first_publish_year": None,
                "subjects": None,
                "synopsis": None,
                "metadata_source": None,
                "match_confidence": None,
                "needs_review": 1,
                "enriched_at": None,
            }

        if existing:
            conn.execute(
                """
                UPDATE books SET
                    title = ?,
                    authors = ?,
                    cover_url = ?,
                    page_count = ?,
                    first_publish_year = ?,
                    subjects = ?,
                    synopsis = ?,
                    source = COALESCE(?, source),
                    metadata_source = ?,
                    match_confidence = ?,
                    needs_review = ?,
                    enriched_at = CASE WHEN ? IS NOT NULL THEN datetime('now') ELSE enriched_at END,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    fields["title"],
                    fields["authors"],
                    fields["cover_url"],
                    fields["page_count"],
                    fields["first_publish_year"],
                    fields["subjects"],
                    fields["synopsis"],
                    source,
                    fields["metadata_source"],
                    fields["match_confidence"],
                    fields["needs_review"],
                    fields["enriched_at"],
                    existing["id"],
                ),
            )
            book_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO books (
                    raw_title, title, authors, status, cover_url, page_count,
                    first_publish_year, subjects, synopsis, source, metadata_source,
                    match_confidence, needs_review, enriched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IS NOT NULL THEN datetime('now') ELSE NULL END)
                """,
                (
                    raw_title,
                    fields["title"],
                    fields["authors"],
                    status,
                    fields["cover_url"],
                    fields["page_count"],
                    fields["first_publish_year"],
                    fields["subjects"],
                    fields["synopsis"],
                    source,
                    fields["metadata_source"],
                    fields["match_confidence"],
                    fields["needs_review"],
                    fields["enriched_at"],
                ),
            )
            book_id = cursor.lastrowid

        conn.commit()
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return row_to_dict(row)


def delete_book(book_id: int, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_book_status(
    book_id: int,
    status: str,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Change a book's reading status."""
    status = normalize_status(status)
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return None
        if row["status"] == status:
            return row_to_dict(row)

        conflict = conn.execute(
            """
            SELECT id FROM books
            WHERE id != ?
              AND lower(raw_title) = lower(?)
              AND status = ?
            """,
            (book_id, row["raw_title"], status),
        ).fetchone()
        if conflict:
            raise ValueError(
                f"Another shelf entry already uses status {status!r} for this title"
            )

        conn.execute(
            """
            UPDATE books
            SET status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, book_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return row_to_dict(updated) if updated else None


def get_book(book_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return row_to_dict(row) if row else None


def list_books(
    *,
    status: str | None = None,
    search: str | None = None,
    needs_review: bool | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    clauses: list[str] = []
    params: list[Any] = []

    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append(
            "(lower(coalesce(title, '')) LIKE ? OR lower(raw_title) LIKE ? OR lower(coalesce(authors, '')) LIKE ?)"
        )
        needle = f"%{search.casefold()}%"
        params.extend([needle, needle, needle])
    if needs_review is not None:
        clauses.append("needs_review = ?")
        params.append(1 if needs_review else 0)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM books
        {where}
        ORDER BY
            CASE status
                WHEN 'reading' THEN 0
                WHEN 'want_to_read' THEN 1
                WHEN 'not_finished' THEN 2
                WHEN 'read' THEN 3
                WHEN 'dropped' THEN 4
                ELSE 5
            END,
            lower(coalesce(title, raw_title))
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [row_to_dict(row) for row in rows]


def count_by_status(db_path: Path | None = None) -> dict[str, int]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM books GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}


def apply_enrichment_to_book(
    book_id: int,
    enrichment: EnrichmentResult,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        book = conn.execute("SELECT raw_title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book:
            return None
        title = enrichment.title or book["raw_title"]
        conn.execute(
            """
            UPDATE books SET
                title = ?,
                authors = ?,
                cover_url = ?,
                page_count = ?,
                first_publish_year = ?,
                subjects = ?,
                synopsis = ?,
                metadata_source = ?,
                match_confidence = ?,
                needs_review = ?,
                enriched_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                title,
                enrichment.authors,
                enrichment.cover_url,
                enrichment.page_count,
                enrichment.first_publish_year,
                enrichment.subjects,
                enrichment.synopsis,
                enrichment.metadata_source,
                enrichment.match_confidence,
                1 if enrichment.needs_review else 0,
                book_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return row_to_dict(row) if row else None


def list_pending_enrichment(
    db_path: Path | None = None,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        if force:
            rows = conn.execute("SELECT * FROM books ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM books
                WHERE enriched_at IS NULL
                   OR needs_review = 1
                   OR metadata_source IS NULL
                   OR metadata_source = 'openlibrary'
                ORDER BY id
                """
            ).fetchall()
        return [row_to_dict(row) for row in rows]


def reenrich_book(
    book_id: int,
    *,
    title: str | None = None,
    use_llm: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Optionally rename raw_title, then re-run enrichment (LLM-assisted by default)."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return None
        raw_title = (title or row["raw_title"] or "").strip()
        if not raw_title:
            raise ValueError("title is required")
        if title is not None and raw_title != row["raw_title"]:
            conn.execute(
                """
                UPDATE books SET
                    raw_title = ?,
                    title = ?,
                    authors = NULL,
                    cover_url = NULL,
                    page_count = NULL,
                    first_publish_year = NULL,
                    subjects = NULL,
                    synopsis = NULL,
                    metadata_source = NULL,
                    match_confidence = NULL,
                    needs_review = 1,
                    enriched_at = NULL,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (raw_title, raw_title, book_id),
            )
            conn.commit()

    result = enrich_title(raw_title, use_llm=use_llm)
    return apply_enrichment_to_book(book_id, result, db_path=db_path)


def reset_metadata(db_path: Path | None = None) -> int:
    """Clear enrichment fields so titles fall back to raw_title before re-enrich."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE books SET
                title = raw_title,
                authors = NULL,
                cover_url = NULL,
                page_count = NULL,
                first_publish_year = NULL,
                subjects = NULL,
                synopsis = NULL,
                metadata_source = NULL,
                match_confidence = NULL,
                needs_review = 1,
                enriched_at = NULL,
                updated_at = datetime('now')
            """
        )
        conn.commit()
        return cursor.rowcount


def list_books_missing_covers(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM books
            WHERE cover_url IS NULL OR cover_url = ''
            ORDER BY id
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def repair_book_cover(
    book_id: int,
    *,
    client=None,
    browser_session=None,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    """Find a cover for an existing book without wiping title/author/status."""
    from library.enrich import (
        find_cover_candidates,
        make_browser_session,
        make_http_client,
    )

    init_db(db_path)
    book = get_book(book_id, db_path=db_path)
    if not book:
        return None
    if book.get("cover_url"):
        return book

    query = (book.get("title") or book.get("raw_title") or "").strip()
    if not query:
        return book

    owns_client = client is None
    owns_browser = browser_session is None
    http = client or make_http_client()
    browser = browser_session or make_browser_session()

    cover_url = None
    page_count = book.get("page_count")
    year = book.get("first_publish_year")
    try:
        hit = find_cover_candidates(
            query,
            authors=book.get("authors"),
            client=http,
            browser_session=browser,
        )
        if hit:
            cover_url = hit.get("cover_url")
            if hit.get("page_count") and not page_count:
                page_count = hit["page_count"]
            if hit.get("first_publish_year") and not year:
                year = hit["first_publish_year"]
    finally:
        if owns_client:
            http.close()
        if owns_browser and browser is not None and hasattr(browser, "close"):
            try:
                browser.close()
            except Exception:
                pass

    if not cover_url:
        return book

    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE books SET
                cover_url = ?,
                page_count = COALESCE(?, page_count),
                first_publish_year = COALESCE(?, first_publish_year),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (cover_url, page_count, year, book_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        return row_to_dict(row) if row else None
