"""Book library core: ingest, enrich, and shared add_book API."""

from library.books import add_book, get_book, list_books

__all__ = ["add_book", "get_book", "list_books"]
