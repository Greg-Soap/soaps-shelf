# Shelf — book library pipeline

All-Python weekend project: import Microsoft To Do PDF/txt lists → enrich via Open Library → browse in a simple Jinja gallery. Shared `add_book()` is ready for a future Telegram/WhatsApp bot.

## Setup

```bash
cd book-library
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Import titles

PDFs live in `data/raw/` (`1.pdf`–`4.pdf`). Default status mapping:

| File | To Do list name                     | Status        |
|------|-------------------------------------|---------------|
| 1    | Novels                              | read          |
| 2    | Novels Read Ongoing                 | reading       |
| 3    | Novels Dropped                      | dropped       |
| 4    | Novels Read I've Not Finished       | not_finished  |

Dry-run parse (no DB writes):

```bash
python scripts/import_raw.py --dry-run --no-enrich
```

Import without hitting Open Library yet:

```bash
python scripts/import_raw.py --no-enrich
```

If a PDF extracts almost nothing, open it, select all text, paste into `data/raw/1.txt` (same stem), and re-run. `.txt` wins over `.pdf` for that stem.

Override statuses:

```bash
python scripts/import_raw.py --no-enrich --status-map '{"1":"want_to_read","2":"read","3":"reading","4":"other"}'
```

## Enrich

Metadata order: **Aethon → [chikari.moe](https://chikari.moe) → [freewebnovel.com](https://freewebnovel.com) → NovelUpdates → strict Open Library**.
Chikari/FreeWebNovel cover most web novels (covers, authors, tags, synopsis).
Weak Open Library hits are rejected (better blank than wrong Arthur C. Clarke for *Cradle*).

```bash
# Clear bad matches and re-enrich everything
python scripts/enrich_pending.py --reset

# Or only pending / needs-review rows
python scripts/enrich_pending.py
```

Responses are cached under `data/cache/`. NovelUpdates is Cloudflare-protected and may miss often; Aethon works well for their LitRPG catalog.

### LLM fill for Needs review

```bash
# Edit .env and set:
#   GEMINI_API_KEY=your_key_here
# Free key: https://aistudio.google.com/apikey

python scripts/enrich_llm.py --dry-run   # see targets
python scripts/enrich_llm.py             # fill author / genres / synopsis
```

Uses the LLM for titles the scrapers missed, then tries Aethon/Open Library again for a cover.

## Add one book (bot-shaped CLI)

```bash
python -m library.add "Cradle book 1" --status read
```

## Telegram bot

1. Open Telegram → [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token
2. Put it in `.env`:

```bash
TELEGRAM_BOT_TOKEN=123456:ABC...
# After you message /id to the bot:
TELEGRAM_ALLOWED_USER_IDS=your_numeric_id
TELEGRAM_DEFAULT_STATUS=want_to_read
```

3. Run (separate terminal from the gallery):

```bash
python scripts/telegram_bot.py
```

Then DM the bot a title (`Cradle`), or `reading: Shadow Slave`, or `/read Dungeon Crawler Carl`.

## Gallery + API

```bash
# Bind to all interfaces so the phone can reach the API on your LAN
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Gallery: http://127.0.0.1:8000/
- Compiler: http://127.0.0.1:8000/compiler
- Categories: http://127.0.0.1:8000/categories
- Add book: `POST /api/books` with `{"title":"…","status":"read"}`

## Mobile app (Expo)

Primary client for day-to-day use. Talks to the same FastAPI backend.

```bash
# 1) API reachable on LAN (see host 0.0.0.0 above)
# 2) Set your Mac's Wi‑Fi IP in mobile/.env
#    EXPO_PUBLIC_API_URL=http://192.168.x.x:8000

cd mobile
npm start
```

Then open in Expo Go (same Wi‑Fi). Tabs: **Shelf**, **Compile**, **Categories**.

## Compile EPUB (Prestigio handoff)

Uses vendored **WebToEpub** parsers (100+ hosts) via a Node headless runner, with a Python Royal Road fallback if Cloudflare blocks Node fetch.

```bash
# Optional: keep the runner warm (Docker starts this for you)
cd compiler-js && npm install && npm start

# Smoke test (3 chapters) — blocks until done
python scripts/compile_epub.py "https://…" --limit 3
```

`POST /api/compile` **queues** jobs (Render-safe); poll `/api/compile/jobs/{id}`. EPUBs land in `data/epubs/`.

Docker / Render: see [docs/RENDER.md](docs/RENDER.md).

## Layout

- `library/` — db, ingest, enrich, `add_book`, categories, compiler
- `compiler-js/` — headless WebToEpub runner
- `vendor/webtoepub/` — GPL-3 parser sources
- `scripts/` — import, enrich, compile, telegram bot
- `app/` — FastAPI + Jinja UI
- `mobile/` — Expo client (Soap's Shelf)
- `data/raw/` — source PDFs/txt
- `data/epubs/` — compiled EPUBs
- `reference/` — local WebToEpub dump (gitignored)
