from __future__ import annotations

import json
import threading
import traceback
from typing import Any

from library.books import add_book
from library.compiler.epub import build_epub
from library.compiler.models import ChapterContent, FictionMeta
from library.compiler import royalroad as rr
from library.compiler import wte_client
from library.db import EPUB_DIR, get_connection, init_db

_worker_lock = threading.Lock()
_worker_started = False


def list_adapters() -> list[dict[str, str]]:
    adapters = [
        {
            "id": "webtoepub",
            "label": "WebToEpub (100+ sites)",
            "hosts": "auto-detect from URL",
        },
        {
            "id": "royalroad",
            "label": "Royal Road (Python fallback)",
            "hosts": "royalroad.com",
        },
    ]
    try:
        hosts = wte_client.list_hosts()
        count = hosts.get("count")
        if count:
            adapters[0]["label"] = f"WebToEpub ({count} hosts)"
    except Exception:
        pass
    return adapters


def detect_adapter(url: str) -> str | None:
    try:
        detected = wte_client.detect_url(url)
        if detected.get("supported"):
            return detected.get("adapter") or "webtoepub"
    except Exception:
        pass
    if rr.can_handle(url):
        return "royalroad"
    return "webtoepub"


def _update_job(job_id: int, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values())
    values.append(job_id)
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE compile_jobs
            SET {assignments}, updated_at = datetime('now')
            WHERE id = ?
            """,
            values,
        )
        conn.commit()


def _create_job(
    source_url: str,
    adapter: str,
    book_id: int | None,
    *,
    chapter_from: int = 0,
    chapter_to: int | None = None,
    status: str = "queued",
    options: dict[str, Any] | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO compile_jobs (
                book_id, source_url, adapter, status, chapter_from, chapter_to, options_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                source_url,
                adapter,
                status,
                chapter_from,
                chapter_to,
                json.dumps(options or {}),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_job(job_id: int) -> dict[str, Any] | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM compile_jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM compile_jobs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def _claim_next_job() -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM compile_jobs
            WHERE status = 'queued'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        job = dict(row)
        conn.execute(
            """
            UPDATE compile_jobs
            SET status = 'compiling', updated_at = datetime('now')
            WHERE id = ? AND status = 'queued'
            """,
            (job["id"],),
        )
        conn.commit()
        claimed = conn.execute("SELECT * FROM compile_jobs WHERE id = ?", (job["id"],)).fetchone()
        return dict(claimed) if claimed and claimed["status"] == "compiling" else None


def _meta_from_wte(payload: dict[str, Any]) -> tuple[FictionMeta, list[ChapterContent]]:
    chapters = [
        ChapterContent(
            index=int(item.get("index", idx)),
            title=str(item.get("title") or f"Chapter {idx + 1}"),
            url=str(item.get("sourceUrl") or ""),
            html=str(item.get("html") or ""),
        )
        for idx, item in enumerate(payload.get("chapters") or [])
    ]
    meta = FictionMeta(
        title=str(payload.get("title") or "Untitled"),
        authors=payload.get("authors"),
        synopsis=payload.get("synopsis"),
        cover_url=payload.get("coverUrl"),
        subjects=payload.get("subjects"),
        source_url=str(payload.get("sourceUrl") or ""),
        adapter=str(payload.get("adapter") or "webtoepub"),
    )
    return meta, chapters


def _scrape(url: str, *, chapter_from: int, chapter_to: int | None, limit: int | None, delay: float) -> tuple[FictionMeta, list[ChapterContent], str]:
    """Prefer WebToEpub; fall back to Python Royal Road on CF/blocked failures."""
    wte_error: Exception | None = None
    try:
        payload = wte_client.compile_url(
            url,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            limit=limit,
            delay=delay,
        )
        meta, chapters = _meta_from_wte(payload)
        return meta, chapters, str(payload.get("adapter") or "webtoepub")
    except Exception as err:
        wte_error = err

    if rr.can_handle(url):
        meta = rr.fetch_fiction_meta(url)
        chapters = rr.fetch_chapters(
            meta,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            delay=delay,
            limit=limit,
        )
        return meta, chapters, "royalroad"

    raise RuntimeError(str(wte_error) if wte_error else "Compile failed")


def _finalize_success(
    *,
    job_id: int,
    meta: FictionMeta,
    chapters: list[ChapterContent],
    adapter: str,
    status: str,
    book_id: int | None,
    use_llm: bool,
    chapter_from: int,
    chapter_to: int | None,
) -> dict[str, Any]:
    epub_path = build_epub(meta, chapters)

    if book_id is None:
        book = add_book(
            meta.title,
            status=status,
            source="compiler",
            enrich=False,
            use_llm=use_llm,
        )
        book_id = int(book["id"])
    else:
        book = None

    last = chapters[-1]
    try:
        relative = str(epub_path.relative_to(EPUB_DIR.parent))
    except ValueError:
        relative = str(epub_path)

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE books SET
                title = COALESCE(?, title),
                authors = COALESCE(?, authors),
                cover_url = COALESCE(?, cover_url),
                subjects = COALESCE(?, subjects),
                synopsis = COALESCE(?, synopsis),
                source_url = ?,
                adapter = ?,
                pipeline_status = 'ready',
                last_chapter_index = ?,
                last_chapter_title = ?,
                epub_path = ?,
                epub_built_at = datetime('now'),
                metadata_source = COALESCE(metadata_source, ?),
                needs_review = 0,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                meta.title,
                meta.authors,
                meta.cover_url,
                meta.subjects,
                meta.synopsis,
                meta.source_url,
                adapter,
                last.index,
                last.title,
                str(epub_path),
                adapter,
                book_id,
            ),
        )
        conn.execute(
            """
            UPDATE compile_jobs
            SET status = 'ready',
                book_id = ?,
                adapter = ?,
                chapter_from = ?,
                chapter_to = ?,
                chapter_count = ?,
                epub_path = ?,
                error = NULL,
                finished_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                book_id,
                adapter,
                chapter_from,
                last.index if chapter_to is None else chapter_to,
                len(chapters),
                str(epub_path),
                job_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        book = dict(row) if row else book

    return {
        "job": get_job(job_id),
        "book": book,
        "epub_path": str(epub_path),
        "epub_relative": relative,
        "chapter_count": len(chapters),
        "title": meta.title,
        "authors": meta.authors,
    }


def _fail_job(job_id: int, err: Exception) -> None:
    _update_job(job_id, status="failed", error=str(err))
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE compile_jobs
            SET finished_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (job_id,),
        )
        conn.commit()


def process_job(job_id: int, *, status: str = "want_to_read", limit: int | None = None, delay: float = 0.55, use_llm: bool = False) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    url = job["source_url"]
    chapter_from = int(job.get("chapter_from") or 0)
    chapter_to = job.get("chapter_to")
    chapter_to_i = int(chapter_to) if chapter_to is not None else None
    book_id = job.get("book_id")
    book_id_i = int(book_id) if book_id is not None else None

    _update_job(job_id, status="compiling", error=None)
    try:
        meta, chapters, adapter = _scrape(
            url,
            chapter_from=chapter_from,
            chapter_to=chapter_to_i,
            limit=limit,
            delay=delay,
        )
        return _finalize_success(
            job_id=job_id,
            meta=meta,
            chapters=chapters,
            adapter=adapter,
            status=status,
            book_id=book_id_i,
            use_llm=use_llm,
            chapter_from=chapter_from,
            chapter_to=chapter_to_i,
        )
    except Exception as err:
        _fail_job(job_id, err)
        raise


def enqueue_compile(
    url: str,
    *,
    status: str = "want_to_read",
    chapter_from: int = 0,
    chapter_to: int | None = None,
    limit: int | None = None,
    delay: float = 0.55,
    book_id: int | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    """Create a queued compile job and ensure the background worker is running."""
    init_db()
    adapter = detect_adapter(url) or "webtoepub"
    job_id = _create_job(
        url,
        adapter,
        book_id,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        status="queued",
        options={
            "status": status,
            "limit": limit,
            "delay": delay,
            "use_llm": use_llm,
        },
    )
    ensure_compile_worker()
    return {"job": get_job(job_id), "queued": True, "job_id": job_id}


def compile_source_url(
    url: str,
    *,
    status: str = "want_to_read",
    chapter_from: int = 0,
    chapter_to: int | None = None,
    limit: int | None = None,
    delay: float = 0.55,
    book_id: int | None = None,
    use_llm: bool = False,
    sync: bool = False,
) -> dict[str, Any]:
    """Enqueue by default (Render-safe). Pass sync=True for local/CLI blocking compiles."""
    init_db()
    if not sync:
        return enqueue_compile(
            url,
            status=status,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            limit=limit,
            delay=delay,
            book_id=book_id,
            use_llm=use_llm,
        )

    adapter = detect_adapter(url) or "webtoepub"
    job_id = _create_job(
        url,
        adapter,
        book_id,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        status="compiling",
    )
    try:
        meta, chapters, used_adapter = _scrape(
            url,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            limit=limit,
            delay=delay,
        )
        return _finalize_success(
            job_id=job_id,
            meta=meta,
            chapters=chapters,
            adapter=used_adapter,
            status=status,
            book_id=book_id,
            use_llm=use_llm,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
        )
    except Exception as err:
        _fail_job(job_id, err)
        raise


def _worker_loop() -> None:
    while True:
        job = _claim_next_job()
        if not job:
            threading.Event().wait(1.0)
            continue
        job_id = int(job["id"])
        options: dict[str, Any] = {}
        raw = job.get("options_json")
        if raw:
            try:
                options = json.loads(raw)
            except Exception:
                options = {}
        try:
            process_job(
                job_id,
                status=options.get("status", "want_to_read"),
                limit=options.get("limit"),
                delay=float(options.get("delay", 0.55)),
                use_llm=bool(options.get("use_llm", False)),
            )
        except Exception:
            traceback.print_exc()


def ensure_compile_worker() -> None:
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="compile-worker", daemon=True)
        thread.start()
        _worker_started = True
