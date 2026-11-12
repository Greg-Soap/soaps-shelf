from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChapterRef:
    index: int
    title: str
    url: str


@dataclass
class ChapterContent:
    index: int
    title: str
    url: str
    html: str


@dataclass
class FictionMeta:
    title: str
    authors: str | None = None
    synopsis: str | None = None
    cover_url: str | None = None
    subjects: str | None = None
    source_url: str = ""
    adapter: str = ""
    chapters: list[ChapterRef] = field(default_factory=list)
