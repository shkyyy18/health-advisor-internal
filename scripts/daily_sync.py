#!/usr/bin/env python3
"""Daily automatic sync for the health assistant.

Syncs Strava activities and Xiaomi Mi Fitness data (sleep, body composition,
daily metrics) by calling the local service endpoints, so the service stays
the single SQLite writer. Starts the service first if it is not running.

Logs to logs/daily_sync.log. Exit code 1 when any source fails, so the
Windows scheduled task result reflects the failure.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).absolute().parent.parent
LOG_PATH = BASE_DIR / "logs" / "daily_sync.log"
PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}"
SYNC_TIMEOUT_SECONDS = 180


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ensure_service() -> bool:
    if port_open(PORT):
        return True
    log("服务未运行，先启动健康助手服务。")
    subprocess.Popen(
        [sys.executable, "-m", "scripts.start_health_services"],
        cwd=BASE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        if port_open(PORT):
            return True
        time.sleep(1)
    return False


def post_sync(path: str) -> tuple[bool, str]:
    request = urllib.request.Request(f"{BASE_URL}{path}", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SYNC_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return True, body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return False, f"HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    log("开始每日同步。")
    if not ensure_service():
        log("失败：健康助手服务在 30 秒内未就绪，放弃本次同步。")
        return 1

    failed = False
    for name, path in (("xiaomi", "/api/sync/xiaomi"), ("strava", "/api/sync/strava")):
        ok, detail = post_sync(path)
        if ok:
            try:
                detail = json.dumps(json.loads(detail), ensure_ascii=False)
            except (ValueError, TypeError):
                pass
            log(f"{name} 同步成功：{detail[:800]}")
        else:
            failed = True
            log(f"{name} 同步失败：{detail}")

    log("每日同步结束。" if not failed else "每日同步结束（有失败项）。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
