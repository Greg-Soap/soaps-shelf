from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from library.db import RAW_DIR

NOISE_PATTERNS = [
    re.compile(r"^microsoft\s+to[\s-]?do$", re.I),
    re.compile(r"^to[\s-]?do$", re.I),
    re.compile(r"^tasks?$", re.I),
    re.compile(r"^my\s+day$", re.I),
    re.compile(r"^important$", re.I),
    re.compile(r"^planned$", re.I),
    re.compile(r"^assigned\s+to\s+me$", re.I),
    re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.I),
    re.compile(r"^\d+\s*/\s*\d+$"),
    re.compile(r"^completed$", re.I),
    re.compile(r"^not\s+completed$", re.I),
    re.compile(r"^due\s+", re.I),
    re.compile(r"^reminder", re.I),
    re.compile(r"^notes?$", re.I),
    re.compile(r"^steps?$", re.I),
    re.compile(r"^created\s+", re.I),
    re.compile(r"^updated\s+", re.I),
    re.compile(r"^today$", re.I),
    re.compile(r"^tomorrow$", re.I),
    re.compile(r"^yesterday$", re.I),
    # Microsoft To Do list chrome from these exports
    re.compile(r"^novels$", re.I),
    re.compile(r"^novels\s+read\s+ongoing$", re.I),
    re.compile(r"^novels\s+dropped$", re.I),
    re.compile(r"^novels\s+read\s+i'?ve\s+not\s+finished$", re.I),
    re.compile(r"^printed\s+with\s+microsoft\s+to[\s-]?do$", re.I),
    re.compile(
        r"^(monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+"
        r"\d{1,2},?\s+\d{4}$",
        re.I,
    ),
]

# Derived from PDF list headers in the user's exports
STATUS_BY_STEM: dict[str, str] = {
    "1": "read",           # Novels (finished)
    "2": "reading",        # Novels Read Ongoing
    "3": "dropped",        # Novels Dropped
    "4": "not_finished",   # Novels Read I've Not Finished
}


@dataclass
class ParsedTitle:
    title: str
    status: str
    source: str


def is_noise(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    if len(text) < 2:
        return True
    if text.isdigit():
        return True
    return any(pattern.match(text) for pattern in NOISE_PATTERNS)


def clean_line(line: str) -> str:
    text = line.strip()
    # Strip private-use / icon glyphs To Do sometimes embeds (e.g. before "Note")
    text = re.sub(r"[\ue000-\uf8ff]", "", text)
    text = re.sub(r"^[\u2022\-\*\u25CF\u25A0\u2610\u2611\u2705]+\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_text_from_pdf(path: Path) -> str:
    doc = fitz.open(path)
    pages: list[str] = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages)


def extract_text_from_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def lines_from_text(text: str) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = clean_line(raw)
        if is_noise(line):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(line)
    return titles


def resolve_source_path(stem: str, raw_dir: Path | None = None) -> Path | None:
    base = raw_dir or RAW_DIR
    txt = base / f"{stem}.txt"
    pdf = base / f"{stem}.pdf"
    if txt.exists() and txt.stat().st_size > 0:
        return txt
    if pdf.exists():
        return pdf
    return None


def parse_file(path: Path, status: str | None = None) -> list[ParsedTitle]:
    stem = path.stem
    resolved_status = status or STATUS_BY_STEM.get(stem, "want_to_read")
    if path.suffix.lower() == ".pdf":
        text = extract_text_from_pdf(path)
    else:
        text = extract_text_from_txt(path)

    titles = lines_from_text(text)
    return [
        ParsedTitle(title=title, status=resolved_status, source=path.name)
        for title in titles
    ]


def parse_raw_dir(
    raw_dir: Path | None = None,
    status_map: dict[str, str] | None = None,
) -> tuple[list[ParsedTitle], list[str]]:
    """Parse PDFs/txts under data/raw. Returns (titles, warnings)."""
    base = raw_dir or RAW_DIR
    mapping = {**STATUS_BY_STEM, **(status_map or {})}
    results: list[ParsedTitle] = []
    warnings: list[str] = []
    global_seen: set[tuple[str, str]] = set()

    stems = sorted(
        {
            path.stem
            for path in base.iterdir()
            if path.suffix.lower() in {".pdf", ".txt"} and path.is_file()
        }
    )

    for stem in stems:
        path = resolve_source_path(stem, base)
        if path is None:
            continue
        status = mapping.get(stem, "want_to_read")
        parsed = parse_file(path, status=status)
        if len(parsed) < 3 and path.suffix.lower() == ".pdf":
            txt_hint = base / f"{stem}.txt"
            warnings.append(
                f"{path.name}: only {len(parsed)} titles extracted. "
                f"If this looks wrong, paste the list into {txt_hint.name} and re-run."
            )
        for item in parsed:
            key = (item.title.casefold(), item.status)
            if key in global_seen:
                continue
            global_seen.add(key)
            results.append(item)

    return results, warnings
