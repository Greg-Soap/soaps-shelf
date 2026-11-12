#!/usr/bin/env python3
"""Fill missing cover images without rewriting title/author/status."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.books import list_books_missing_covers, repair_book_cover
from library.db import init_db
from library.enrich import make_browser_session, make_http_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair missing book covers")
    parser.add_argument("--limit", type=int, default=0, help="Max books (0 = all)")
    parser.add_argument("--delay", type=float, default=0.6, help="Delay between titles")
    parser.add_argument("--dry-run", action="store_true", help="List targets only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()
    targets = list_books_missing_covers()
    if args.limit > 0:
        targets = targets[: args.limit]

    print(f"Missing covers: {len(targets)}")
    if args.dry_run:
        for book in targets:
            print(f"  - [{book['id']}] {book.get('title') or book['raw_title']}")
        return 0

    browser = make_browser_session()
    client = make_http_client()
    filled = 0
    try:
        for index, book in enumerate(targets, start=1):
            updated = repair_book_cover(
                book["id"],
                client=client,
                browser_session=browser,
            )
            has_cover = bool(updated and updated.get("cover_url"))
            if has_cover:
                filled += 1
            label = "cover" if has_cover else "miss"
            print(
                f"[{index}/{len(targets)}] {label}  "
                f"{book.get('title') or book['raw_title']!r}"
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

    remaining = len(list_books_missing_covers())
    print(f"Done. Filled {filled}. Still missing: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
