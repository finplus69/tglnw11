#!/usr/bin/env python3
"""A small, privacy-conscious Telegram workspace CLI.

This tool intentionally does not implement bulk messaging, bulk member adding,
or any flood-limit bypass. Use it only for accounts and groups you control or
are authorized to administer.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import os
import re
import sys
from pathlib import Path
from typing import Iterable

from telethon import TelegramClient
from telethon.errors import RPCError, SessionPasswordNeededError

APP_DIR = Path(os.environ.get("TELE_HOME", Path.home() / ".tele-workspace"))
CONFIG_FILE = APP_DIR / "config.env"
SESSION_DIR = APP_DIR / "sessions"


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
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
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
    print(f"บันทึกการตั้งค่าไว้ที่ {CONFIG_FILE} (ไม่อยู่ใน Git)")


def client_for() -> TelegramClient:
    api_id, api_hash, phone = require_config()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
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
        die(f"Telegram API แจ้งข้อผิดพลาด: {exc}")
    return client


def check(_: argparse.Namespace) -> None:
    client = connected_client()
    try:
        me = client.get_me()
        name = " ".join(x for x in (me.first_name, me.last_name) if x) or "(ไม่มีชื่อ)"
        print(f"เข้าสู่ระบบแล้ว: {name} | id={me.id}")
    finally:
        client.disconnect()


def groups(_: argparse.Namespace) -> None:
    client = connected_client()
    try:
        found = 0
        for dialog in client.iter_dialogs():
            if dialog.is_group or dialog.is_channel:
                found += 1
                kind = "กลุ่ม" if dialog.is_group else "ช่อง/megagroup"
                print(f"{dialog.id}\t{kind}\t{dialog.name}")
        print(f"รวม {found} รายการ")
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
    client = connected_client()
    try:
        group = resolve_group(client, args.group)
        title = getattr(group, "title", args.group)
        rows: list[dict[str, str]] = []
        for user in client.iter_participants(group, limit=args.limit):
            # Minimize personal data: export only public username and display name.
            username = user.username or ""
            if not username and not args.include_no_username:
                continue
            name = " ".join(x for x in (user.first_name, user.last_name) if x).strip()
            rows.append({"username": username, "display_name": name, "group": title})
        with output.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["username", "display_name", "group"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"ส่งออก {len(rows)} รายการไปที่ {output}")
        print("หมายเหตุ: ใช้ข้อมูลตามสิทธิ์และความยินยอมที่เหมาะสม ห้ามใช้เพื่อสแปมหรือเพิ่มสมาชิกจำนวนมาก")
    finally:
        client.disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="เครื่องมือจัดการ Telegram แบบปลอดภัย")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="ตั้งค่า API credentials ไว้ในโฟลเดอร์ local").set_defaults(func=setup)
    sub.add_parser("check", help="ตรวจสอบการเข้าสู่ระบบและบัญชีปัจจุบัน").set_defaults(func=check)
    sub.add_parser("groups", help="แสดงกลุ่ม/ช่องที่บัญชีเข้าถึงได้").set_defaults(func=groups)
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
