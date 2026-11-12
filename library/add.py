"""CLI: python -m library.add "Cradle book 1" --status read"""

from __future__ import annotations

import argparse
import json
import sys

from library.books import add_book


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Add a book to the library")
    parser.add_argument("title", help="Book title (rough titles are fine)")
    parser.add_argument(
        "--status",
        default="read",
        choices=["read", "reading", "want_to_read", "dropped", "not_finished", "other"],
        help="Reading status (default: read — for the future bot flow)",
    )
    parser.add_argument(
        "--source",
        default="cli",
        help="Source label stored on the row",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip Open Library enrichment",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    book = add_book(
        args.title,
        status=args.status,
        source=args.source,
        enrich=not args.no_enrich,
    )
    print(json.dumps(book, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
