from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

CREATE_NO_WINDOW = 0x08000000
TRUE_VALUES = {"1", "true", "yes", "on"}
PROJECT = Path(__file__).absolute().parent.parent
LOGS = PROJECT / "logs"
LOGS.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    with (LOGS / "startup.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, seconds: int = 15) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


def env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = PROJECT / ".env"
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def ngrok_enabled(values: dict[str, str] | None = None) -> bool:
    configured = env_values() if values is None else values
    return configured.get("HEALTH_ENABLE_NGROK", "").strip().lower() in TRUE_VALUES


def launch(command: list[str], stdout_name: str, stderr_name: str) -> None:
    stdout = (LOGS / stdout_name).open("ab")
    stderr = (LOGS / stderr_name).open("ab")
    subprocess.Popen(
        command,
        cwd=PROJECT,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def main() -> None:
    if not port_open(8000):
        launch(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            "app.out.log",
            "app.err.log",
        )
        if not wait_for_port(8000):
            raise RuntimeError("健康助手未能在 8000 端口启动。")
        log("健康助手已启动。")
    else:
        log("健康助手已在运行。")

    values = env_values()
    if not ngrok_enabled(values):
        log("ngrok is disabled by default; set HEALTH_ENABLE_NGROK=true only after a separate security review.")
        return

    if not port_open(4040):
        ngrok = shutil.which("ngrok")
        if not ngrok:
            log("ngrok was explicitly enabled but the executable was not found; keeping the service local-only.")
            return
        callback = values.get("STRAVA_WEBHOOK_CALLBACK_URL", "")
        host = urlparse(callback).hostname
        if not host:
            log("ngrok was explicitly enabled but no valid callback host is configured; skipping the public tunnel.")
            return
        launch(
            [ngrok, "http", f"--url={host}", "8000", "--log=stdout"],
            "ngrok.log",
            "ngrok.err.log",
        )
        if not wait_for_port(4040):
            raise RuntimeError("ngrok did not start its local admin port 4040.")
        log("ngrok started after explicit local opt-in.")
    else:
        log("ngrok is already running.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"服务启动失败：{exc}")
        raise
