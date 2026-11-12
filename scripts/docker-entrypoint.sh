#!/bin/sh
set -eu

mkdir -p /app/data/epubs /app/data/cache /app/data/raw

# Headless WebToEpub runner (localhost only)
node /app/compiler-js/src/server.mjs &
WTE_PID=$!

TG_PID=""
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] || [ -n "${TELEGRAM_TOKEN:-}" ]; then
  python /app/scripts/telegram_bot.py &
  TG_PID=$!
  echo "Telegram bot started (pid $TG_PID)"
fi

cleanup() {
  kill "$WTE_PID" 2>/dev/null || true
  if [ -n "$TG_PID" ]; then
    kill "$TG_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Wait briefly for runner health
i=0
while [ "$i" -lt 50 ]; do
  if wget -qO- "http://127.0.0.1:${WTE_PORT:-8791}/health" >/dev/null 2>&1; then
    echo "WebToEpub runner ready"
    break
  fi
  i=$((i + 1))
  sleep 0.2
done

echo "Starting Soap's Shelf on 0.0.0.0:${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
