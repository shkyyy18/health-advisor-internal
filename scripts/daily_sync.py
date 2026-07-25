#!/usr/bin/env python3
"""Daily automatic sync for the health assistant.

Syncs Strava activities and Xiaomi Mi Fitness data (sleep, body composition,
daily metrics) by calling the local service endpoints, so the service stays
the single SQLite writer. Starts the service first if it is not running, and
stops it again after the sync so nothing stays resident.

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


def ensure_service() -> str | None:
    """Return 'running' if already up, 'started' if we launched it, None on failure."""
    if port_open(PORT):
        return "running"
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
            return "started"
        time.sleep(1)
    return None


def listening_pid(port: int) -> int | None:
    output = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="replace"
    ).stdout
    for line in output.splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0] == "TCP"
            and parts[1].endswith(f":{port}")
            and parts[3] == "LISTENING"
        ):
            try:
                return int(parts[4])
            except ValueError:
                return None
    return None


def stop_service() -> None:
    pid = listening_pid(PORT)
    if pid is None:
        return
    # /T 连带杀掉 multiprocessing 子进程（spawn_main），避免端口残留占用。
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    log(f"本次同步临时启动的服务已停止（PID {pid}）。")


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
    service_state = ensure_service()
    if service_state is None:
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
    if service_state == "started":
        stop_service()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
