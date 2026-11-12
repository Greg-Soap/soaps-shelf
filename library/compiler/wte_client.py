"""Client for the Node WebToEpub headless runner."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_JS = REPO_ROOT / "compiler-js"
CLI = COMPILER_JS / "src" / "cli.mjs"

DEFAULT_BASE = os.environ.get("WTE_URL", "http://127.0.0.1:8791").rstrip("/")


def _http_json(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 600.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{DEFAULT_BASE}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def runner_available() -> bool:
    try:
        payload = _http_json("GET", "/health", timeout=2.0)
        return bool(payload.get("ok"))
    except Exception:
        return False


def detect_url(url: str) -> dict[str, Any]:
    if runner_available():
        return _http_json("POST", "/detect", {"url": url}, timeout=30.0)
    return _cli_json(["--detect", "--url", url])


def list_hosts() -> dict[str, Any]:
    if runner_available():
        return _http_json("GET", "/hosts", timeout=30.0)
    return _cli_json(["--hosts"])


def compile_url(
    url: str,
    *,
    chapter_from: int = 0,
    chapter_to: int | None = None,
    limit: int | None = None,
    delay: float = 0.55,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "url": url,
        "chapterFrom": chapter_from,
        "delay": delay,
    }
    if chapter_to is not None:
        body["chapterTo"] = chapter_to
    if limit is not None:
        body["limit"] = limit

    if runner_available():
        try:
            return _http_json("POST", "/compile", body, timeout=max(120.0, delay * 20 + 60))
        except HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(detail)
                detail = payload.get("detail") or detail
            except Exception:
                pass
            raise RuntimeError(detail) from err
        except URLError as err:
            raise RuntimeError(f"WebToEpub runner unreachable: {err}") from err

    args = ["--url", url, "--from", str(chapter_from), "--delay", str(delay)]
    if chapter_to is not None:
        args.extend(["--to", str(chapter_to)])
    if limit is not None:
        args.extend(["--limit", str(limit)])
    return _cli_json(args)


def _cli_json(args: list[str]) -> dict[str, Any]:
    if not CLI.exists():
        raise RuntimeError(f"WebToEpub CLI missing at {CLI}")
    started = time.time()
    proc = subprocess.run(
        ["node", str(CLI), *args],
        cwd=str(COMPILER_JS),
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "WebToEpub CLI failed").strip())
    # CLI may log warmup lines before JSON.
    stdout = proc.stdout.strip()
    start = stdout.find("{")
    if start < 0:
        raise RuntimeError(f"WebToEpub CLI returned no JSON (took {time.time() - started:.1f}s)")
    return json.loads(stdout[start:])
