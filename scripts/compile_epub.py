#!/usr/bin/env python3
"""Compile a web fiction URL into an EPUB for Prestigio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.compiler.service import compile_source_url, list_adapters
from library.db import init_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile fiction URL → EPUB")
    parser.add_argument("url", nargs="?", help="Fiction URL (WebToEpub-supported)")
    parser.add_argument("--status", default="want_to_read", help="Library status")
    parser.add_argument("--from", dest="chapter_from", type=int, default=0)
    parser.add_argument("--to", dest="chapter_to", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0, help="Max chapters (0 = all)")
    parser.add_argument("--delay", type=float, default=0.55)
    parser.add_argument("--list-adapters", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()

    if args.list_adapters:
        print(json.dumps(list_adapters(), indent=2))
        return 0
    if not args.url:
        build_parser().error("url is required unless --list-adapters")

    limit = args.limit if args.limit > 0 else None
    print(f"Compiling {args.url} …")
    result = compile_source_url(
        args.url,
        status=args.status,
        chapter_from=args.chapter_from,
        chapter_to=args.chapter_to,
        limit=limit,
        delay=args.delay,
        sync=True,
    )
    print(
        f"OK · {result['title']!r} by {result.get('authors') or '?'} · "
        f"{result['chapter_count']} chapters"
    )
    print(f"EPUB · {result['epub_path']}")
    if result.get("book"):
        print(f"Book id · {result['book']['id']} · pipeline={result['book'].get('pipeline_status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
