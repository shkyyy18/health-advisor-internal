#!/usr/bin/env python3
"""Create Xiaomi credentials and run the public-path Mi Fitness connector."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
import socket
import sys
from pathlib import Path

BASE_DIR = Path(__file__).absolute().parent.parent
AUTH_DIR = BASE_DIR / "data" / ".mijia"
AUTH_PATH = AUTH_DIR / "auth.json"
QR_PATH = AUTH_DIR / "login_qr.png"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _read_auth() -> dict[str, object]:
    if not AUTH_PATH.exists():
        return {}
    return json.loads(AUTH_PATH.read_text(encoding="utf-8-sig"))


def _validate_auth() -> None:
    payload = _read_auth()
    if not str(payload.get("userId") or "").strip():
        raise RuntimeError(f"Authentication file is missing userId: {AUTH_PATH}")
    if not str(payload.get("passToken") or "").strip():
        raise RuntimeError(f"Authentication file is missing passToken: {AUTH_PATH}")


def reset_login() -> Path | None:
    """Back up only Xiaomi credentials; never delete health data or Strava settings."""
    if not AUTH_PATH.exists():
        return None
    backup = AUTH_PATH.with_name(
        f"auth.json.backup-{datetime.now():%Y%m%d-%H%M%S-%f}"
    )
    AUTH_PATH.rename(backup)
    return backup


def show_qr(path: Path) -> None:
    """Open the newly generated image, with a visible fallback path on failure."""
    print(f"QR image (open manually if no image window appears): {path}", flush=True)
    try:
        os.startfile(str(path))
    except (AttributeError, OSError):
        print("Could not open the image viewer. Open the QR file above manually.", flush=True)


def login() -> None:
    """Use Xiaomi QR login and store userId/passToken in the project data dir."""
    try:
        from mijiaAPI import mijiaAPI
        import qrcode
    except ModuleNotFoundError as exc:
        raise RuntimeError('Missing Xiaomi login dependencies. Run: pip install -e ".[xiaomi]"') from exc

    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    socket.setdefaulttimeout(30)
    api = mijiaAPI(str(AUTH_PATH))
    login_data = api._get_qr_login_data()
    if login_data.get("refreshed"):
        _validate_auth()
        print(f"Xiaomi login is valid: {AUTH_PATH}")
        return

    login_url = login_data.get("loginUrl") or login_data.get("qr")
    if not login_url:
        raise RuntimeError("Xiaomi login service did not return a QR URL.")
    qrcode.make(login_url).save(str(QR_PATH))
    show_qr(QR_PATH)
    print("Scan this QR image with the Mi Home app and confirm login:")
    print(QR_PATH)
    print("Keep this window open until login completes.")
    api._complete_qr_login(login_data)
    _validate_auth()
    print(f"Login succeeded. Credentials saved to: {AUTH_PATH}")


async def _doctor() -> None:
    from app.xiaomi_sync import _adapter_class, load_credentials

    user_id, pass_token = load_credentials(AUTH_PATH)
    adapter = _adapter_class()(user_id=user_id, pass_token=pass_token, region="cn")
    try:
        if not await adapter.connect():
            raise RuntimeError("Mi Fitness cloud connection failed. Run login again.")
        print("Mi Fitness cloud connection is healthy.")
    finally:
        await adapter.close()


async def _sync() -> None:
    from app.xiaomi_sync import sync_mi_fitness

    result = await sync_mi_fitness(credentials_path=AUTH_PATH)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Xiaomi Mi Fitness authentication and sync")
    parser.add_argument(
        "command",
        nargs="?",
        default="sync",
        choices=("login", "discover", "doctor", "sync"),
        help="discover is a backward-compatible alias for login",
    )
    parser.add_argument(
        "--reset-login", action="store_true",
        help="Back up Xiaomi credentials and request a fresh QR; only valid with login",
    )
    args = parser.parse_args()
    if args.reset_login:
        if args.command not in {"login", "discover"}:
            parser.error("--reset-login requires login or discover")
        reset_login()
    if args.command in {"login", "discover"}:
        login()
    elif args.command == "doctor":
        asyncio.run(_doctor())
    else:
        asyncio.run(_sync())


if __name__ == "__main__":
    main()
