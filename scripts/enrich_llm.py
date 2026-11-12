#!/usr/bin/env python3
"""Fill Needs-review books with LLM metadata (Gemini, OpenAI, or Anthropic)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.books import apply_enrichment_to_book, list_books
from library.db import get_connection, init_db
from library.enrich import make_browser_session, make_http_client
from library.llm_enrich import available_llm_provider, enrich_with_llm, load_dotenv


def list_llm_targets(*, missing_only: bool = True) -> list[dict]:
    init_db()
    with get_connection() as conn:
        if missing_only:
            rows = conn.execute(
                """
                SELECT * FROM books
                WHERE needs_review = 1
                  AND (
                    authors IS NULL OR authors = ''
                    OR metadata_source IS NULL
                    OR cover_url IS NULL
                  )
                ORDER BY id
                """
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM books WHERE needs_review = 1 ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]


def clear_review_when_solid() -> int:
    """Drop needs_review when we already have author + solid source/confidence."""
    init_db()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE books
            SET needs_review = 0, updated_at = datetime('now')
            WHERE needs_review = 1
              AND authors IS NOT NULL AND authors != ''
              AND match_confidence >= 0.85
              AND metadata_source IN (
                'aethon', 'chikari', 'freewebnovel', 'royalroad',
                'novelupdates', 'openlibrary', 'llm'
              )
            """
        )
        conn.commit()
        return cursor.rowcount


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM-enrich needs-review books")
    parser.add_argument("--limit", type=int, default=0, help="Max books (0 = all)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between calls")
    parser.add_argument(
        "--all-review",
        action="store_true",
        help="Process every needs_review row, even if author already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List targets without calling the LLM",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()
    init_db()

    cleared = clear_review_when_solid()
    if cleared:
        print(f"Cleared needs_review on {cleared} solid matches")

    provider = available_llm_provider()
    if not provider and not args.dry_run:
        print(
            "No API key found.\n"
            "Create book-library/.env with one of:\n"
            "  GEMINI_API_KEY=...\n"
            "  OPENAI_API_KEY=sk-...\n"
            "  ANTHROPIC_API_KEY=sk-ant-...\n"
        )
        return 1

    targets = list_llm_targets(missing_only=not args.all_review)
    if args.limit > 0:
        targets = targets[: args.limit]

    print(f"Provider: {provider or 'none'} · targets: {len(targets)}")
    if args.dry_run:
        for book in targets[:30]:
            print(f"  - {book['raw_title']}")
        if len(targets) > 30:
            print(f"  … +{len(targets) - 30} more")
        return 0

    browser = make_browser_session()
    client = make_http_client()
    try:
        for index, book in enumerate(targets, start=1):
            result = enrich_with_llm(
                book["raw_title"],
                client=client,
                browser_session=browser,
            )
            # Preserve an existing good cover if LLM didn't find one
            if not result.cover_url and book.get("cover_url"):
                result.cover_url = book["cover_url"]
            apply_enrichment_to_book(book["id"], result)
            flag = "REVIEW" if result.needs_review else "ok"
            print(
                f"[{index}/{len(targets)}] {flag}/llm  "
                f"{book['raw_title']!r} → {result.title!r} | {result.authors!r} "
                f"(confidence={result.match_confidence:.2f})"
            )
            if index < len(targets):
                time.sleep(args.delay)
    finally:
        client.close()
        if browser is not None and hasattr(browser, "close"):
            try:
                browser.close()
            except Exception:
                pass

    remaining = len(list_books(needs_review=True))
    print(f"Done. Needs review remaining: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
