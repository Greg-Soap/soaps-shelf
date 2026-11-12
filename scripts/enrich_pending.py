#!/usr/bin/env python3
"""Enrich books via Aethon → NovelUpdates → strict Open Library."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.books import apply_enrichment_to_book, list_pending_enrichment, reset_metadata
from library.db import init_db
from library.enrich import enrich_title, make_browser_session, make_http_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich pending books")
    parser.add_argument("--limit", type=int, default=0, help="Max books (0 = all)")
    parser.add_argument("--delay", type=float, default=0.8, help="Delay between titles")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear existing metadata first (fixes bad Open Library matches)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-enrich every book, not only pending/review/openlibrary rows",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()

    if args.reset:
        cleared = reset_metadata()
        print(f"Reset metadata on {cleared} books")

    pending = list_pending_enrichment(force=args.force or args.reset)
    if args.limit > 0:
        pending = pending[: args.limit]

    print(f"Enriching {len(pending)} books…")
    browser = make_browser_session()
    client = make_http_client()
    try:
        for index, book in enumerate(pending, start=1):
            result = enrich_title(
                book["raw_title"],
                client=client,
                browser_session=browser,
            )
            apply_enrichment_to_book(book["id"], result)
            flag = "REVIEW" if result.needs_review else "ok"
            source = result.metadata_source or "none"
            display = result.title or book["raw_title"]
            print(
                f"[{index}/{len(pending)}] {flag}/{source}  "
                f"{book['raw_title']!r} → {display!r} "
                f"(confidence={result.match_confidence:.2f})"
            )
            if index < len(pending):
                time.sleep(args.delay)
    finally:
        client.close()
        if browser is not None and hasattr(browser, "close"):
            try:
                browser.close()
            except Exception:
                pass

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
