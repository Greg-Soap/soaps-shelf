from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import httpx
from bs4 import BeautifulSoup

from library.db import CACHE_DIR, ensure_dirs

OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
AETHON_SEARCH = "https://aethonbooks.com/"
NOVELUPDATES_FINDER = "https://www.novelupdates.com/series-finder/"
CHIKARI_SEARCH = "https://chikari.moe/api/search"
CHIKARI_NOVEL = "https://chikari.moe/api/novels/{slug}"
FREEWEBNOVEL_SEARCH = "https://freewebnovel.com/search"
FREEWEBNOVEL_ORIGIN = "https://freewebnovel.com"
ROYALROAD_SEARCH = "https://www.royalroad.com/fictions/search"
ROYALROAD_ORIGIN = "https://www.royalroad.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

FICTION_HINTS = {
    "fiction",
    "fantasy",
    "science fiction",
    "novels",
    "young adult",
    "litrpg",
    "lit rpg",
    "web novel",
    "cultivation",
    "progression",
    "xianxia",
    "xuanhuan",
    "wuxia",
    "gamelit",
}


@dataclass
class EnrichmentResult:
    title: str | None
    authors: str | None
    cover_url: str | None
    page_count: int | None
    first_publish_year: int | None
    subjects: str | None
    match_confidence: float
    needs_review: bool
    metadata_source: str | None = None
    synopsis: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def cache_path(prefix: str, query: str) -> Path:
    ensure_dirs()
    digest = hashlib.sha256(query.casefold().encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{prefix}_{digest}.json"


def load_cache(prefix: str, query: str) -> Any | None:
    path = cache_path(prefix, query)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_cache(prefix: str, query: str, payload: Any) -> None:
    cache_path(prefix, query).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_for_compare(text: str) -> str:
    text = text.casefold()
    text = text.replace("'", "").replace("'", "").replace("'", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_volume_suffix(text: str) -> str:
    return re.sub(r"\s+(\d+|book\s+\d+|vol\.?\s*\d+)$", "", text, flags=re.I).strip()


def title_similarity(query: str, candidate: str) -> float:
    from difflib import SequenceMatcher

    q = normalize_for_compare(query)
    c = normalize_for_compare(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0

    c_root = strip_volume_suffix(c)
    if q == c_root:
        return 0.92

    seq = SequenceMatcher(None, q, c).ratio()
    q_tokens = q.split()
    c_tokens = c.split()
    # Short titles ("Cradle") must not match "Cradle of Secrets"
    if len(q_tokens) <= 2:
        if c == q or c_root == q:
            return 1.0 if c == q else 0.92
        if c.startswith(q + " ") and len(c_tokens) <= len(q_tokens) + 1:
            return 0.8
        overlap = len(set(q_tokens) & set(c_tokens)) / len(set(q_tokens) | set(c_tokens))
        score = overlap if overlap >= 0.8 else overlap * 0.5
        return max(score, seq if seq >= 0.9 else 0.0)

    if q in c or c in q or q in c_root or c_root in q:
        return max(0.85, seq)
    if not q_tokens or not c_tokens:
        return seq if seq >= 0.9 else 0.0
    overlap = len(set(q_tokens) & set(c_tokens)) / len(set(q_tokens) | set(c_tokens))
    # Typo-tolerant: "Revered"≈"Reverend", "Omniscent"≈"Omniscient"
    return max(overlap, seq if seq >= 0.86 else 0.0)


def aethon_card_score(query: str, title: str, series: str) -> float:
    title_score = title_similarity(query, title)
    series_score = title_similarity(query, series) if series else 0.0
    score = max(title_score, series_score * 0.95)
    # Prefer the unnumbered series entry over "Title 17"
    if normalize_for_compare(title) == normalize_for_compare(query):
        score += 0.08
    elif strip_volume_suffix(normalize_for_compare(title)) == normalize_for_compare(query):
        if re.search(r"\d+$", normalize_for_compare(title)):
            score -= 0.05
    return score


def empty_result(needs_review: bool = True) -> EnrichmentResult:
    return EnrichmentResult(
        title=None,
        authors=None,
        cover_url=None,
        page_count=None,
        first_publish_year=None,
        subjects=None,
        match_confidence=0.0,
        needs_review=needs_review,
        metadata_source=None,
    )


def make_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
    )


def make_browser_session():
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    session = curl_requests.Session()
    return session


# --- chikari.moe (web novels) ----------------------------------------------

def search_chikari(query: str, client: httpx.Client | None = None) -> EnrichmentResult | None:
    cached = load_cache("chikari", query)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return EnrichmentResult(
            **{k: v for k, v in cached.items() if k != "raw"},
            raw=cached.get("raw") or {},
        )

    owns = client is None
    http = client or make_http_client()
    try:
        response = http.get(
            CHIKARI_SEARCH,
            params={"q": query, "include_novels": "true", "limit": 10},
        )
        if response.status_code != 200:
            save_cache("chikari", query, {"_miss": True})
            return None
        items = response.json()
        if not isinstance(items, list) or not items:
            save_cache("chikari", query, {"_miss": True})
            return None

        # Prefer novel medium over comic/manhwa adaptations
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            title = item.get("title") or ""
            score = title_similarity(query, title)
            medium = (item.get("medium") or item.get("type") or "").casefold()
            if medium == "novel":
                score += 0.08
            elif medium in {"comic", "manga", "manhwa", "manhua"}:
                score -= 0.05
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best = ranked[0]
        if best_score < 0.55:
            save_cache("chikari", query, {"_miss": True})
            return None

        slug = best.get("slug")
        detail = fetch_chikari_novel(slug, http) if slug else {}
        authors = detail.get("authors") or []
        if isinstance(authors, list):
            author_names = [
                item.get("name") if isinstance(item, dict) else str(item)
                for item in authors
            ]
            authors_text = ", ".join(name for name in author_names if name) or None
        else:
            authors_text = str(authors) if authors else None

        genres = [g.get("name") for g in (detail.get("genres") or []) if isinstance(g, dict)]
        tags = [t.get("name") for t in (detail.get("tags") or [])[:10] if isinstance(t, dict)]
        subjects = ", ".join([*genres, *tags]) or None
        synopsis = (detail.get("description") or "").strip() or None
        if synopsis and len(synopsis) > 1200:
            synopsis = synopsis[:1200].rsplit(" ", 1)[0] + "…"

        result = EnrichmentResult(
            title=detail.get("title") or best.get("title"),
            authors=authors_text,
            cover_url=detail.get("cover_url") or best.get("cover_url"),
            page_count=None,
            first_publish_year=detail.get("year"),
            subjects=subjects,
            match_confidence=min(best_score, 1.0),
            needs_review=best_score < 0.8,
            metadata_source="chikari",
            synopsis=synopsis,
            raw={"slug": slug, "search": best},
        )
        save_cache(
            "chikari",
            query,
            {
                "title": result.title,
                "authors": result.authors,
                "cover_url": result.cover_url,
                "page_count": result.page_count,
                "first_publish_year": result.first_publish_year,
                "subjects": result.subjects,
                "match_confidence": result.match_confidence,
                "needs_review": result.needs_review,
                "metadata_source": result.metadata_source,
                "synopsis": result.synopsis,
                "raw": result.raw,
            },
        )
        return result
    except Exception:
        save_cache("chikari", query, {"_miss": True})
        return None
    finally:
        if owns:
            http.close()


def fetch_chikari_novel(slug: str, client: httpx.Client) -> dict[str, Any]:
    try:
        response = client.get(CHIKARI_NOVEL.format(slug=slug))
        if response.status_code != 200:
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


# --- freewebnovel.com -------------------------------------------------------

def absolute_freewebnovel_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("/"):
        return FREEWEBNOVEL_ORIGIN + path
    return FREEWEBNOVEL_ORIGIN + "/" + path


def freewebnovel_search_candidates(query: str) -> list[str]:
    """Build search queries: exact title, then distinctive tokens for typo tolerance."""
    cleaned = re.sub(r"\s+", " ", query).strip()
    candidates = [cleaned]
    tokens = [t for t in re.findall(r"[A-Za-z0-9']+", cleaned) if len(t) >= 4]
    stop = {
        "novel", "book", "volume", "chapter", "the", "and", "with", "from",
        "class", "world", "story", "records", "record",
    }
    useful = [t for t in tokens if t.casefold() not in stop]
    if len(useful) >= 2:
        candidates.append(" ".join(useful[-2:]))
    if useful:
        # Longest distinctive token (e.g. Insanity, Omniscient-ish Viewpoint)
        longest = max(useful, key=len)
        if len(longest) >= 6:
            candidates.append(longest)
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def parse_freewebnovel_search_rows(html: str, query: str) -> list[tuple[float, str, str, str | None]]:
    soup = BeautifulSoup(html, "lxml")
    ranked: list[tuple[float, str, str, str | None]] = []
    for row in soup.select(".li-row"):
        link = row.select_one("h3.tit a, .tit a, a[href*='/novel/']")
        if not link:
            continue
        href = link.get("href") or ""
        if "/chapter-" in href or "/novel/" not in href:
            continue
        title = (
            link.get("title")
            or link.get_text(strip=True)
            or (row.select_one("img").get("alt") if row.select_one("img") else "")
        )
        if not title:
            continue
        score = title_similarity(query, title)
        img = row.select_one("img")
        cover = absolute_freewebnovel_url(img.get("src") if img else None)
        ranked.append((score, title, href, cover))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def search_freewebnovel(query: str, session=None) -> EnrichmentResult | None:
    cached = load_cache("fwn", query)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return EnrichmentResult(
            **{k: v for k, v in cached.items() if k != "raw"},
            raw=cached.get("raw") or {},
        )

    http = session or make_browser_session()
    if http is None:
        return None
    owns = session is None

    try:
        ranked: list[tuple[float, str, str, str | None]] = []
        for keyword in freewebnovel_search_candidates(query):
            response = http.get(
                FREEWEBNOVEL_SEARCH,
                params={"keyword": keyword},
                impersonate="chrome120",
                timeout=30,
                headers={"Referer": FREEWEBNOVEL_ORIGIN + "/"},
            )
            if response.status_code != 200:
                continue
            ranked.extend(parse_freewebnovel_search_rows(response.text, query))
            # Exact search already good enough
            if ranked and ranked[0][0] >= 0.85:
                break
            time.sleep(0.2)

        if not ranked:
            save_cache("fwn", query, {"_miss": True})
            return None

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best, best_href, best_cover = ranked[0]
        # Keep threshold fairly high — token fallback can otherwise latch onto
        # unrelated hits (e.g. "pursuit of time" → "Pursuit of the Truth").
        if best_score < 0.72:
            save_cache("fwn", query, {"_miss": True})
            return None

        detail = fetch_freewebnovel_detail(best_href, http)
        result = EnrichmentResult(
            title=detail.get("title") or best,
            authors=detail.get("authors"),
            cover_url=detail.get("cover_url") or best_cover,
            page_count=None,
            first_publish_year=None,
            subjects=detail.get("subjects"),
            match_confidence=min(best_score, 1.0),
            needs_review=best_score < 0.8,
            metadata_source="freewebnovel",
            synopsis=detail.get("synopsis"),
            raw={"href": best_href, "search_title": best},
        )
        save_cache(
            "fwn",
            query,
            {
                "title": result.title,
                "authors": result.authors,
                "cover_url": result.cover_url,
                "page_count": result.page_count,
                "first_publish_year": result.first_publish_year,
                "subjects": result.subjects,
                "match_confidence": result.match_confidence,
                "needs_review": result.needs_review,
                "metadata_source": result.metadata_source,
                "synopsis": result.synopsis,
                "raw": result.raw,
            },
        )
        return result
    except Exception:
        save_cache("fwn", query, {"_miss": True})
        return None
    finally:
        if owns and hasattr(http, "close"):
            try:
                http.close()
            except Exception:
                pass


def fetch_freewebnovel_detail(path: str, http) -> dict[str, Any]:
    url = absolute_freewebnovel_url(path)
    if not url:
        return {}
    try:
        response = http.get(url, impersonate="chrome120", timeout=30)
        if response.status_code != 200:
            return {}
    except Exception:
        return {}

    soup = BeautifulSoup(response.text, "lxml")
    out: dict[str, Any] = {}

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("@type") != "Book":
            continue
        out["title"] = data.get("name")
        authors = data.get("author") or []
        names: list[str] = []
        if isinstance(authors, dict):
            authors = [authors]
        if isinstance(authors, list):
            for author in authors:
                if isinstance(author, dict) and author.get("name"):
                    # Prefer latin / english-looking name first
                    name = str(author["name"]).strip()
                    if name:
                        names.append(name)
        if names:
            # Keep up to 2, prefer non-CJK if mixed
            latin = [n for n in names if re.search(r"[A-Za-z]", n)]
            out["authors"] = ", ".join((latin or names)[:2])
        genres = data.get("genre") or []
        if isinstance(genres, list):
            out["subjects"] = ", ".join(str(g) for g in genres if g)
        elif genres:
            out["subjects"] = str(genres)
        image = data.get("image")
        if isinstance(image, list) and image:
            out["cover_url"] = absolute_freewebnovel_url(str(image[0]))
        elif isinstance(image, str):
            out["cover_url"] = absolute_freewebnovel_url(image)
        synopsis = (data.get("description") or "").strip()
        if synopsis:
            out["synopsis"] = synopsis[:1200]
        break

    if not out.get("title"):
        h1 = soup.select_one("h1")
        if h1:
            out["title"] = h1.get_text(strip=True)
    if not out.get("cover_url"):
        og = soup.select_one("meta[property='og:image']")
        if og and og.get("content"):
            out["cover_url"] = absolute_freewebnovel_url(og["content"])
    if not out.get("synopsis"):
        og = soup.select_one("meta[property='og:description']")
        if og and og.get("content"):
            text = og["content"]
            text = re.sub(r"^Read .+? online for free\.\s*", "", text, flags=re.I)
            out["synopsis"] = text[:1200]
    return out


# --- Aethon Books -----------------------------------------------------------

def search_aethon(query: str, session=None) -> EnrichmentResult | None:
    cached = load_cache("aethon", query)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return EnrichmentResult(**{k: v for k, v in cached.items() if k != "raw"}, raw=cached.get("raw") or {})

    owns = session is None
    http = session or make_browser_session() or make_http_client()
    try:
        if hasattr(http, "get") and "curl_cffi" in type(http).__module__:
            response = http.get(
                AETHON_SEARCH,
                params={"s": query, "post_type": "product"},
                impersonate="chrome120",
                timeout=30,
            )
            html = response.text
            status = response.status_code
        else:
            response = http.get(AETHON_SEARCH, params={"s": query, "post_type": "product"})
            html = response.text
            status = response.status_code
        if status != 200:
            save_cache("aethon", query, {"_miss": True})
            return None

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article.mfb-card[data-mf-book-title]")
        if not cards:
            save_cache("aethon", query, {"_miss": True})
            return None

        best = None
        best_score = 0.0
        for card in cards:
            title = card.get("data-mf-book-title") or ""
            series_event = card.select_one("[data-mf-event]")
            series = ""
            if series_event and series_event.get("data-mf-event"):
                try:
                    series = json.loads(series_event["data-mf-event"]).get("series") or ""
                except json.JSONDecodeError:
                    series = ""
            score = aethon_card_score(query, title, series)
            if score > best_score:
                best_score = score
                best = card

        if not best or best_score < 0.55:
            save_cache("aethon", query, {"_miss": True})
            return None

        link_el = best.select_one("a.mfb-image, a.mfb-title, a[href*='/book/']")
        detail_url = None
        if link_el:
            detail_url = link_el.get("href") or link_el.get("data-mf-href")
        img = best.select_one("img")
        cover = img.get("src") if img else None
        card_title = best.get("data-mf-book-title") or ""
        series_event = best.select_one("[data-mf-event]")
        series_name = ""
        if series_event and series_event.get("data-mf-event"):
            try:
                series_name = json.loads(series_event["data-mf-event"]).get("series") or ""
            except json.JSONDecodeError:
                series_name = ""

        # Prefer canonical series title over "Title 17" when query is the series
        display_title = card_title
        if series_name and title_similarity(query, series_name) >= 0.92:
            display_title = series_name

        confidence = max(
            title_similarity(query, card_title),
            title_similarity(query, series_name) if series_name else 0.0,
        )

        # If we matched the series, open the series-root book page when present
        if series_name and title_similarity(query, series_name) >= 0.92:
            for card in cards:
                if normalize_for_compare(card.get("data-mf-book-title") or "") == normalize_for_compare(series_name):
                    root_link = card.select_one("a.mfb-image, a[href*='/book/']")
                    if root_link:
                        detail_url = root_link.get("href") or root_link.get("data-mf-href") or detail_url
                        root_img = card.select_one("img")
                        if root_img and root_img.get("src"):
                            cover = root_img["src"]
                    break

        detail = fetch_aethon_detail(detail_url, http) if detail_url else {}
        # Prefer series name / query over "Book One" product title when appropriate
        resolved_title = display_title
        if series_name and title_similarity(query, series_name) >= 0.92:
            resolved_title = series_name
        elif detail.get("title") and title_similarity(query, detail["title"]) >= 0.85:
            resolved_title = detail["title"]

        result = EnrichmentResult(
            title=resolved_title,
            authors=detail.get("authors"),
            cover_url=detail.get("cover_url") or cover,
            page_count=detail.get("page_count"),
            first_publish_year=detail.get("first_publish_year"),
            subjects=detail.get("subjects") or "LitRPG, Progression Fantasy",
            match_confidence=confidence,
            needs_review=confidence < 0.8,
            metadata_source="aethon",
            synopsis=detail.get("synopsis"),
            raw={"detail_url": detail_url, "card_title": card_title, "series": series_name},
        )
        save_cache(
            "aethon",
            query,
            {
                "title": result.title,
                "authors": result.authors,
                "cover_url": result.cover_url,
                "page_count": result.page_count,
                "first_publish_year": result.first_publish_year,
                "subjects": result.subjects,
                "match_confidence": result.match_confidence,
                "needs_review": result.needs_review,
                "metadata_source": result.metadata_source,
                "synopsis": result.synopsis,
                "raw": result.raw,
            },
        )
        return result
    except Exception:
        save_cache("aethon", query, {"_miss": True})
        return None
    finally:
        if owns and hasattr(http, "close"):
            http.close()


def fetch_aethon_detail(url: str, http) -> dict[str, Any]:
    try:
        if "curl_cffi" in type(http).__module__:
            response = http.get(url, impersonate="chrome120", timeout=30)
            html = response.text
            if response.status_code != 200:
                return {}
        else:
            response = http.get(url)
            if response.status_code != 200:
                return {}
            html = response.text
    except Exception:
        return {}

    soup = BeautifulSoup(html, "lxml")
    out: dict[str, Any] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "Book":
            out["title"] = data.get("name")
            author = data.get("author")
            if isinstance(author, dict):
                out["authors"] = author.get("name")
            elif isinstance(author, list):
                names = []
                for item in author:
                    if isinstance(item, dict) and item.get("name"):
                        names.append(item["name"])
                    elif isinstance(item, str):
                        names.append(item)
                out["authors"] = ", ".join(names) if names else None
            elif isinstance(author, str):
                out["authors"] = author
            out["synopsis"] = data.get("description")
            out["page_count"] = data.get("numberOfPages")
            image = data.get("image")
            if isinstance(image, list) and image:
                out["cover_url"] = image[0]
            elif isinstance(image, str):
                out["cover_url"] = image
            genre = data.get("genre")
            if isinstance(genre, list):
                out["subjects"] = ", ".join(genre)
            elif isinstance(genre, str):
                out["subjects"] = genre
            published = data.get("datePublished") or ""
            if isinstance(published, str) and len(published) >= 4 and published[:4].isdigit():
                out["first_publish_year"] = int(published[:4])
            break
    return out


# --- NovelUpdates -----------------------------------------------------------

def search_novelupdates(query: str, session=None) -> EnrichmentResult | None:
    cached = load_cache("nu", query)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return EnrichmentResult(**{k: v for k, v in cached.items() if k != "raw"}, raw=cached.get("raw") or {})

    http = session or make_browser_session()
    if http is None:
        return None

    try:
        http.get("https://www.novelupdates.com/series-finder/", impersonate="chrome120", timeout=30)
        response = http.get(
            NOVELUPDATES_FINDER,
            params={"sf": "1", "sh": query, "sort": "abc", "order": "asc"},
            impersonate="chrome120",
            timeout=30,
        )
        if response.status_code != 200 or "Just a moment" in response.text:
            save_cache("nu", query, {"_miss": True})
            return None

        soup = BeautifulSoup(response.text, "lxml")
        results = []
        for box in soup.select(".search_main_box_nu"):
            link = box.select_one(".search_title a[href*='/series/']")
            if not link:
                continue
            title = link.get_text(strip=True)
            score = title_similarity(query, title)
            if score < 0.55:
                continue
            img = box.select_one("img")
            genres = [a.get_text(strip=True) for a in box.select(".search_genre a, a[href*='?genre=']")[:12]]
            results.append(
                {
                    "title": title,
                    "url": link.get("href"),
                    "cover_url": img.get("src") if img else None,
                    "subjects": ", ".join(genres) if genres else None,
                    "score": score,
                }
            )

        if not results:
            # Fallback: slug guess pages are often CF-blocked; mark miss
            save_cache("nu", query, {"_miss": True})
            return None

        results.sort(key=lambda item: item["score"], reverse=True)
        best = results[0]
        detail = fetch_novelupdates_detail(best["url"], http) if best.get("url") else {}
        result = EnrichmentResult(
            title=detail.get("title") or best["title"],
            authors=detail.get("authors"),
            cover_url=detail.get("cover_url") or best.get("cover_url"),
            page_count=None,
            first_publish_year=detail.get("first_publish_year"),
            subjects=detail.get("subjects") or best.get("subjects"),
            match_confidence=best["score"],
            needs_review=best["score"] < 0.85,
            metadata_source="novelupdates",
            synopsis=detail.get("synopsis"),
            raw={"url": best.get("url")},
        )
        save_cache(
            "nu",
            query,
            {
                "title": result.title,
                "authors": result.authors,
                "cover_url": result.cover_url,
                "page_count": result.page_count,
                "first_publish_year": result.first_publish_year,
                "subjects": result.subjects,
                "match_confidence": result.match_confidence,
                "needs_review": result.needs_review,
                "metadata_source": result.metadata_source,
                "synopsis": result.synopsis,
                "raw": result.raw,
            },
        )
        return result
    except Exception:
        save_cache("nu", query, {"_miss": True})
        return None


def fetch_novelupdates_detail(url: str, http) -> dict[str, Any]:
    try:
        response = http.get(url, impersonate="chrome120", timeout=30)
        if response.status_code != 200 or "Just a moment" in response.text:
            return {}
    except Exception:
        return {}

    soup = BeautifulSoup(response.text, "lxml")
    out: dict[str, Any] = {}
    title_el = soup.select_one(".seriestitlenu")
    if title_el:
        out["title"] = title_el.get_text(strip=True)
    authors = [a.get_text(strip=True) for a in soup.select("#showauthors a")[:5]]
    if authors:
        out["authors"] = ", ".join(authors)
    genres = [a.get_text(strip=True) for a in soup.select("#seriesgenre a")[:12]]
    tags = [a.get_text(strip=True) for a in soup.select("#showtags a")[:8]]
    subjects = genres + tags
    if subjects:
        out["subjects"] = ", ".join(subjects)
    img = soup.select_one(".seriesimg img")
    if img and img.get("src"):
        out["cover_url"] = img["src"]
    syn = soup.select_one("#editdescription")
    if syn:
        out["synopsis"] = syn.get_text(" ", strip=True)[:1200]
    return out


# --- Open Library (strict) --------------------------------------------------

def subject_bonus(doc: dict[str, Any]) -> float:
    subjects = [str(item).casefold() for item in (doc.get("subject") or [])]
    if not subjects:
        return 0.0
    if any(any(hint in subject for hint in FICTION_HINTS) for subject in subjects):
        return 0.08
    return 0.0


def cover_url_from_doc(doc: dict[str, Any]) -> str | None:
    cover_id = doc.get("cover_i")
    if cover_id:
        return f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
    isbn_list = doc.get("isbn") or []
    if isbn_list:
        return f"https://covers.openlibrary.org/b/isbn/{isbn_list[0]}-L.jpg"
    return None


def search_open_library(query: str, client: httpx.Client | None = None) -> EnrichmentResult | None:
    cached = load_cache("ol", query)
    payload: dict[str, Any]
    if cached is not None:
        payload = cached
    else:
        owns = client is None
        http = client or make_http_client()
        try:
            response = http.get(OPEN_LIBRARY_SEARCH, params={"q": query, "limit": 10})
            response.raise_for_status()
            payload = response.json()
            save_cache("ol", query, payload)
        except Exception:
            return None
        finally:
            if owns:
                http.close()

    docs = payload.get("docs") or []
    if not docs:
        return None

    best = None
    best_score = 0.0
    for doc in docs[:10]:
        candidate = doc.get("title") or ""
        score = title_similarity(query, candidate)
        if doc.get("cover_i"):
            score += 0.03
        if doc.get("author_name"):
            score += 0.02
        score += subject_bonus(doc)
        if score > best_score:
            best_score = score
            best = doc

    if not best:
        return None

    confidence = title_similarity(query, best.get("title") or "")
    # Strict: reject weak / ambiguous conventional library hits for niche titles
    if confidence < 0.8:
        return None

    subjects = best.get("subject") or []
    subject_text = ", ".join(subjects[:12]) if subjects else ""
    has_fiction = any(any(hint in s.casefold() for hint in FICTION_HINTS) for s in subjects)
    exact_authors = {
        tuple((doc.get("author_name") or [])[:1])
        for doc in docs[:8]
        if title_similarity(query, doc.get("title") or "") >= 0.99
    }
    ambiguous = len(exact_authors) > 1
    # Ambiguous short/exact titles (e.g. Cradle) are worse than leaving blank
    if ambiguous:
        return None
    if not has_fiction and confidence < 0.95:
        return None

    author_names = best.get("author_name") or []
    authors = ", ".join(author_names[:5]) if author_names else None

    niche_hints = {"fantasy", "litrpg", "lit rpg", "cultivation", "xianxia", "web novel", "gamelit"}
    has_niche = any(any(hint in s.casefold() for hint in niche_hints) for s in subjects)
    # One-word titles ("Cradle") collide constantly in Open Library
    if len(normalize_for_compare(query).split()) <= 1 and not has_niche:
        return None

    return EnrichmentResult(
        title=best.get("title"),
        authors=authors,
        cover_url=cover_url_from_doc(best),
        page_count=best.get("number_of_pages_median") or best.get("number_of_pages"),
        first_publish_year=best.get("first_publish_year"),
        subjects=subject_text or None,
        match_confidence=confidence,
        needs_review=False if (authors and confidence >= 0.9 and has_fiction) else (not has_fiction),
        metadata_source="openlibrary",
        raw=best,
    )


def find_open_library_cover(
    query: str,
    *,
    authors: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """Looser Open Library cover lookup for repair passes (does not rewrite identity)."""
    owns = client is None
    http = client or make_http_client()
    try:
        search_q = query
        if authors:
            first_author = authors.split(",")[0].strip()
            if first_author:
                search_q = f"{query} {first_author}"
        response = http.get(OPEN_LIBRARY_SEARCH, params={"q": search_q, "limit": 12})
        response.raise_for_status()
        docs = response.json().get("docs") or []
    except Exception:
        return None
    finally:
        if owns:
            http.close()

    if not docs:
        return None

    author_needle = normalize_for_compare((authors or "").split(",")[0])
    ranked: list[tuple[float, dict[str, Any]]] = []
    for doc in docs:
        title = doc.get("title") or ""
        score = title_similarity(query, title)
        if score < 0.72:
            continue
        if not (doc.get("cover_i") or doc.get("isbn")):
            continue
        if author_needle:
            names = [normalize_for_compare(name) for name in (doc.get("author_name") or [])]
            if any(author_needle in name or name in author_needle for name in names if name):
                score += 0.2
            elif len(normalize_for_compare(query).split()) <= 2:
                # Short titles without author agreement are dangerous
                score -= 0.35
        ranked.append((score, doc))

    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best = ranked[0]
    if best_score < 0.8:
        return None
    cover = cover_url_from_doc(best)
    if not cover:
        return None
    return {
        "cover_url": cover,
        "page_count": best.get("number_of_pages_median") or best.get("number_of_pages"),
        "first_publish_year": best.get("first_publish_year"),
        "source": "openlibrary",
        "score": best_score,
    }


def find_cover_candidates(
    query: str,
    *,
    authors: str | None = None,
    client: httpx.Client | None = None,
    browser_session=None,
) -> dict[str, Any] | None:
    """Best-effort cover hunt across sources; prefers author-aware Open Library."""
    for hit in (
        search_aethon(query, session=browser_session),
        search_chikari(query, client=client),
        search_freewebnovel(query, session=browser_session),
        search_royalroad(query, session=browser_session),
    ):
        if hit and hit.cover_url and hit.match_confidence >= 0.72:
            return {
                "cover_url": hit.cover_url,
                "page_count": hit.page_count,
                "first_publish_year": hit.first_publish_year,
                "source": hit.metadata_source,
                "score": hit.match_confidence,
            }

    ol = find_open_library_cover(query, authors=authors, client=client)
    if ol:
        return ol

    # Series shorthand: try first known volume title when author is Will Wight / Cradle
    aliases = {
        "cradle": "Unsouled",
        "bobverse": "We Are Legion",
        "we are legion (we are bob)": "We Are Legion",
        "warformed: iron prince": "Iron Prince",
        "warformed": "Iron Prince",
    }
    alias = aliases.get(normalize_for_compare(query))
    if alias:
        return find_open_library_cover(alias, authors=authors, client=client)
    return None


# --- Royal Road -------------------------------------------------------------

def search_royalroad(query: str, session=None) -> EnrichmentResult | None:
    cached = load_cache("rr", query)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return EnrichmentResult(
            **{k: v for k, v in cached.items() if k != "raw"},
            raw=cached.get("raw") or {},
        )

    http = session or make_browser_session()
    if http is None:
        return None
    owns = session is None

    try:
        response = http.get(
            ROYALROAD_SEARCH,
            params={"title": query},
            impersonate="chrome120",
            timeout=45,
        )
        if response.status_code != 200 or "Just a moment" in response.text:
            save_cache("rr", query, {"_miss": True})
            return None

        soup = BeautifulSoup(response.text, "lxml")
        ranked: list[tuple[float, dict[str, Any]]] = []
        for item in soup.select(".fiction-list-item"):
            link = item.select_one("h2.fiction-title a, .fiction-title a")
            if not link:
                continue
            title = link.get_text(strip=True)
            href = link.get("href") or ""
            score = title_similarity(query, title)
            stats = item.select_one(".stats")
            stats_text = stats.get_text(" ", strip=True) if stats else ""
            followers = 0
            match = re.search(r"([\d,]+)\s+Followers", stats_text)
            if match:
                followers = int(match.group(1).replace(",", ""))
            img = item.select_one("img")
            cover = None
            if img:
                cover = img.get("data-src") or img.get("src")
            is_nocover = bool(cover and "nocover" in cover)
            if is_nocover:
                score -= 0.25
            # Tiny popularity boost; reject obvious stubs for short exact titles
            score += min(followers, 20000) / 200000
            if len(normalize_for_compare(query).split()) <= 2 and is_nocover and followers < 500:
                score -= 0.4
            tags = [t.get_text(strip=True) for t in item.select(".tags a, a.label")[:12]]
            ranked.append(
                (
                    score,
                    {
                        "title": title,
                        "href": href,
                        "cover": cover,
                        "followers": followers,
                        "tags": tags,
                        "is_nocover": is_nocover,
                    },
                )
            )

        if not ranked:
            save_cache("rr", query, {"_miss": True})
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score, best = ranked[0]
        if best_score < 0.72 or best.get("is_nocover"):
            # Allow nocover only if extremely strong title + popularity
            if not (best_score >= 0.95 and best.get("followers", 0) >= 2000):
                save_cache("rr", query, {"_miss": True})
                return None

        detail = fetch_royalroad_detail(best["href"], http)
        cover = detail.get("cover_url") or absolute_url(ROYALROAD_ORIGIN, best.get("cover"))
        if cover and "nocover" in cover:
            cover = None
        synopsis = detail.get("synopsis")
        if synopsis:
            synopsis = BeautifulSoup(synopsis, "lxml").get_text(" ", strip=True)[:1200]

        result = EnrichmentResult(
            title=detail.get("title") or best["title"],
            authors=detail.get("authors"),
            cover_url=cover,
            page_count=None,
            first_publish_year=None,
            subjects=", ".join(detail.get("tags") or best.get("tags") or []) or "Progression Fantasy, LitRPG",
            match_confidence=min(best_score, 1.0),
            needs_review=best_score < 0.85,
            metadata_source="royalroad",
            synopsis=synopsis,
            raw={"href": best.get("href"), "followers": best.get("followers")},
        )
        save_cache(
            "rr",
            query,
            {
                "title": result.title,
                "authors": result.authors,
                "cover_url": result.cover_url,
                "page_count": result.page_count,
                "first_publish_year": result.first_publish_year,
                "subjects": result.subjects,
                "match_confidence": result.match_confidence,
                "needs_review": result.needs_review,
                "metadata_source": result.metadata_source,
                "synopsis": result.synopsis,
                "raw": result.raw,
            },
        )
        return result
    except Exception:
        save_cache("rr", query, {"_miss": True})
        return None
    finally:
        if owns and hasattr(http, "close"):
            try:
                http.close()
            except Exception:
                pass


def absolute_url(origin: str, path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("/"):
        return origin + path
    return origin + "/" + path


def fetch_royalroad_detail(path: str, http) -> dict[str, Any]:
    url = absolute_url(ROYALROAD_ORIGIN, path)
    if not url:
        return {}
    try:
        response = http.get(url, impersonate="chrome120", timeout=45)
        if response.status_code != 200:
            return {}
    except Exception:
        return {}

    soup = BeautifulSoup(response.text, "lxml")
    out: dict[str, Any] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("@type") not in {"Book", "Novel", "CreativeWork"}:
            continue
        out["title"] = data.get("name")
        author = data.get("author")
        if isinstance(author, dict):
            out["authors"] = author.get("name")
        elif isinstance(author, list):
            names = [a.get("name") for a in author if isinstance(a, dict) and a.get("name")]
            out["authors"] = ", ".join(names[:3]) if names else None
        elif isinstance(author, str):
            out["authors"] = author
        image = data.get("image")
        if isinstance(image, list) and image:
            out["cover_url"] = absolute_url(ROYALROAD_ORIGIN, str(image[0]))
        elif isinstance(image, str):
            out["cover_url"] = absolute_url(ROYALROAD_ORIGIN, image)
        out["synopsis"] = data.get("description")
        break

    if not out.get("authors"):
        author_el = soup.select_one("h4 a[href*='/profile/'], .fiction-info h4 a")
        if author_el:
            text = author_el.get_text(strip=True)
            out["authors"] = re.sub(r"^by\s+", "", text, flags=re.I)
    if not out.get("cover_url"):
        og = soup.select_one("meta[property='og:image']")
        if og and og.get("content") and "nocover" not in og["content"]:
            out["cover_url"] = absolute_url(ROYALROAD_ORIGIN, og["content"])
    tags = [a.get_text(strip=True) for a in soup.select(".tags a, span.tags a")[:12]]
    if tags:
        out["tags"] = tags
    return out


# --- Orchestrator -----------------------------------------------------------

def enrich_title(
    query: str,
    client: httpx.Client | None = None,
    browser_session=None,
    *,
    use_llm: bool = False,
) -> EnrichmentResult:
    """Aethon → chikari → freewebnovel → royalroad → NovelUpdates → Open Library → LLM."""
    query = query.strip()
    if not query:
        return empty_result()

    owns_client = client is None
    owns_browser = browser_session is None
    http = client or make_http_client()
    browser = browser_session or make_browser_session()

    try:
        aethon = search_aethon(query, session=browser)
        if aethon and aethon.match_confidence >= 0.55:
            return aethon

        chikari = search_chikari(query, client=http)
        if chikari and chikari.match_confidence >= 0.55:
            return chikari

        fwn = search_freewebnovel(query, session=browser)
        if fwn and fwn.match_confidence >= 0.55:
            return fwn

        rr = search_royalroad(query, session=browser)
        if rr and rr.match_confidence >= 0.72:
            return rr

        time.sleep(0.35)
        nu = search_novelupdates(query, session=browser)
        if nu and nu.match_confidence >= 0.55:
            return nu

        ol = search_open_library(query, client=http)
        if ol:
            return ol

        if use_llm:
            from library.llm_enrich import enrich_with_llm

            return enrich_with_llm(
                query,
                client=http,
                browser_session=browser,
            )
    finally:
        if owns_client:
            http.close()
        if owns_browser and browser is not None and hasattr(browser, "close"):
            try:
                browser.close()
            except Exception:
                pass

    # Keep the user's title — do not invent wrong conventional-library metadata
    return EnrichmentResult(
        title=query,
        authors=None,
        cover_url=None,
        page_count=None,
        first_publish_year=None,
        subjects=None,
        match_confidence=0.0,
        needs_review=True,
        metadata_source=None,
        synopsis=None,
    )
