"""Build a Prestigio-friendly EPUB from scraped chapters."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import httpx
from ebooklib import epub

from library.compiler.models import ChapterContent, FictionMeta
from library.db import EPUB_DIR, ensure_dirs


def slugify_filename(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    slug = slug.strip("._") or "book"
    return slug[:80]


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _download_cover(url: str | None) -> tuple[bytes, str] | None:
    if not url:
        return None
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
            data = response.content
            if not data:
                return None
            ext = "jpg"
            if "png" in content_type:
                ext = "png"
            elif "webp" in content_type:
                ext = "webp"
            elif "gif" in content_type:
                ext = "gif"
            return data, ext
    except Exception:
        return None


def build_epub(
    meta: FictionMeta,
    chapters: Iterable[ChapterContent],
    *,
    output_path: Path | None = None,
) -> Path:
    ensure_dirs()
    chapter_list = list(chapters)
    if not chapter_list:
        raise ValueError("No chapters to package")

    book = epub.EpubBook()
    identifier = meta.source_url or meta.title
    book.set_identifier(identifier)
    book.set_title(meta.title)
    book.set_language("en")
    if meta.authors:
        book.add_author(meta.authors)
    if meta.subjects:
        for tag in [part.strip() for part in meta.subjects.split(",") if part.strip()][:12]:
            book.add_metadata("DC", "subject", tag)
    if meta.synopsis:
        book.add_metadata("DC", "description", meta.synopsis)
    if meta.source_url:
        book.add_metadata("DC", "source", meta.source_url)

    cover = _download_cover(meta.cover_url)
    if cover:
        data, ext = cover
        book.set_cover(f"cover.{ext}", data)

    style = """
    body { font-family: serif; line-height: 1.5; }
    h1 { margin: 1.2em 0 0.6em; }
    p { margin: 0.6em 0; }
    img { max-width: 100%; height: auto; }
    """
    nav_css = epub.EpubItem(
        uid="style_nav",
        file_name="style/nav.css",
        media_type="text/css",
        content=style.encode("utf-8"),
    )
    book.add_item(nav_css)

    spine_items: list[Any] = ["nav"]
    toc_items = []

    if meta.synopsis:
        intro = epub.EpubHtml(
            title="Description",
            file_name="desc.xhtml",
            lang="en",
        )
        paragraphs = "".join(
            f"<p>{_escape(part)}</p>" for part in meta.synopsis.split("\n") if part.strip()
        )
        intro.content = f"<h1>Description</h1>{paragraphs}"
        intro.add_item(nav_css)
        book.add_item(intro)
        spine_items.append(intro)
        toc_items.append(intro)

    for chapter in chapter_list:
        item = epub.EpubHtml(
            title=chapter.title,
            file_name=f"chap_{chapter.index + 1:04d}.xhtml",
            lang="en",
        )
        body = chapter.html.strip() or f"<p>{_escape(chapter.title)}</p>"
        item.content = f"<h1>{_escape(chapter.title)}</h1>\n{body}"
        item.add_item(nav_css)
        book.add_item(item)
        spine_items.append(item)
        toc_items.append(item)

    book.toc = tuple(toc_items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_items

    if output_path is None:
        fiction_id = ""
        match = re.search(r"/fiction/(\d+)", meta.source_url or "")
        if match:
            fiction_id = match.group(1) + "_"
        filename = f"{fiction_id}{slugify_filename(meta.title)}.epub"
        output_path = EPUB_DIR / filename
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    epub.write_epub(str(output_path), book, {})
    return output_path
