#!/usr/bin/env python3
"""Wait for the local health service, sync fresh data, then open the dashboard.

Launched by scripts/healthboard.bat (via the 健康看板 desktop shortcut or the
healthboard:// protocol bookmark). Flow: wait for uvicorn to come up, pull the
latest Xiaomi + Strava data through the sync endpoints, then open the
dashboard in the browser — so the page shows data fresh as of this click.
Sync failures do not block opening the dashboard.
"""
from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}"
SYNC_TIMEOUT_SECONDS = 180
LOG_PATH = Path(__file__).absolute().parent.parent / "logs" / "open_dashboard.log"


def log(message: str) -> None:
    try:
        print(message)
    except Exception:
        pass  # pythonw 无控制台，sys.stdout 不可用
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def post_sync(path: str) -> tuple[bool, str]:
    request = urllib.request.Request(f"{BASE_URL}{path}", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SYNC_TIMEOUT_SECONDS) as response:
            return True, response.read().decode("utf-8", errors="replace")[:300]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    for _ in range(60):
        if port_open(PORT):
            break
        time.sleep(1)
    else:
        log("Service did not come up in 60s; opening dashboard anyway.")

    log("Opening dashboard immediately; syncing in background...")
    webbrowser.open(BASE_URL)

    log("Syncing latest data from Xiaomi cloud...")
    ok, detail = post_sync("/api/sync/xiaomi")
    log(f"xiaomi sync {'OK' if ok else 'FAILED'}: {detail}")
    log("Syncing latest activities from Strava...")
    ok, detail = post_sync("/api/sync/strava")
    log(f"strava sync {'OK' if ok else 'FAILED'}: {detail}")


if __name__ == "__main__":
    main()
