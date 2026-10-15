"""X API v2 integration for X-post-linked Telegram tasks.

Public post lookup and public_metrics use an app Bearer Token. Per-user likes,
reposts and bookmarks are intentionally not guessed from public counts; those
require the participant's own OAuth user context.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

X_API_BASE = "https://api.x.com/2"
POST_URL_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/(\d+)")


class XApiError(RuntimeError):
    pass


def parse_x_post_id(value: str) -> str:
    value = value.strip()
    match = POST_URL_RE.fullmatch(value)
    if match:
        return match.group(1)
    if value.isdigit():
        return value
    raise ValueError("ต้องเป็น X URL เช่น https://x.com/user/status/123 หรือ post ID")


class XApiClient:
    def __init__(self, bearer_token: str) -> None:
        self.bearer_token = bearer_token

    def _request_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{X_API_BASE}{path}{query}",
            headers={"Authorization": f"Bearer {self.bearer_token}", "User-Agent": "racer-check-bot/1.0"},
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status >= 300:
                    raise XApiError(f"X API HTTP {response.status}: {payload}")
                return payload
        except XApiError:
            raise
        except Exception as exc:
            raise XApiError(str(exc)) from exc

    def get_post(self, post_id: str) -> dict[str, Any]:
        return self._request_json(
            f"/tweets/{post_id}",
            {
                "tweet.fields": "created_at,public_metrics,conversation_id,author_id,lang,possibly_sensitive",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            },
        )

    def recent_search(self, query: str) -> dict[str, Any]:
        return self._request_json(
            "/tweets/search/recent",
            {
                "query": query,
                "max_results": "10",
                "tweet.fields": "created_at,public_metrics,conversation_id,author_id",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            },
        )

    def ensure_stream_rule(self, rule: str) -> dict[str, Any]:
        existing = self._request_json("/tweets/search/stream/rules")
        if any(item.get("value") == rule for item in existing.get("data", [])):
            return existing
        body = json.dumps({"add": [{"value": rule, "tag": "racer-check-bot"}]}).encode("utf-8")
        request = Request(
            f"{X_API_BASE}/tweets/search/stream/rules",
            data=body,
            headers={
                "Authorization": f"Bearer {self.bearer_token}",
                "Content-Type": "application/json",
                "User-Agent": "racer-check-bot/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status >= 300:
                    raise XApiError(f"X API HTTP {response.status}: {payload}")
                return payload
        except XApiError:
            raise
        except Exception as exc:
            raise XApiError(str(exc)) from exc

    def stream_rule(self, rule: str) -> AsyncIterator[dict[str, Any]]:
        return self._stream_rule(rule)

    async def _stream_rule(self, rule: str) -> AsyncIterator[dict[str, Any]]:
        """Yield filtered-stream events; reconnect after disconnects/keep-alives."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def worker() -> None:
            while True:
                try:
                    params = {"tweet.fields": "created_at,public_metrics,conversation_id,author_id"}
                    request = Request(
                        f"{X_API_BASE}/tweets/search/stream?{urlencode(params)}",
                        headers={"Authorization": f"Bearer {self.bearer_token}", "User-Agent": "racer-check-bot/1.0"},
                    )
                    with urlopen(request, timeout=95) as response:
                        for raw_line in response:
                            line = raw_line.decode("utf-8").strip()
                            if not line:
                                continue
                            payload = json.loads(line)
                            loop.call_soon_threadsafe(queue.put_nowait, payload)
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"_x_error": str(exc)})
                    time.sleep(5)

        # The caller registers the configured rule before opening this stream.
        threading.Thread(target=worker, name="x-filtered-stream", daemon=True).start()
        while True:
            event = await queue.get()
            if event.get("_x_error"):
                raise XApiError(event["_x_error"])
            yield event


class XMonitor:
    def __init__(self, connection: sqlite3.Connection, lock: Any, admin_chat: int, webhook_url: str = "", webhook_secret: str = "") -> None:
        self.conn = connection
        self.lock = lock
        self.admin_chat = admin_chat
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.bearer_token = os.getenv("X_BEARER_TOKEN", "")
        self.poll_seconds = max(15, int(os.getenv("X_POLL_SECONDS", "30")))
        self.post_ids = {value.strip() for value in os.getenv("X_POST_IDS", "").split(",") if value.strip()}
        self.stream_rule = os.getenv("X_FILTERED_STREAM_RULE", "").strip()
        self.client = XApiClient(self.bearer_token) if self.bearer_token else None
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS x_posts (
                    post_id TEXT PRIMARY KEY,
                    post_url TEXT NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    author_id TEXT NOT NULL DEFAULT '',
                    author_username TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    last_seen TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(racer_tasks)")}
            if "x_post_id" not in columns:
                self.conn.execute("ALTER TABLE racer_tasks ADD COLUMN x_post_id TEXT")
            if "x_post_url" not in columns:
                self.conn.execute("ALTER TABLE racer_tasks ADD COLUMN x_post_url TEXT")
            self.conn.commit()

    @staticmethod
    def _author(payload: dict[str, Any]) -> tuple[str, str]:
        data = payload.get("includes", {}).get("users", [])
        if data:
            return str(data[0].get("id", "")), str(data[0].get("username", ""))
        return "", ""

    @staticmethod
    def _public_url(post_id: str, username: str = "") -> str:
        return f"https://x.com/{username}/status/{post_id}" if username else f"https://x.com/i/web/status/{post_id}"

    async def _send_admin(self, bot: Bot, text: str) -> None:
        if not self.admin_chat:
            return
        try:
            await bot.send_message(self.admin_chat, text, disable_web_page_preview=True)
        except Exception as exc:
            print(f"X admin report failed: {exc}")

    async def _send_webhook(self, payload: dict[str, Any]) -> None:
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
            print(f"X webhook failed: {exc}")

    @staticmethod
    def _post_webhook(request: Request) -> None:
        with urlopen(request, timeout=5) as response:
            if response.status >= 300:
                raise RuntimeError(f"webhook HTTP {response.status}")

    async def link_x_task(self, message: Message, bot: Bot) -> None:
        if message.from_user is None or message.from_user.id not in self._admin_ids():
            await message.reply("🚫 คำสั่งนี้สำหรับแอดมินเท่านั้น")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.reply("รูปแบบ: /link_x_task https://x.com/user/status/123 | ชื่องาน | 40 | 2026-10-16T23:59:00")
            return
        fields = [field.strip() for field in parts[1].split("|")]
        if len(fields) != 4:
            await message.reply("รูปแบบ: /link_x_task URL | ชื่องาน | คะแนน | deadline")
            return
        try:
            post_id = parse_x_post_id(fields[0])
            title = fields[1]
            points = int(fields[2])
            deadline = dt.datetime.fromisoformat(fields[3])
            if not title or points < 1:
                raise ValueError
        except ValueError:
            await message.reply("URL/คะแนน/deadline ไม่ถูกต้อง เช่น 2026-10-16T23:59:00")
            return
        if self.client is None:
            await message.reply("ยังไม่ได้ตั้ง X_BEARER_TOKEN")
            return
        try:
            payload = await asyncio.to_thread(self.client.get_post, post_id)
            post = payload.get("data")
            if not post:
                raise XApiError("ไม่พบโพสต์หรือโพสต์ถูกลบ")
        except XApiError as exc:
            await message.reply(f"ดึงโพสต์จาก X ไม่สำเร็จ: {exc}")
            return
        thread_id = message.message_thread_id or (message.reply_to_message.message_id if message.reply_to_message else 0)
        url = self._public_url(post_id)
        with self.lock:
            try:
                cursor = self.conn.execute(
                    "INSERT INTO racer_tasks(title,channel_id,channel_post_id,discussion_chat_id,discussion_thread_id,points,deadline,created_by,created_at,x_post_id,x_post_url) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (title, 0, -int(post_id[-12:]), message.chat.id, thread_id, points, deadline.isoformat(), message.from_user.id, dt.datetime.now().isoformat(timespec="seconds"), post_id, url),
                )
                task_id = cursor.lastrowid
                self.conn.commit()
            except sqlite3.IntegrityError:
                await message.reply("โพสต์ X นี้ถูกผูกกับ Task แล้ว")
                return
        text = str(post.get("text", "")).replace("\n", " ")[:160]
        metrics = post.get("public_metrics", {})
        await message.reply(f"✅ ผูก X post กับ Task #{task_id} แล้ว\n{title}\nโพสต์: {url}\nตัวอย่างข้อความ: {text}\nคะแนน {points} · หมดเขต {deadline:%d/%m/%Y %H:%M}\nmetrics ปัจจุบัน: like {metrics.get('like_count', 0)} · repost {metrics.get('retweet_count', 0)} · reply {metrics.get('reply_count', 0)}")
        await self._send_admin(bot, f"🔗 X post ผูกกับ Task #{task_id}\n{title}\n{url}")

    def _admin_ids(self) -> set[int]:
        return {int(value.strip()) for value in os.getenv("ADMIN_IDS", "").split(",") if value.strip()}

    async def _observe_post(self, bot: Bot, post_id: str) -> None:
        if self.client is None:
            return
        payload = await asyncio.to_thread(self.client.get_post, post_id)
        post = payload.get("data")
        if not post:
            return
        author_id, username = self._author(payload)
        metrics = post.get("public_metrics", {})
        now = dt.datetime.now().isoformat(timespec="seconds")
        url = self._public_url(post_id, username)
        metrics_json = json.dumps(metrics, sort_keys=True)
        with self.lock:
            previous = self.conn.execute("SELECT metrics_json FROM x_posts WHERE post_id=?", (post_id,)).fetchone()
            changed = previous is None or previous[0] != metrics_json
            self.conn.execute(
                "INSERT INTO x_posts(post_id,post_url,text,author_id,author_username,created_at,metrics_json,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET text=excluded.text,author_id=excluded.author_id,author_username=excluded.author_username,metrics_json=excluded.metrics_json,last_seen=excluded.last_seen",
                (post_id, url, post.get("text", ""), author_id, username, post.get("created_at", ""), metrics_json, now),
            )
            task = self.conn.execute("SELECT id,title FROM racer_tasks WHERE x_post_id=? AND status='active'", (post_id,)).fetchone()
            self.conn.commit()
        if not changed:
            return
        task_label = f"Task #{task['id']} · {task['title']}" if task else "ยังไม่ผูก Task"
        report = f"📈 X post update · {task_label}\n{url}\n❤️ {metrics.get('like_count', 0)} · 🔁 {metrics.get('retweet_count', 0)} · 💬 {metrics.get('reply_count', 0)} · 🔖 {metrics.get('bookmark_count', 0)}"
        await self._send_admin(bot, report)
        await self._send_webhook({"event": "x_post_metrics_updated", "postId": post_id, "postUrl": url, "taskId": task["id"] if task else None, "taskTitle": task["title"] if task else None, "text": post.get("text", ""), "publicMetrics": metrics, "seenAt": now})

    async def _poll_loop(self, bot: Bot) -> None:
        while True:
            if self.client:
                with self.lock:
                    rows = self.conn.execute("SELECT x_post_id FROM racer_tasks WHERE x_post_id IS NOT NULL AND status='active'").fetchall()
                ids = self.post_ids | {str(row[0]) for row in rows}
                for post_id in ids:
                    try:
                        await self._observe_post(bot, post_id)
                    except Exception as exc:
                        print(f"X post lookup failed for {post_id}: {exc}")
            await asyncio.sleep(self.poll_seconds)

    async def _stream_loop(self, bot: Bot) -> None:
        if not self.client or not self.stream_rule:
            return
        while True:
            try:
                await asyncio.to_thread(self.client.ensure_stream_rule, self.stream_rule)
                async for event in self.client.stream_rule(self.stream_rule):
                    post = event.get("data", {})
                    post_id = str(post.get("id", ""))
                    if post_id:
                        await self._observe_post(bot, post_id)
            except Exception as exc:
                print(f"X filtered stream reconnecting: {exc}")
                await asyncio.sleep(5)

    async def run(self, bot: Bot) -> None:
        if not self.bearer_token:
            print("X monitor disabled: X_BEARER_TOKEN is not set")
            await asyncio.Event().wait()
        await asyncio.gather(self._poll_loop(bot), self._stream_loop(bot))

    def register(self, router: Router) -> None:
        router.message(Command("link_x_task"))(self.link_x_task)
