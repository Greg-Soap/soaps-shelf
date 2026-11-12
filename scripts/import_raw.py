#!/usr/bin/env python3
"""Import titles from data/raw/*.pdf (or *.txt paste fallback) into SQLite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.books import add_book, count_by_status
from library.db import RAW_DIR, init_db
from library.ingest import STATUS_BY_STEM, parse_raw_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import To Do PDF/txt exports")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=RAW_DIR,
        help="Directory containing 1.pdf / 1.txt etc.",
    )
    parser.add_argument(
        "--status-map",
        type=str,
        default="",
        help='JSON map of stem→status, e.g. \'{"1":"read","2":"reading"}\'',
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Import titles only; enrich later with scripts/enrich_pending.py",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print samples without writing to the DB",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    status_map = dict(STATUS_BY_STEM)
    if args.status_map:
        status_map.update(json.loads(args.status_map))

    titles, warnings = parse_raw_dir(args.raw_dir, status_map=status_map)

    print(f"Parsed {len(titles)} titles from {args.raw_dir}")
    for warning in warnings:
        print(f"WARNING: {warning}")

    by_status: dict[str, list[str]] = {}
    for item in titles:
        by_status.setdefault(item.status, []).append(item.title)

    for status, items in sorted(by_status.items()):
        print(f"\n[{status}] {len(items)} titles — sample:")
        for title in items[:8]:
            print(f"  - {title}")
        if len(items) > 8:
            print(f"  … +{len(items) - 8} more")

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0

    init_db()
    enrich = not args.no_enrich
    for index, item in enumerate(titles, start=1):
        add_book(
            item.title,
            status=item.status,
            source=item.source,
            enrich=enrich,
        )
        if index % 10 == 0 or index == len(titles):
            print(f"Imported {index}/{len(titles)}")

    print("\nCounts by status:")
    for status, count in sorted(count_by_status().items()):
        print(f"  {status}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
