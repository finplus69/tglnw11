"""Telegram channel-post/task/thread integration for Racer Check Bot.

The module deliberately keeps the Telegram correlation keys explicit:
(channel_id, channel_post_id) identifies an activity, while discussion_chat_id
and discussion_thread_id identify its comment thread.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import json
import os
import sqlite3
from typing import Any, Awaitable, Callable
from urllib.request import Request, urlopen

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message


class TaskManager:
    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: Any,
        allowed_chats: set[int],
        active_channels: set[int],
        admin_ids: set[int],
        admin_chat: int,
        gemini_model: Callable[[], Any],
        parse_ai_result: Callable[[str], dict[str, bool]],
        get_user: Callable[[int, str | None], sqlite3.Row],
        webhook_url: str = "",
        webhook_secret: str = "",
    ) -> None:
        self.conn = connection
        self.lock = lock
        self.allowed_chats = allowed_chats
        self.active_channels = active_channels
        self.admin_ids = admin_ids
        self.admin_chat = admin_chat
        self.gemini_model = gemini_model
        self.parse_ai_result = parse_ai_result
        self.get_user = get_user
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS channel_posts (
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    channel_title TEXT NOT NULL DEFAULT '',
                    channel_username TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    posted_at TEXT NOT NULL,
                    PRIMARY KEY(channel_id, message_id)
                );
                CREATE TABLE IF NOT EXISTS racer_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    channel_post_id INTEGER NOT NULL,
                    discussion_chat_id INTEGER NOT NULL,
                    discussion_thread_id INTEGER NOT NULL,
                    points INTEGER NOT NULL DEFAULT 40,
                    deadline TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(channel_id, channel_post_id)
                );
                CREATE TABLE IF NOT EXISTS task_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    evidence_message_id INTEGER NOT NULL,
                    source_post_id INTEGER NOT NULL,
                    image_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'verifying',
                    checks_json TEXT NOT NULL DEFAULT '{}',
                    points INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, user_id, image_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_racer_tasks_thread
                    ON racer_tasks(discussion_chat_id, discussion_thread_id, status);
                CREATE INDEX IF NOT EXISTS idx_task_submissions_user
                    ON task_submissions(task_id, user_id, created_at);
                """
            )
            self.conn.commit()

    def _is_allowed_discussion(self, chat_id: int) -> bool:
        return not self.allowed_chats or chat_id in self.allowed_chats

    def _is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    @staticmethod
    def _source_post(message: Message) -> tuple[int, int] | None:
        """Resolve the original channel post from Telegram's auto-forwarded root."""
        reply = message.reply_to_message
        if reply is None:
            return None
        origin = getattr(reply, "forward_origin", None)
        origin_chat = getattr(origin, "chat", None)
        origin_message_id = getattr(origin, "message_id", None)
        if origin_chat is not None and origin_message_id is not None:
            return int(origin_chat.id), int(origin_message_id)
        legacy_chat = getattr(reply, "forward_from_chat", None)
        legacy_message_id = getattr(reply, "forward_from_message_id", None)
        if legacy_chat is not None and legacy_message_id is not None:
            return int(legacy_chat.id), int(legacy_message_id)
        return None

    @staticmethod
    def _message_link(chat_id: int, message_id: int, username: str = "") -> str:
        if username:
            return f"https://t.me/{username.lstrip('@')}/{message_id}"
        return f"https://t.me/c/{str(abs(chat_id))[-10:]}/{message_id}"

    async def _admin_report(self, bot: Bot, text: str) -> None:
        if not self.admin_chat:
            return
        try:
            await bot.send_message(self.admin_chat, text)
        except Exception as exc:
            print(f"real-time admin report failed: {exc}")

    async def _webhook(self, payload: dict[str, Any]) -> None:
        if not self.webhook_url:
            return
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.webhook_secret:
            headers["Authorization"] = f"Bearer {self.webhook_secret}"
        request = Request(self.webhook_url, data=body, headers=headers, method="POST")
        try:
            await asyncio.to_thread(self._post_webhook, request)
        except Exception as exc:
            print(f"website webhook failed: {exc}")

    @staticmethod
    def _post_webhook(request: Request) -> None:
        with urlopen(request, timeout=5) as response:
            if response.status >= 300:
                raise RuntimeError(f"webhook status {response.status}")

    async def on_channel_post(self, message: Message, bot: Bot) -> None:
        if self.active_channels and message.chat.id not in self.active_channels:
            return
        text = (message.text or message.caption or "").strip()
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO channel_posts(channel_id,message_id,channel_title,channel_username,text,posted_at) VALUES(?,?,?,?,?,?)",
                (
                    message.chat.id,
                    message.message_id,
                    message.chat.title or "",
                    message.chat.username or "",
                    text[:4000],
                    dt.datetime.now().isoformat(timespec="seconds"),
                ),
            )
            self.conn.commit()
        link = self._message_link(message.chat.id, message.message_id, message.chat.username or "")
        await self._admin_report(bot, f"📣 Channel post ใหม่\n{message.chat.title or message.chat.id}\nโพสต์ #{message.message_id}\n{link}\n\nใช้คำสั่ง /new_task ใน Discussion thread เพื่อเปิดเป็นงาน")

    async def new_task(self, message: Message, bot: Bot) -> None:
        if message.from_user is None or not self._is_admin(message.from_user.id):
            await message.reply("🚫 คำสั่งนี้สำหรับแอดมินเท่านั้น")
            return
        if not self._is_allowed_discussion(message.chat.id):
            return
        source = self._source_post(message)
        if source is None:
            await message.reply("กรุณาตอบกลับโพสต์ต้นฉบับที่บอท forward มาจาก Channel แล้วใช้คำสั่งนี้ใน Discussion thread")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.reply("รูปแบบ: /new_task ชื่องาน | คะแนน | 2026-10-16T23:59:00")
            return
        fields = [field.strip() for field in parts[1].split("|")]
        if len(fields) != 3:
            await message.reply("รูปแบบ: /new_task ชื่องาน | คะแนน | 2026-10-16T23:59:00")
            return
        title, points_raw, deadline_raw = fields
        try:
            points = int(points_raw)
            deadline = dt.datetime.fromisoformat(deadline_raw)
            if not title or points < 1:
                raise ValueError
        except ValueError:
            await message.reply("คะแนนต้องเป็นจำนวนเต็มบวก และ deadline ต้องเป็น ISO datetime เช่น 2026-10-16T23:59:00")
            return
        thread_id = message.message_thread_id or (message.reply_to_message.message_id if message.reply_to_message else 0)
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "INSERT INTO racer_tasks(title,channel_id,channel_post_id,discussion_chat_id,discussion_thread_id,points,deadline,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (title, source[0], source[1], message.chat.id, thread_id, points, deadline.isoformat(), message.from_user.id, dt.datetime.now().isoformat(timespec="seconds")),
                )
                task_id = cursor.lastrowid
                self.conn.commit()
            except sqlite3.IntegrityError:
                await message.reply("โพสต์นี้ถูกเปิดเป็น Task แล้ว")
                return
        await message.reply(f"✅ เปิด Task #{task_id} แล้ว\n{title}\nคะแนน: {points}\nหมดเขต: {deadline:%d/%m/%Y %H:%M}")
        await self._admin_report(bot, f"🟢 เปิด Task #{task_id}\n{title}\nโพสต์ต้นทาง: {source[0]}/{source[1]}\nคะแนน {points} · หมดเขต {deadline:%Y-%m-%d %H:%M}")

    async def list_tasks(self, message: Message) -> None:
        if message.from_user is None or not self._is_admin(message.from_user.id):
            return
        with self.lock:
            rows = self.conn.execute("SELECT id,title,points,deadline,status FROM racer_tasks ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            await message.reply("ยังไม่มี Task")
            return
        text = "\n".join(f"#{row['id']} · {row['title']} · {row['points']} pts · {row['status']} · {row['deadline']}" for row in rows)
        await message.reply("📋 Tasks\n" + text)

    async def handle_evidence(self, message: Message, bot: Bot) -> bool:
        """Return True when the image belongs to a known Task discussion."""
        if message.from_user is None or not message.photo or not self._is_allowed_discussion(message.chat.id):
            return False
        source = self._source_post(message)
        thread_id = message.message_thread_id or (message.reply_to_message.message_id if message.reply_to_message else 0)
        with self.lock:
            task = None
            if source:
                task = self.conn.execute(
                    "SELECT * FROM racer_tasks WHERE channel_id=? AND channel_post_id=? AND status='active'",
                    source,
                ).fetchone()
            if task is None and thread_id:
                task = self.conn.execute(
                    "SELECT * FROM racer_tasks WHERE discussion_chat_id=? AND discussion_thread_id=? AND status='active'",
                    (message.chat.id, thread_id),
                ).fetchone()
        if task is None:
            return False
        now = dt.datetime.now()
        deadline = dt.datetime.fromisoformat(task["deadline"])
        if now > deadline:
            await message.reply(f"⛔ Task #{task['id']} หมดเขตแล้วเมื่อ {deadline:%d/%m/%Y %H:%M}")
            return True
        user = self.get_user(message.from_user.id, message.from_user.username)
        telegram_file = await bot.get_file(message.photo[-1].file_id)
        buffer = io.BytesIO()
        await bot.download_file(telegram_file.file_path, buffer)
        image_bytes = buffer.getvalue()
        digest = hashlib.sha256(image_bytes).hexdigest()
        with self.lock:
            previous = self.conn.execute(
                "SELECT status FROM task_submissions WHERE task_id=? AND user_id=? AND status IN ('verifying','passed') ORDER BY id DESC LIMIT 1",
                (task["id"], user["id"]),
            ).fetchone()
            if previous:
                await message.reply("⚠️ คุณมีหลักฐานของ Task นี้ที่กำลังตรวจหรือผ่านแล้ว ไม่ต้องส่งซ้ำ")
                return True
            try:
                self.conn.execute(
                    "INSERT INTO task_submissions(task_id,user_id,username,evidence_message_id,source_post_id,image_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                    (task["id"], user["id"], message.from_user.username or "", message.message_id, task["channel_post_id"], digest, now.isoformat(timespec="seconds")),
                )
                self.conn.commit()
            except sqlite3.IntegrityError:
                await message.reply("⚠️ หลักฐานภาพนี้ถูกใช้แล้ว")
                return True
        await message.reply(f"⏳ รับหลักฐานแล้ว · Task #{task['id']}\nระบบกำลังตรวจภาพและจะตอบผลใน thread นี้")
        asyncio.create_task(self._verify_and_report(message, bot, task, user, image_bytes))
        return True

    async def _verify_and_report(self, message: Message, bot: Bot, task: sqlite3.Row, user: sqlite3.Row, image_bytes: bytes) -> None:
        try:
            model = self.gemini_model()
            prompt = "ตรวจหลักฐานกิจกรรมนี้ ตอบ JSON เท่านั้น: {\"like\":true,\"repost\":true,\"bookmark\":true,\"comment\":true} ค่าทุกตัวเป็น boolean"
            response = await asyncio.to_thread(model.generate_content, [prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
            checks = self.parse_ai_result(response.text)
            passed = all(checks.values())
            points = int(task["points"]) if passed else 0
            status = "passed" if passed else "failed"
            missing = ", ".join(key for key, value in checks.items() if not value)
            with self.lock:
                self.conn.execute(
                    "UPDATE task_submissions SET status=?,checks_json=?,points=?,error=? WHERE task_id=? AND user_id=? AND image_hash=?",
                    (status, json.dumps(checks), points, "" if passed else missing, task["id"], user["id"], hashlib.sha256(image_bytes).hexdigest()),
                )
                self.conn.execute("UPDATE users SET checks=checks+1, passed=passed+?, score=score+? WHERE id=?", (int(passed), points, user["id"]))
                self.conn.execute("INSERT INTO tasks(uid,ts,passed,points,source) VALUES(?,?,?,?,?)", (user["id"], dt.datetime.now().isoformat(timespec="seconds"), int(passed), points, user["username"]))
                self.conn.commit()
            if passed:
                reply = f"✅ ตรวจผ่านแล้ว · Task #{task['id']}\nกิจกรรม: {task['title']}\n✓ Like  ✓ Repost  ✓ Bookmark  ✓ Comment\nได้รับ +{points} คะแนน"
            else:
                reply = f"❌ หลักฐานยังไม่ครบ · Task #{task['id']}\nยังขาด: {missing}\nกรุณาส่งภาพใหม่ใน thread นี้"
            await message.reply(reply)
            report = f"{'✅' if passed else '❌'} ผลตรวจเรียลไทม์ · Task #{task['id']}\nผู้ส่ง: @{user['username']}\nโพสต์ต้นทาง: {task['channel_id']}/{task['channel_post_id']}\nสถานะ: {status} · คะแนน {points}"
            await self._admin_report(bot, report)
            await self._webhook({"event": "task_submission_verified", "taskId": task["id"], "taskTitle": task["title"], "userId": user["id"], "username": user["username"], "channelId": task["channel_id"], "channelPostId": task["channel_post_id"], "evidenceMessageId": message.message_id, "status": status, "checks": checks, "points": points})
        except Exception as exc:
            with self.lock:
                self.conn.execute("UPDATE task_submissions SET status='error',error=? WHERE task_id=? AND user_id=? ORDER BY id DESC LIMIT 1", (str(exc)[:300], task["id"], user["id"]))
                self.conn.commit()
            await message.reply("⚠️ ระบบตรวจภาพขัดข้องชั่วคราว กรุณาส่งหลักฐานใหม่ภายหลัง")

    def register(self, router: Router) -> None:
        router.channel_post(F.photo | F.text | F.caption)(self.on_channel_post)
        router.message(Command("new_task"))(self.new_task)
        router.message(Command("tasks"))(self.list_tasks)
