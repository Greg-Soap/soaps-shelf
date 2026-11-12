from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from library.enrich import (
    EnrichmentResult,
    load_cache,
    save_cache,
    search_aethon,
    search_chikari,
    search_freewebnovel,
    search_open_library,
    search_royalroad,
)

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def available_llm_provider() -> str | None:
    load_dotenv()
    if gemini_api_key():
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


SYSTEM_PROMPT = """You catalog LitRPG, progression fantasy, cultivation, xianxia, and web novels.
The user gives a rough title that may include typos, series shorthand, or multiple titles.
Return ONLY valid JSON with this shape:
{
  "known": true,
  "title": "Canonical English title",
  "authors": "Primary author or pen name",
  "genres": ["LitRPG", "Progression Fantasy"],
  "synopsis": "Two short spoiler-light sentences.",
  "confidence": 0.0
}
Rules:
- If you are not reasonably sure this is a real published/serial story, set known=false, confidence<=0.3, and leave authors empty.
- Prefer the commonly used English title.
- Do not invent authors. If unsure of the author, leave authors as "".
- confidence is 0-1 for how sure you are that title+author are correct.
- genres should be short tags from: LitRPG, Progression Fantasy, Cultivation, Xianxia, Xuanhuan, Wuxia, System, Apocalypse, Isekai, Fantasy, Sci-Fi, Romance, Action.
"""


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def call_openai(query: str, client: httpx.Client) -> dict[str, Any]:
    api_key = os.environ["OPENAI_API_KEY"]
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    response = client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Rough title from my reading list: {query}",
                },
            ],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return extract_json(content)


def call_anthropic(query: str, client: httpx.Client) -> dict[str, Any]:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    response = client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 700,
            "temperature": 0.1,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": f"Rough title from my reading list: {query}",
                }
            ],
        },
        timeout=60.0,
    )
    response.raise_for_status()
    content = response.json()["content"][0]["text"]
    return extract_json(content)


def call_gemini(query: str, client: httpx.Client) -> dict[str, Any]:
    import time

    api_key = gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY missing")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": f"Rough title from my reading list: {query}"}
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    last_error: Exception | None = None
    for attempt in range(5):
        response = client.post(
            url,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=60.0,
        )
        if response.status_code == 429:
            wait = 8 * (attempt + 1)
            time.sleep(wait)
            last_error = httpx.HTTPStatusError(
                f"429 Too Many Requests (retry {attempt + 1})",
                request=response.request,
                response=response,
            )
            continue
        response.raise_for_status()
        payload = response.json()
        content = payload["candidates"][0]["content"]["parts"][0]["text"]
        return extract_json(content)
    assert last_error is not None
    raise last_error


def call_llm(provider: str, query: str, client: httpx.Client) -> dict[str, Any]:
    if provider == "gemini":
        return call_gemini(query, client)
    if provider == "openai":
        return call_openai(query, client)
    if provider == "anthropic":
        return call_anthropic(query, client)
    raise RuntimeError(f"Unknown LLM provider: {provider}")


def enrich_with_llm(
    query: str,
    *,
    client: httpx.Client | None = None,
    browser_session=None,
) -> EnrichmentResult:
    load_dotenv()
    provider = available_llm_provider()
    if not provider:
        raise RuntimeError(
            "No LLM API key found. Add GEMINI_API_KEY (or GOOGLE_API_KEY), "
            "OPENAI_API_KEY, or ANTHROPIC_API_KEY to .env"
        )

    cached = load_cache("llm", query)
    if cached is not None:
        return EnrichmentResult(**{k: v for k, v in cached.items() if k != "raw"}, raw=cached.get("raw") or {})

    owns = client is None
    http = client or httpx.Client(timeout=60.0)
    try:
        payload = call_llm(provider, query, http)
    finally:
        if owns:
            http.close()

    known = bool(payload.get("known"))
    confidence = float(payload.get("confidence") or 0.0)
    title = (payload.get("title") or query).strip() or query
    authors = (payload.get("authors") or "").strip() or None
    genres = payload.get("genres") or []
    if isinstance(genres, str):
        subjects = genres
    else:
        subjects = ", ".join(str(item) for item in genres if item) or None
    synopsis = (payload.get("synopsis") or "").strip() or None

    if not known or confidence < 0.55 or not authors:
        result = EnrichmentResult(
            title=title if known else query,
            authors=authors,
            cover_url=None,
            page_count=None,
            first_publish_year=None,
            subjects=subjects,
            match_confidence=confidence,
            needs_review=True,
            metadata_source="llm" if known else None,
            synopsis=synopsis,
            raw={"provider": provider, "payload": payload},
        )
    else:
        cover_url = None
        page_count = None
        year = None
        # Try to grab a cover with the corrected title
        try:
            cover_client = None if owns else http
            candidates = [
                search_aethon(title, session=browser_session),
                search_chikari(title, client=cover_client),
                search_freewebnovel(title, session=browser_session),
                search_royalroad(title, session=browser_session),
                search_open_library(title, client=cover_client),
            ]
            for hit in candidates:
                if not hit or hit.match_confidence < 0.7:
                    continue
                if hit.cover_url and not cover_url:
                    cover_url = hit.cover_url
                if hit.page_count and not page_count:
                    page_count = hit.page_count
                if hit.first_publish_year and not year:
                    year = hit.first_publish_year
                if hit.synopsis and not synopsis:
                    synopsis = hit.synopsis
                if hit.authors and not authors:
                    authors = hit.authors
                if cover_url:
                    break
        except Exception:
            pass

        result = EnrichmentResult(
            title=title,
            authors=authors,
            cover_url=cover_url,
            page_count=page_count,
            first_publish_year=year,
            subjects=subjects,
            match_confidence=confidence,
            needs_review=confidence < 0.75,
            metadata_source="llm",
            synopsis=synopsis,
            raw={"provider": provider, "payload": payload},
        )

    save_cache(
        "llm",
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
