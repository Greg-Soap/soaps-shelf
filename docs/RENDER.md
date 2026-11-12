# Deploy Soap's Shelf on Render

One Docker service runs:

1. **FastAPI** (gallery + JSON API for the Expo app)
2. **WebToEpub Node runner** on localhost `:8791`
3. **Telegram bot** (only if `TELEGRAM_BOT_TOKEN` is set)

The Expo mobile app is a **client** — it is not hosted on Render. Point it at your public API URL.

## Fastest path (Blueprint)

1. Push this repo to GitHub (public is fine).
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Select the repo (uses [`render.yaml`](../render.yaml)).
4. Fill secret env vars when prompted:
   - `GEMINI_API_KEY` (recommended)
   - `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USER_IDS` (optional)
5. Deploy. Health check: `GET /health`.

## Persistent data (important)

SQLite + EPUBs live under `/app/data`.

- **Free web service:** filesystem is ephemeral — data resets on restart/redeploy.
- **Keep your library:** upgrade to a plan that supports disks, then add a disk mounted at `/app/data` (1 GB is enough to start).

## Manual Docker service (without Blueprint)

- Runtime: **Docker**
- Dockerfile path: `./Dockerfile`
- Health check path: `/health`
- Same env vars as in `render.yaml`

## After deploy

- Gallery: `https://YOUR-SERVICE.onrender.com/`
- API health: `https://YOUR-SERVICE.onrender.com/health`
- Compile: `POST /api/compile` (async — poll `/api/compile/jobs/{id}`)

Mobile (`mobile/.env`):

```bash
EXPO_PUBLIC_API_URL=https://YOUR-SERVICE.onrender.com
```

## Local Docker smoke test

```bash
docker compose up --build
curl -s http://127.0.0.1:8000/health
```

## License note

`vendor/webtoepub/` is GPL-3 (WebToEpub). Shipping it in the Docker image means the distributed backend should be treated as GPL-compatible. See `vendor/webtoepub/LICENSE.md`.
