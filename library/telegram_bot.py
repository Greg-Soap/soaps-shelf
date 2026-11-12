"""Simple Telegram long-polling bot that adds books via add_book()."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import httpx

from library.books import ALLOWED_STATUSES, add_book
from library.llm_enrich import available_llm_provider, load_dotenv

TELEGRAM_API = "https://api.telegram.org"

STATUS_ALIASES = {
    "read": "read",
    "reading": "reading",
    "want": "want_to_read",
    "want_to_read": "want_to_read",
    "wtr": "want_to_read",
    "dropped": "dropped",
    "drop": "dropped",
    "nf": "not_finished",
    "not_finished": "not_finished",
    "unfinished": "not_finished",
    "other": "other",
}

HELP_TEXT = """Shelf bot — send a title and I'll add it.

Examples:
  Cradle
  reading: Shadow Slave
  /want Mother of Learning
  /read Dungeon Crawler Carl

Commands:
  /start /help — this text
  /id — your Telegram user id (for allowlist)
  /read|/reading|/want|/dropped|/nf <title>
"""


def telegram_token() -> str | None:
    load_dotenv()
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")


def allowed_user_ids() -> set[int]:
    load_dotenv()
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS") or os.getenv("TELEGRAM_USER_ID") or ""
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


def default_status() -> str:
    load_dotenv()
    value = (os.getenv("TELEGRAM_DEFAULT_STATUS") or "want_to_read").strip().lower()
    return value if value in ALLOWED_STATUSES else "want_to_read"


def parse_message(text: str) -> tuple[str | None, str | None]:
    """Return (status, title). status/title None means a command or empty."""
    text = (text or "").strip()
    if not text:
        return None, None

    lower = text.casefold()
    if lower in {"/start", "/help", "help", "?", "/?"}:
        return None, "__help__"
    if lower in {"/id", "id"}:
        return None, "__id__"

    command = re.match(
        r"^/(read|reading|want|want_to_read|wtr|dropped|drop|nf|not_finished|unfinished|other|add)(?:@\w+)?(?:\s+|$)(.*)$",
        text,
        flags=re.I | re.S,
    )
    if command:
        verb = command.group(1).casefold()
        title = (command.group(2) or "").strip()
        if verb == "add":
            return default_status(), title or None
        return STATUS_ALIASES.get(verb, default_status()), title or None

    prefix = re.match(
        r"^(read|reading|want|want_to_read|wtr|dropped|drop|nf|not_finished|unfinished|other)\s*:\s*(.+)$",
        text,
        flags=re.I | re.S,
    )
    if prefix:
        return STATUS_ALIASES[prefix.group(1).casefold()], prefix.group(2).strip()

    return default_status(), text


def api_url(token: str, method: str) -> str:
    return f"{TELEGRAM_API}/bot{token}/{method}"


def send_message(client: httpx.Client, token: str, chat_id: int, text: str) -> None:
    client.post(
        api_url(token, "sendMessage"),
        json={"chat_id": chat_id, "text": text},
        timeout=30.0,
    )


def format_book(book: dict[str, Any]) -> str:
    title = book.get("title") or book.get("raw_title") or "Untitled"
    authors = book.get("authors") or "author unknown"
    status = (book.get("status") or "").replace("_", " ")
    source = book.get("metadata_source") or "pending"
    cover = "cover ✓" if book.get("cover_url") else "no cover"
    review = " · needs review" if book.get("needs_review") else ""
    return (
        f"Added · {title}\n"
        f"{authors}\n"
        f"Status: {status} · {source} · {cover}{review}"
    )


def handle_text(
    *,
    user_id: int,
    text: str,
    use_llm: bool,
) -> str:
    status, title = parse_message(text)
    if title == "__help__":
        return HELP_TEXT
    if title == "__id__":
        return f"Your Telegram user id: {user_id}"
    if not title:
        return "Send a title, or /help"

    book = add_book(
        title,
        status=status or default_status(),
        source="telegram",
        enrich=True,
        use_llm=use_llm,
    )
    return format_book(book)


def run_bot(*, poll_timeout: int = 25) -> int:
    load_dotenv()
    token = telegram_token()
    if not token:
        print(
            "Missing TELEGRAM_BOT_TOKEN.\n"
            "1. Message @BotFather → /newbot → copy the token\n"
            "2. Add to .env: TELEGRAM_BOT_TOKEN=...\n"
            "3. Optional lock: TELEGRAM_ALLOWED_USER_IDS=your_id  (send /id to the bot)\n"
        )
        return 1

    allow = allowed_user_ids()
    use_llm = available_llm_provider() is not None
    print(
        f"Telegram bot running · llm={'on' if use_llm else 'off'} · "
        f"allowlist={'open' if not allow else sorted(allow)}",
        flush=True,
    )

    offset = 0
    with httpx.Client(timeout=httpx.Timeout(poll_timeout + 10.0, connect=20.0)) as client:
        # Drop pending updates so old messages don't flood-add books
        client.get(api_url(token, "getUpdates"), params={"offset": -1, "timeout": 0})

        while True:
            try:
                response = client.get(
                    api_url(token, "getUpdates"),
                    params={"offset": offset, "timeout": poll_timeout},
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as err:
                print(f"poll error: {err}")
                time.sleep(2)
                continue

            if not payload.get("ok"):
                print(f"telegram error: {payload}")
                time.sleep(2)
                continue

            for update in payload.get("result") or []:
                offset = max(offset, int(update["update_id"]) + 1)
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                chat = message.get("chat") or {}
                user = message.get("from") or {}
                chat_id = chat.get("id")
                user_id = user.get("id")
                text = message.get("text")
                if chat_id is None or user_id is None or not text:
                    continue

                if allow and int(user_id) not in allow:
                    send_message(
                        client,
                        token,
                        int(chat_id),
                        f"Not authorized. Your id is {user_id}.",
                    )
                    continue

                try:
                    reply = handle_text(
                        user_id=int(user_id),
                        text=text,
                        use_llm=use_llm,
                    )
                except Exception as err:
                    reply = f"Failed: {err}"
                send_message(client, token, int(chat_id), reply)

    return 0
