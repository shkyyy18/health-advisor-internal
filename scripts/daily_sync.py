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
# 夜间（约 21:40）小米云响应明显变慢，180s 内服务端同步尚未完成，
# 客户端超时误报失败，随后 stop_service 还会把仍在同步的服务杀掉
# （2026-07-23 起连续多晚实录，早上同样数据量 40s 内完成）。放宽到 600s：
# 覆盖服务端 connect 3 次重试 + 采集重试的常见最坏情况，同时给 strava
# 同步和启动预留余量，整轮仍低于计划任务 15 分钟 ExecutionTimeLimit。
SYNC_TIMEOUT_SECONDS = 600


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


def post_sync(path: str) -> tuple[bool, str, bool]:
    """返回 (是否成功, 详情, 是否可重试)。

    HTTP 错误（如小米鉴权失败返回 400）重试无意义，不重试；
    网络/超时类错误（TimeoutError、URLError）可重试——服务端同步是幂等
    upsert，且服务端已加锁串行化，客户端超时后重试安全。
    """
    request = urllib.request.Request(f"{BASE_URL}{path}", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SYNC_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", errors="replace")
            return True, body, False
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return False, f"HTTP {exc.code}: {detail}", False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}", True


RETRY_DELAYS_SECONDS = (30, 60)  # 网络类失败的指数退避：最多重试 2 次


def post_sync_with_retry(name: str, path: str) -> tuple[bool, str]:
    for attempt, delay in enumerate([0, *RETRY_DELAYS_SECONDS]):
        if delay:
            log(f"{name} 同步为网络类失败，{delay} 秒后进行第 {attempt + 1} 次重试…")
            time.sleep(delay)
        ok, detail, retriable = post_sync(path)
        if ok or not retriable:
            return ok, detail
    return ok, detail


def main() -> int:
    log("开始每日同步。")
    service_state = ensure_service()
    if service_state is None:
        log("失败：健康助手服务在 30 秒内未就绪，放弃本次同步。")
        return 1

    failed = False
    for name, path in (("xiaomi", "/api/sync/xiaomi"), ("strava", "/api/sync/strava")):
        # 2026-07-23 起连续多晚 21:40 场 xiaomi 同步 TimeoutError（strava 正常）：
        # 网络类失败按指数退避正式重试（30s、60s），HTTP/鉴权类错误不重试。
        ok, detail = post_sync_with_retry(name, path)
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
