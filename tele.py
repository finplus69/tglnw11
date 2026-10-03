#!/usr/bin/env python3
"""A privacy-conscious Telegram workspace CLI with a local Chrome event bridge.

This tool intentionally does not implement bulk messaging, bulk member adding,
or any flood-limit bypass. Use it only for accounts and groups you control or
are authorized to administer.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from telethon import TelegramClient
from telethon.errors import RPCError, SessionPasswordNeededError

APP_DIR = Path(os.environ.get("TELE_HOME", Path.home() / ".tele-workspace"))
CONFIG_FILE = APP_DIR / "config.env"
SESSION_DIR = APP_DIR / "sessions"
NOTIFY_TOKEN_FILE = APP_DIR / "notify.token"
NOTIFY_HOST = "127.0.0.1"
NOTIFY_PORT = int(os.environ.get("TELE_NOTIFY_PORT", "8765"))


def die(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(code)


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"):
        if os.getenv(key):
            values[key] = os.environ[key]
    return values


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def notification_token() -> str:
    ensure_app_dir()
    if not NOTIFY_TOKEN_FILE.exists():
        NOTIFY_TOKEN_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        os.chmod(NOTIFY_TOKEN_FILE, 0o600)
    return NOTIFY_TOKEN_FILE.read_text(encoding="utf-8").strip()


def emit_event(event: str, message: str, **data: Any) -> None:
    """Best-effort event delivery; CLI work never fails if the bridge is off."""
    payload = {"event": event, "message": message, "timestamp": int(time.time() * 1000), **data}
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        f"http://{NOTIFY_HOST}:{NOTIFY_PORT}/emit",
        data=body,
        headers={"Content-Type": "application/json", "X-Tele-Token": notification_token()},
        method="POST",
    )
    try:
        with urlopen(request, timeout=0.8):
            pass
    except Exception:
        pass


def require_config() -> tuple[int, str, str]:
    values = load_config()
    missing = [k for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE") if not values.get(k)]
    if missing:
        die("ยังไม่ได้ตั้งค่า " + ", ".join(missing) + ". เรียก `python tele.py setup` ก่อน")
    try:
        api_id = int(values["TELEGRAM_API_ID"])
    except ValueError:
        die("TELEGRAM_API_ID ต้องเป็นตัวเลข")
    return api_id, values["TELEGRAM_API_HASH"], values["TELEGRAM_PHONE"]


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return value[:80] or "telegram"


def setup(_: argparse.Namespace) -> None:
    ensure_app_dir()
    api_id = input("Telegram API ID: ").strip()
    api_hash = getpass.getpass("Telegram API hash: ").strip()
    phone = input("Phone number (+countrycode...): ").strip()
    if not api_id.isdigit() or not api_hash or not phone:
        die("ข้อมูลตั้งค่าไม่ครบหรือไม่ถูกต้อง")
    CONFIG_FILE.write_text(
        f"TELEGRAM_API_ID={api_id}\nTELEGRAM_API_HASH={api_hash}\nTELEGRAM_PHONE={phone}\n",
        encoding="utf-8",
    )
    os.chmod(CONFIG_FILE, 0o600)
    token = notification_token()
    print(f"บันทึกการตั้งค่าไว้ที่ {CONFIG_FILE} (ไม่อยู่ใน Git)")
    print(f"Notification token สำหรับใส่ใน Chrome Extension: {token}")


def client_for() -> TelegramClient:
    api_id, api_hash, phone = require_config()
    ensure_app_dir()
    return TelegramClient(str(SESSION_DIR / safe_name(phone)), api_id, api_hash)


def connected_client() -> TelegramClient:
    client = client_for()
    try:
        client.start(phone=load_config()["TELEGRAM_PHONE"])
    except SessionPasswordNeededError:
        password = getpass.getpass("Telegram 2FA password: ")
        client.sign_in(password=password)
    except RPCError as exc:
        client.disconnect()
        emit_event("error", f"Telegram API error: {exc}")
        die(f"Telegram API แจ้งข้อผิดพลาด: {exc}")
    return client


def check(_: argparse.Namespace) -> None:
    emit_event("task_started", "กำลังตรวจสอบบัญชี Telegram", task="check")
    client = connected_client()
    try:
        me = client.get_me()
        name = " ".join(x for x in (me.first_name, me.last_name) if x) or "(ไม่มีชื่อ)"
        message = f"เข้าสู่ระบบแล้ว: {name} | id={me.id}"
        print(message)
        emit_event("task_completed", message, task="check")
    finally:
        client.disconnect()


def groups(_: argparse.Namespace) -> None:
    emit_event("task_started", "กำลังโหลดรายการกลุ่มและช่อง", task="groups")
    client = connected_client()
    try:
        found = 0
        for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                found += 1
                kind = "กลุ่ม" if dialog.is_group else "ช่อง/megagroup"
                print(f"{dialog.id}\t{kind}\t{dialog.name}")
        message = f"โหลดรายการสำเร็จ {found} รายการ"
        print(message)
        emit_event("task_completed", message, task="groups", count=found)
    finally:
        client.disconnect()


def resolve_group(client: TelegramClient, value: str):
    value = value.strip()
    if value.lstrip("-").isdigit():
        return client.get_entity(int(value))
    return client.get_entity(value if value.startswith("@") or value.startswith("t.me/") else f"@{value}")


def export_members(args: argparse.Namespace) -> None:
    if args.limit < 1 or args.limit > 10000:
        die("limit ต้องอยู่ระหว่าง 1 ถึง 10000")
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    emit_event("task_started", f"กำลัง export สมาชิกจาก {args.group}", task="export-members", group=args.group)
    client = connected_client()
    try:
        group = resolve_group(client, args.group)
        title = getattr(group, "title", args.group)
        rows: list[dict[str, str]] = []
        for user in client.iter_participants(group, limit=args.limit):
            username = user.username or ""
            if not username and not args.include_no_username:
                continue
            name = " ".join(x for x in (user.first_name, user.last_name) if x).strip()
            rows.append({"username": username, "display_name": name, "group": title})
        with output.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["username", "display_name", "group"])
            writer.writeheader()
            writer.writerows(rows)
        message = f"ส่งออก {len(rows)} รายการไปที่ {output}"
        print(message)
        print("หมายเหตุ: ใช้ข้อมูลตามสิทธิ์และความยินยอมที่เหมาะสม ห้ามใช้เพื่อสแปมหรือเพิ่มสมาชิกจำนวนมาก")
        emit_event("task_completed", message, task="export-members", group=title, count=len(rows), output=str(output))
    except Exception as exc:
        emit_event("error", f"export ไม่สำเร็จ: {exc}", task="export-members")
        raise
    finally:
        client.disconnect()


class EventBridge:
    clients: set[Any] = set()
    lock = threading.Lock()

    @classmethod
    def publish(cls, payload: dict[str, Any]) -> None:
        packet = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        with cls.lock:
            dead = []
            for client in cls.clients:
                try:
                    client.wfile.write(packet)
                    client.wfile.flush()
                except Exception:
                    dead.append(client)
            for client in dead:
                cls.clients.discard(client)


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "TeleEventBridge/1.0"

    def log_message(self, *_: Any) -> None:
        return

    def authorized(self) -> bool:
        return self.headers.get("X-Tele-Token") == notification_token() or parse_qs(urlparse(self.path).query).get("token", [""])[0] == notification_token()

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if urlparse(self.path).path != "/events" or not self.authorized():
            self.send_error(403)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        with EventBridge.lock:
            EventBridge.clients.add(self)
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                time.sleep(15)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except Exception:
            pass
        finally:
            with EventBridge.lock:
                EventBridge.clients.discard(self)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/emit" or not self.authorized():
            self.send_error(403)
            return
        try:
            size = min(int(self.headers.get("Content-Length", "0")), 16384)
            payload = json.loads(self.rfile.read(size))
            EventBridge.publish(payload)
            self.send_response(204)
            self.end_headers()
        except Exception:
            self.send_error(400)


def notifications(_: argparse.Namespace) -> None:
    token = notification_token()
    server = ThreadingHTTPServer((NOTIFY_HOST, NOTIFY_PORT), BridgeHandler)
    print(f"Local notification bridge: http://{NOTIFY_HOST}:{NOTIFY_PORT}")
    print(f"Chrome Extension token: {token}")
    print("กด Ctrl+C เพื่อหยุด")
    emit_event("bridge_started", "Notification bridge พร้อมใช้งาน", port=NOTIFY_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("หยุด notification bridge แล้ว")
    finally:
        server.server_close()


def notify_token(_: argparse.Namespace) -> None:
    print(notification_token())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="เครื่องมือจัดการ Telegram แบบปลอดภัย")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="ตั้งค่า API credentials และสร้าง notification token").set_defaults(func=setup)
    sub.add_parser("check", help="ตรวจสอบการเข้าสู่ระบบและบัญชีปัจจุบัน").set_defaults(func=check)
    sub.add_parser("groups", help="แสดงกลุ่ม/ช่องที่บัญชีเข้าถึงได้").set_defaults(func=groups)
    sub.add_parser("notifications", help="เปิด local event bridge สำหรับ Chrome Extension").set_defaults(func=notifications)
    sub.add_parser("notify-token", help="แสดง token สำหรับเชื่อมต่อ Chrome Extension").set_defaults(func=notify_token)
    exp = sub.add_parser("export-members", help="ส่งออกชื่อผู้ใช้สาธารณะของกลุ่มที่ได้รับอนุญาต")
    exp.add_argument("--group", required=True, help="username, invite/entity หรือ chat id")
    exp.add_argument("--output", default="members-export.csv")
    exp.add_argument("--limit", type=int, default=1000)
    exp.add_argument("--include-no-username", action="store_true", help="รวมสมาชิกที่ไม่มี username (ยังไม่ส่งออก id ส่วนตัว)")
    exp.set_defaults(func=export_members)
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
