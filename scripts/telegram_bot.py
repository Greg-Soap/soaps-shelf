#!/usr/bin/env python3
"""Run the Telegram shelf bot (long polling)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from library.telegram_bot import run_bot


def main() -> int:
    return run_bot()


if __name__ == "__main__":
    sys.exit(main())
