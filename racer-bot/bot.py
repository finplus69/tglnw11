#!/usr/bin/env python3
"""Racer Check Bot: screenshot verification, scores, reports and backups."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import json
import os
import random
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message
import google.generativeai as genai
from task_manager import TaskManager
from x_integration import XMonitor


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "score.db"))).expanduser()
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(ROOT / "backups"))).expanduser()
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8080")))
CHECK_REPEAT_RATE = float(os.getenv("CHECK_REPEAT_RATE", "0.20"))


def csv_ints(name: str) -> set[int]:
    return {int(value.strip()) for value in os.getenv(name, "").split(",") if value.strip()}


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_KEY = os.getenv("GEMINI_KEY", "")
ADMIN_IDS = csv_ints("ADMIN_IDS")
ALLOWED_CHAT = csv_ints("ALLOWED_CHAT")
ACTIVE_CHANNEL_IDS = csv_ints("ACTIVE_CHANNEL_IDS")
ADMIN_CHAT = int(os.getenv("ADMIN_CHAT", "0")) if os.getenv("ADMIN_CHAT") else 0
DEADLINE = dt.datetime.fromisoformat(os.getenv("DEADLINE", "2099-12-31T23:59:00"))
RACER_WEBHOOK_URL = os.getenv("RACER_WEBHOOK_URL", "")
RACER_WEBHOOK_SECRET = os.getenv("RACER_WEBHOOK_SECRET", "")

PROMPT = """ตรวจสกรีนช็อตงานนี้และตอบเป็น JSON เท่านั้น ห้ามใส่ markdown:
{"like":true,"repost":false,"bookmark":true,"comment":true}
ตรวจว่ามีหลักฐานของทั้ง 4 รายการหรือไม่: like, repost, bookmark, comment
ค่าทุกตัวต้องเป็น boolean เท่านั้น"""

router = Router()
_db_lock = threading.RLock()


def require_settings() -> None:
    missing = []
    for name, value in (("BOT_TOKEN", BOT_TOKEN), ("GEMINI_KEY", GEMINI_KEY)):
        if not value or value.startswith("YOUR_"):
            missing.append(name)
    if not ALLOWED_CHAT:
        missing.append("ALLOWED_CHAT")
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))


def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


conn = db_connect()
with _db_lock:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL DEFAULT 0,
            checks INTEGER NOT NULL DEFAULT 0,
            passed INTEGER NOT NULL DEFAULT 0,
            hot INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            ts TEXT NOT NULL,
            passed INTEGER NOT NULL,
            points INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS image_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            ts TEXT NOT NULL
        );
        """
    )
    conn.commit()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_allowed(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT


def get_user(user_id: int, username: str | None) -> sqlite3.Row:
    username = username or "ไม่มี username"
    with _db_lock:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO users(id, username) VALUES(?, ?)", (user_id, username))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        elif row["username"] != username:
            conn.execute("UPDATE users SET username=? WHERE id=?", (username, user_id))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return row


def remember_image(user_id: int, image_bytes: bytes) -> bool:
    digest = hashlib.sha256(image_bytes).hexdigest()
    with _db_lock:
        try:
            conn.execute(
                "INSERT INTO image_hashes(uid, hash, ts) VALUES(?, ?, ?)",
                (user_id, digest, dt.datetime.now().isoformat(timespec="seconds")),
            )
            conn.commit()
            return False
        except sqlite3.IntegrityError:
            return True


def parse_ai_result(text: str) -> dict[str, bool]:
    cleaned = text.strip().removeprefix("```").removesuffix("```").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    result = json.loads(cleaned)
    if not isinstance(result, dict):
        raise ValueError("AI result is not an object")
    keys = ("like", "repost", "bookmark", "comment")
    if set(result) != set(keys) or not all(type(result[key]) is bool for key in keys):
        raise ValueError("AI result has an invalid schema")
    return {key: result[key] for key in keys}


task_manager = TaskManager(
    connection=conn,
    lock=_db_lock,
    allowed_chats=ALLOWED_CHAT,
    active_channels=ACTIVE_CHANNEL_IDS,
    admin_ids=ADMIN_IDS,
    admin_chat=ADMIN_CHAT,
    gemini_model=lambda: genai.GenerativeModel("gemini-1.5-flash"),
    parse_ai_result=parse_ai_result,
    get_user=get_user,
    webhook_url=RACER_WEBHOOK_URL,
    webhook_secret=RACER_WEBHOOK_SECRET,
)
task_manager.register(router)
x_monitor = XMonitor(
    connection=conn,
    lock=_db_lock,
    admin_chat=ADMIN_CHAT,
    webhook_url=RACER_WEBHOOK_URL,
    webhook_secret=RACER_WEBHOOK_SECRET,
)
x_monitor.register(router)


def record_task(user_id: int, username: str, passed: bool, points: int, hot: bool) -> None:
    with _db_lock:
        conn.execute(
            "UPDATE users SET checks=checks+1, passed=passed+?, score=score+?, hot=hot+? WHERE id=?",
            (int(passed), points, int(hot), user_id),
        )
        conn.execute(
            "INSERT INTO tasks(uid, ts, passed, points, source) VALUES(?, ?, ?, ?, ?)",
            (user_id, dt.datetime.now().isoformat(timespec="seconds"), int(passed), points, username or ""),
        )
        conn.commit()


async def guard(message: Message) -> bool:
    if not is_allowed(message.chat.id):
        await message.answer("🔒 แชทนี้ไม่ได้รับอนุญาตให้ใช้งาน")
        return False
    return True


@router.message(Command("start"))
async def start(message: Message) -> None:
    if not await guard(message):
        return
    days = max((DEADLINE - dt.datetime.now()).days, 0)
    await message.answer(f"👋 ยินดีต้อนรับ!\nส่งสกรีนช็อตงานเพื่อให้ระบบตรวจ\n⏰ เหลือเวลา {days} วัน")


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    if not await guard(message):
        return
    await message.answer("คำสั่ง: /start /profile /leaderboard /admin /my_chat_id /notify_test\nส่งภาพเพื่อให้ระบบตรวจ")


@router.message(Command("my_chat_id"))
async def my_chat_id(message: Message) -> None:
    user_id = message.from_user.id if message.from_user else "ไม่ทราบ"
    await message.answer(f"Telegram chat ID: {message.chat.id}\nUser ID: {user_id}\nนำ chat ID ไปตั้งใน TELEGRAM_NOTIFY_CHAT_IDS")


@router.message(Command("profile"))
async def profile(message: Message) -> None:
    if not await guard(message):
        return
    user = get_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"👤 @{user['username']}\n📊 คะแนน: {user['score']}\n"
        f"🔥 Hot Time: {user['hot']}\n✅ ผ่าน: {user['passed']}/{user['checks']}"
    )


@router.message(Command("leaderboard"))
async def leaderboard(message: Message) -> None:
    if not await guard(message):
        return
    with _db_lock:
        rows = conn.execute("SELECT username, score FROM users ORDER BY score DESC, id LIMIT 10").fetchall()
    body = "\n".join(f"{index}. @{row['username']} — {row['score']}" for index, row in enumerate(rows, 1))
    await message.answer("🏆 ลีดเดอร์บอร์ด\n\n" + (body or "ยังไม่มีผู้ร่วมงาน"))


@router.message(Command("admin"))
async def admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("🚫 คำสั่งนี้สำหรับแอดมินเท่านั้น")
        return
    with _db_lock:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        passed = conn.execute("SELECT COUNT(*) FROM tasks WHERE passed=1").fetchone()[0]
    await message.answer(f"🛡 Admin Panel\n👥 ผู้ร่วมงาน: {users}\n📥 งานที่ส่ง: {tasks}\n✅ ผ่าน: {passed}\n❌ ไม่ผ่าน: {tasks - passed}")


@router.message(F.photo)
async def check_photo(message: Message, bot: Bot) -> None:
    if await task_manager.handle_evidence(message, bot):
        return
    if not await guard(message):
        return
    user = get_user(message.from_user.id, message.from_user.username)
    telegram_file = await bot.get_file(message.photo[-1].file_id)
    buffer = io.BytesIO()
    await bot.download_file(telegram_file.file_path, buffer)
    image_bytes = buffer.getvalue()
    if remember_image(user["id"], image_bytes):
        await message.answer("⚠️ ภาพนี้เคยส่งแล้ว ไม่สามารถใช้ซ้ำได้")
        return
    if random.random() < CHECK_REPEAT_RATE:
        await message.answer("🔁 ระบบสุ่มตรวจซ้ำ กรุณาส่งภาพใหม่เพื่อยืนยัน")
        return
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = await asyncio.to_thread(model.generate_content, [PROMPT, {"mime_type": "image/jpeg", "data": image_bytes}])
        result = parse_ai_result(response.text)
        now = dt.datetime.now()
        hot = (DEADLINE - now).total_seconds() < 5 * 60
        passed = all(result.values())
        points = (40 if passed else 0) + (20 if passed and hot else 0)
        record_task(user["id"], message.from_user.username or "", passed, points, hot and passed)
        if passed:
            suffix = " +🔥Hot Time" if hot else ""
            await message.answer(f"✅ ผ่านครบ! +{points} คะแนน{suffix} 🎉")
        else:
            missing = ", ".join(key for key, value in result.items() if not value)
            await message.answer(f"❌ ยังขาด: {missing}")
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError):
        await message.answer("อ่านภาพไม่ชัดหรือผลตรวจไม่ถูกต้อง กรุณาส่งใหม่ครับ 🙏")
    except Exception:
        await message.answer("ระบบตรวจภาพขัดข้องชั่วคราว กรุณาลองใหม่ภายหลังครับ")


async def backup_db() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            target = BACKUP_DIR / f"score_{timestamp}.db"
            temporary = target.with_suffix(".tmp")
            with _db_lock:
                source = sqlite3.connect(DB_PATH)
                destination = sqlite3.connect(temporary)
                source.backup(destination)
                destination.close()
                source.close()
            temporary.replace(target)
            backups = sorted(BACKUP_DIR.glob("score_*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
            for old_file in backups[7:]:
                old_file.unlink(missing_ok=True)
        except Exception as exc:
            print(f"backup failed: {exc}")
        await asyncio.sleep(6 * 60 * 60)


async def hourly_report(bot: Bot) -> None:
    while True:
        await asyncio.sleep(60 * 60)
        if not ADMIN_CHAT:
            continue
        with _db_lock:
            rows = conn.execute("SELECT username, score FROM users ORDER BY score DESC, id LIMIT 10").fetchall()
        body = "\n".join(f"{index}. @{row['username']} — {row['score']}" for index, row in enumerate(rows, 1)) or "ยังไม่มีผู้ร่วมงาน"
        try:
            await bot.send_message(ADMIN_CHAT, f"📊 รายงานรายชั่วโมง ({dt.datetime.now():%H:%M})\n\n{body}")
        except Exception as exc:
            print(f"hourly report failed: {exc}")


async def deadline_warning(bot: Bot) -> None:
    sent: set[int] = set()
    while True:
        remaining = (DEADLINE - dt.datetime.now()).total_seconds()
        days = int(remaining // 86400)
        if ADMIN_CHAT and days in (1, 2, 3) and days not in sent:
            try:
                await bot.send_message(ADMIN_CHAT, f"⏰ เหลือ {days} วันถึงเดดไลน์")
                sent.add(days)
            except Exception as exc:
                print(f"deadline warning failed: {exc}")
        await asyncio.sleep(60 * 60)


async def main() -> None:
    require_settings()
    genai.configure(api_key=GEMINI_KEY)
    from web import serve_dashboard

    bot = Bot(BOT_TOKEN)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    web_thread = threading.Thread(target=serve_dashboard, args=(DB_PATH, WEB_PORT), daemon=True)
    web_thread.start()
    await asyncio.gather(
        backup_db(),
        hourly_report(bot),
        deadline_warning(bot),
        x_monitor.run(bot),
        dispatcher.start_polling(bot),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
