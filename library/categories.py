from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from library.db import get_connection, init_db


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug or "category"


def list_categories(db_path: Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(bc.book_id) AS book_count
            FROM categories c
            LEFT JOIN book_categories bc ON bc.category_id = c.id
            GROUP BY c.id
            ORDER BY lower(c.name)
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def get_category(category_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT c.*, COUNT(bc.book_id) AS book_count
            FROM categories c
            LEFT JOIN book_categories bc ON bc.category_id = c.id
            WHERE c.id = ?
            GROUP BY c.id
            """,
            (category_id,),
        ).fetchone()
        return row_to_dict(row) if row else None


def create_category(
    name: str,
    *,
    description: str | None = None,
    color: str | None = None,
    slug: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    clean = name.strip()
    if not clean:
        raise ValueError("name is required")
    slug_value = slugify(slug or clean)
    init_db(db_path)
    with get_connection(db_path) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO categories (name, slug, description, color)
                VALUES (?, ?, ?, ?)
                """,
                (clean, slug_value, (description or "").strip() or None, color),
            )
            conn.commit()
            category_id = cursor.lastrowid
        except sqlite3.IntegrityError as err:
            raise ValueError(f"Category already exists: {clean}") from err
    category = get_category(int(category_id), db_path=db_path)
    assert category is not None
    return category


def update_category(
    category_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    color: str | None = None,
    slug: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    init_db(db_path)
    current = get_category(category_id, db_path=db_path)
    if not current:
        return None

    next_name = name.strip() if name is not None else current["name"]
    if not next_name:
        raise ValueError("name is required")
    next_slug = slugify(slug) if slug is not None else (
        slugify(next_name) if name is not None else current["slug"]
    )
    next_description = (
        description.strip() if description is not None else current.get("description")
    )
    next_color = color if color is not None else current.get("color")

    with get_connection(db_path) as conn:
        try:
            conn.execute(
                """
                UPDATE categories
                SET name = ?, slug = ?, description = ?, color = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (next_name, next_slug, next_description or None, next_color, category_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as err:
            raise ValueError("Category name or slug already exists") from err
    return get_category(category_id, db_path=db_path)


def delete_category(category_id: int, db_path: Path | None = None) -> bool:
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        return cursor.rowcount > 0


def set_book_categories(
    book_id: int,
    category_ids: list[int],
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    unique_ids = sorted({int(item) for item in category_ids})
    with get_connection(db_path) as conn:
        book = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book:
            raise ValueError("Book not found")
        conn.execute("DELETE FROM book_categories WHERE book_id = ?", (book_id,))
        for category_id in unique_ids:
            exists = conn.execute(
                "SELECT id FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if not exists:
                raise ValueError(f"Category not found: {category_id}")
            conn.execute(
                "INSERT INTO book_categories (book_id, category_id) VALUES (?, ?)",
                (book_id, category_id),
            )
        conn.commit()
    return list_book_categories(book_id, db_path=db_path)


def list_book_categories(book_id: int, db_path: Path | None = None) -> list[dict[str, Any]]:
    init_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.*
            FROM categories c
            JOIN book_categories bc ON bc.category_id = c.id
            WHERE bc.book_id = ?
            ORDER BY lower(c.name)
            """,
            (book_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]
