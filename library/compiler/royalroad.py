"""Royal Road fiction → chapter list + clean HTML (WebToEpub-inspired)."""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from library.compiler.models import ChapterContent, ChapterRef, FictionMeta
from library.enrich import ROYALROAD_ORIGIN, absolute_url, make_browser_session

CHAPTERS_RE = re.compile(
    r"window\.chapters\s*=\s*(\[[\s\S]*?\]);",
    re.IGNORECASE,
)
FICTION_PATH_RE = re.compile(r"^(/fiction/\d+(?:/[^/]+)?)", re.IGNORECASE)


def normalize_fiction_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        url = "https://" + url.strip()
        parsed = urlparse(url)
    match = re.match(
        r"^(/fiction/\d+(?:/[^/]+)?)(?:/chapter/\d+(?:/[^/]*)?)?/?$",
        parsed.path,
        flags=re.I,
    )
    path = match.group(1) if match else parsed.path.rstrip("/")
    return f"https://www.royalroad.com{path}"


def can_handle(url: str) -> bool:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.casefold()
    host = host.removeprefix("www.")
    return host in {"royalroad.com", "royalroadl.com"}


def _fetch_html(url: str, session=None) -> str:
    http = session or make_browser_session()
    if http is None:
        raise RuntimeError("curl_cffi is required for Royal Road scraping")
    response = http.get(url, impersonate="chrome120", timeout=45)
    text = response.text or ""
    if response.status_code != 200 or "Just a moment" in text or "Making sure you're not a bot" in text:
        raise RuntimeError(f"Royal Road blocked or failed ({response.status_code}) for {url}")
    return text


def _chapters_from_window(html: str, base_url: str) -> list[ChapterRef]:
    match = CHAPTERS_RE.search(html)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    fiction_path = urlparse(base_url).path.rstrip("/")
    chapters: list[ChapterRef] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"Chapter {index + 1}").strip()
        raw_url = item.get("url")
        if raw_url:
            href = urljoin(base_url, str(raw_url))
        elif item.get("id") is not None:
            slug = item.get("slug") or ""
            href = urljoin(base_url, f"{fiction_path}/chapter/{item['id']}/{slug}")
        else:
            continue
        chapters.append(ChapterRef(index=index, title=title, url=href))
    return chapters


def _chapters_from_table(soup: BeautifulSoup, base_url: str) -> list[ChapterRef]:
    table = soup.select_one("table#chapters")
    if not table:
        return []
    chapters: list[ChapterRef] = []
    for index, link in enumerate(table.select("tbody tr td:first-child a[href*='/chapter/']")):
        href = absolute_url(ROYALROAD_ORIGIN, link.get("href"))
        if not href:
            continue
        title = link.get_text(" ", strip=True) or f"Chapter {index + 1}"
        chapters.append(ChapterRef(index=index, title=title, url=href))
    return chapters


def _extract_meta(html: str, soup: BeautifulSoup, source_url: str) -> FictionMeta:
    title = None
    header = soup.select_one("div.fic-header h1, h1")
    if header:
        title = header.get_text(strip=True)
    if not title:
        og = soup.select_one("meta[property='og:title']")
        title = og.get("content") if og else None
    title = (title or "Untitled Royal Road Fiction").strip()

    authors = None
    author_link = soup.select_one("div.fic-header a[href^='/profile/']")
    if author_link and author_link.get_text(strip=True):
        authors = author_link.get_text(strip=True)
    if not authors:
        meta_author = soup.select_one("meta[property='books:author']")
        if meta_author and meta_author.get("content"):
            authors = meta_author["content"].strip()

    genres = [
        a.get_text(strip=True)
        for a in soup.select("a.fiction-tag, a[href*='tagsAdd=']")
        if a.get_text(strip=True)
    ]
    genres = list(dict.fromkeys(genres))

    synopsis = None
    desc = soup.select_one("div.fiction-info div.description, div.description")
    if desc:
        synopsis = desc.get_text("\n", strip=True)[:4000] or None
    if not synopsis:
        og = soup.select_one("meta[property='og:description'], meta[name='description']")
        if og and og.get("content"):
            synopsis = og["content"].strip()

    cover = None
    og_image = soup.select_one("meta[property='og:image'], meta[name='twitter:image']")
    if og_image and og_image.get("content") and "nocover" not in og_image["content"]:
        cover = og_image["content"].strip()
    if not cover:
        img = soup.select_one("img.thumbnail, img[data-type='cover']")
        if img:
            cover = absolute_url(ROYALROAD_ORIGIN, img.get("data-src") or img.get("src"))

    chapters = _chapters_from_window(html, source_url)
    if not chapters:
        chapters = _chapters_from_table(soup, source_url)

    return FictionMeta(
        title=title,
        authors=authors,
        synopsis=synopsis,
        cover_url=cover,
        subjects=", ".join(genres) if genres else None,
        source_url=source_url,
        adapter="royalroad",
        chapters=chapters,
    )


def fetch_fiction_meta(url: str, session=None) -> FictionMeta:
    fiction_url = normalize_fiction_url(url)
    html = _fetch_html(fiction_url, session=session)
    soup = BeautifulSoup(html, "lxml")
    meta = _extract_meta(html, soup, fiction_url)
    if not meta.chapters:
        raise RuntimeError(f"No chapters found for {fiction_url}")
    return meta


def _clean_chapter_html(soup: BeautifulSoup) -> str:
    # Prefer chapter-inner parent (WebToEpub approach), then legacy wrappers
    inner = soup.select_one("div.chapter-inner")
    content: Tag | None
    if inner and inner.parent and isinstance(inner.parent, Tag):
        content = inner.parent
    else:
        content = soup.select_one("div.portlet-body") or soup.select_one(".page-content-wrapper")

    if content is None:
        body = soup.body
        return body.decode_contents() if body else str(soup)

    # Drop author notes / chrome
    for selector in (
        "div.author-note-portlet",
        "div.author-note-card",
        "div.author-note",
        "nav",
        "script",
        "style",
        "iframe",
        "button",
        "form",
    ):
        for node in content.select(selector):
            node.decompose()

    for anchor in content.select("a[href*='royalroad.com'], a[href*='royalroadl.com']"):
        anchor.unwrap()

    # Keep chapter-inner / headings mainly
    kept: list[Tag] = []
    for child in list(content.children):
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                kept.append(BeautifulSoup(f"<p>{text}</p>", "lxml").p)  # type: ignore[arg-type]
            continue
        if not isinstance(child, Tag):
            continue
        tag = child.name.casefold()
        class_name = " ".join(child.get("class") or [])
        if tag == "h1" or tag == "h2":
            kept.append(child)
        elif tag == "div" and (
            class_name.startswith("chapter-inner")
            or "page-content" in class_name
        ):
            kept.append(child)

    if kept:
        parts = []
        for node in kept:
            parts.append(str(node))
        return "\n".join(parts)

    return content.decode_contents()


def fetch_chapter(chapter: ChapterRef, session=None) -> ChapterContent:
    html = _fetch_html(chapter.url, session=session)
    soup = BeautifulSoup(html, "lxml")
    cleaned = _clean_chapter_html(soup)
    title = chapter.title
    heading = soup.select_one("h1") or soup.select_one("h2")
    if heading and heading.get_text(strip=True):
        # Prefer list title; keep page heading only if list title is placeholder-ish
        if not title or title == "[placeholder]":
            title = heading.get_text(strip=True)
    return ChapterContent(
        index=chapter.index,
        title=title,
        url=chapter.url,
        html=cleaned,
    )


def fetch_chapters(
    meta: FictionMeta,
    *,
    chapter_from: int = 0,
    chapter_to: int | None = None,
    delay: float = 0.55,
    session=None,
    limit: int | None = None,
) -> list[ChapterContent]:
    owns = session is None
    http = session or make_browser_session()
    if http is None:
        raise RuntimeError("curl_cffi is required for Royal Road scraping")

    chapters = meta.chapters[chapter_from:]
    if chapter_to is not None:
        chapters = meta.chapters[chapter_from : chapter_to + 1]
    if limit is not None and limit > 0:
        chapters = chapters[:limit]

    out: list[ChapterContent] = []
    try:
        for index, chapter in enumerate(chapters):
            out.append(fetch_chapter(chapter, session=http))
            if index < len(chapters) - 1 and delay > 0:
                time.sleep(delay)
    finally:
        if owns and hasattr(http, "close"):
            try:
                http.close()
            except Exception:
                pass
    return out
