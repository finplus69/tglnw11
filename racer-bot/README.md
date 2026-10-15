# Racer Check Bot

บอท Telegram สำหรับตรวจสกรีนช็อตด้วย Gemini, คิดคะแนน, leaderboard, รายงานแอดมิน, backup SQLite และ dashboard แบบ read-only

## ติดตั้งและรันในเครื่อง

```bash
cd racer-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# export ตัวแปรจาก .env ด้วยวิธีที่คุณใช้งาน เช่น direnv หรือกำหนดใน shell
python bot.py
```

ต้องตั้งค่าอย่างน้อย `BOT_TOKEN`, `GEMINI_KEY` และ `ALLOWED_CHAT` โดยไม่ใส่ secret ลง GitHub บอทจะเปิด dashboard ที่ `http://localhost:8080` หรือค่า `PORT` ที่ระบบกำหนด

## Deploy บน Railway

1. Push โฟลเดอร์นี้ขึ้น GitHub หรือเลือก repo นี้ใน Railway
2. สร้าง service จาก repo และกำหนดตัวแปรในหน้า **Variables** ตาม `.env.example`
3. อย่า commit `.env`, `score.db` หรือโฟลเดอร์ `backups`
4. Railway จะใช้ `railway.json` และรัน `python bot.py` อัตโนมัติ
5. เปิด public domain ของ Railway เพื่อดู dashboard; แนะนำให้ตั้ง `DASHBOARD_TOKEN` เพื่อป้องกันการเปิด leaderboard ต่อสาธารณะ

> Railway อาจมีข้อจำกัดด้าน free plan, ชั่วโมงใช้งาน, sleep และ persistent storage ซึ่งเปลี่ยนแปลงตามนโยบายของ Railway ควรตรวจสอบราคาและเงื่อนไขปัจจุบันในบัญชีของคุณก่อนใช้งานจริง

## Backup

บอทสร้าง backup แรกเมื่อเริ่มทำงาน จากนั้นทุก 6 ชั่วโมง และเก็บไฟล์ล่าสุด 7 เวอร์ชัน ใช้ SQLite backup API และเขียนไฟล์แบบชั่วคราวก่อนเปลี่ยนชื่อ เพื่อไม่คัดลอกฐานข้อมูลกลางคัน

โปรดทราบว่า filesystem ของ Railway อาจไม่ถาวรเมื่อ redeploy/restart หากต้องการ backup ที่ทนต่อการลบ service ควรต่อ persistent volume หรือส่ง backup ไป object storage เพิ่มเติม

## ความปลอดภัยที่แก้จากโค้ดเดิม

- ย้าย token/API key/ID ทั้งหมดไป environment variables
- เปลี่ยน `eval()` เป็น JSON parsing และตรวจ schema ของผล AI
- ใช้ SHA-256 และ unique constraint ป้องกันภาพซ้ำ
- escape username ก่อนใส่ใน HTML dashboard
- ใช้ lock และ SQLite WAL ให้เข้ากับ bot + dashboard ที่ทำงานพร้อมกัน
- ไม่ใช้ bulk messaging, bulk member adding หรือการหลบเลี่ยงข้อจำกัดของ Telegram

## Channel Post → Discussion Thread → Task

บอทรองรับการติดตามโพสต์ใน Channel และผูกกับ Discussion thread ด้วย `channel_id + channel_post_id` โดยไม่ต้องเดา thread จากข้อความ ผู้ใช้ต้องคอมเมนต์หลักฐานใต้โพสต์กิจกรรมที่บอท forward มาจาก Channel

### ตั้งค่า Telegram

1. เชื่อม Discussion Group เข้ากับ Channel
2. เพิ่มบอทเป็นแอดมินใน Channel และ Discussion Group พร้อมสิทธิ์อ่านข้อความและส่งข้อความ
3. ตั้ง `ACTIVE_CHANNEL_IDS` เป็น Channel ID ที่ต้องการติดตาม
4. ตั้ง `ALLOWED_CHAT` เป็น Discussion Group ID ที่รับหลักฐาน
5. ตั้ง `ADMIN_IDS` และ `ADMIN_CHAT` สำหรับคำสั่ง/รายงานแบบเรียลไทม์

### เปิด Task จาก thread

เมื่อมีโพสต์กิจกรรมใหม่ บอทจะแจ้งแอดมินแบบเรียลไทม์ จากนั้นให้แอดมินตอบกลับโพสต์ต้นฉบับใน Discussion thread ด้วย:

```text
/new_task ชื่องาน | 40 | 2026-10-16T23:59:00
```

คำสั่งเสริม:

```text
/tasks
```

การตอบกลับต้องอยู่ใต้ auto-forwarded channel post เพื่อให้ระบบเชื่อม `channel_id`, `channel_post_id`, `discussion_chat_id` และ `discussion_thread_id` ได้ถูกต้อง

### ส่งหลักฐานและการตอบกลับ

ผู้เข้าร่วมส่งรูปใต้ thread เดิม บอทจะตรวจ deadline, hash ภาพซ้ำ, สถานะการส่งของผู้ใช้, ส่งภาพเข้า Gemini และตอบกลับใน thread เดิมด้วยสถานะ `ผ่าน`, `ไม่ผ่าน`, `รอตรวจ` หรือ `ผิดพลาด` พร้อมแจ้งคะแนนให้แอดมินใน `ADMIN_CHAT` ทันที

### ต่อเข้ากับ Racer Board

ถ้าตั้ง `RACER_WEBHOOK_URL` บอทจะส่ง `task_submission_verified` หลังตรวจเสร็จพร้อม `taskId`, ผู้ใช้, โพสต์ต้นทาง, message ID ของหลักฐาน, checks, status และ points โดยใช้ `RACER_WEBHOOK_SECRET` เป็น Bearer token วิธีนี้ทำให้ Dashboard อัปเดตได้โดยไม่ต้องเปิดไฟล์ SQLite ของ Railway ออกสาธารณะ

## X (Twitter) → Telegram Task

โมดูล `x_integration.py` เชื่อม X API v2 เข้ากับ Task โดยใช้ App Bearer Token สำหรับอ่านโพสต์และ `public_metrics` เช่น likes, reposts, replies และ bookmarks

ตั้งค่าใน `.env`:

```env
X_BEARER_TOKEN=จาก X Developer Console
X_POST_IDS=1234567890123456789,1234567890123456790
X_POLL_SECONDS=30
# ทางเลือก: rule ของ Filtered Stream
X_FILTERED_STREAM_RULE=from:your_account -is:retweet
```

ใน Discussion thread ของ Task ใช้คำสั่ง:

```text
/link_x_task https://x.com/brand/status/1234567890123456789 | X Campaign | 40 | 2026-10-16T23:59:00
```

บอทจะเรียก X API เพื่อตรวจว่าโพสต์มีอยู่จริง บันทึก `x_post_id` และ `x_post_url` ลง Task แล้วติดตาม metrics ต่อเนื่อง ทุกครั้งที่ค่าเปลี่ยนจะส่งรายงานไป `ADMIN_CHAT` และ `RACER_WEBHOOK_URL` ถ้ามีการตั้งค่าไว้

`X_FILTERED_STREAM_RULE` เปิดการรับโพสต์ที่ตรง rule ใกล้เรียลไทม์ผ่าน `/2/tweets/search/stream` โดยระบบจะ reconnect เมื่อ connection หลุด ส่วนการติดตามโพสต์ที่ผูก Task ใช้ polling เป็น fallback ที่ควบคุม interval ได้

### ข้อจำกัดการตรวจ action รายบุคคล

Bearer Token อ่านได้เฉพาะข้อมูลสาธารณะและยอดรวมของโพสต์ ไม่สามารถยืนยันได้ว่า Telegram user คนใดกด Like, Repost หรือ Bookmark ใน X การตรวจแบบรายบุคคลต้องใช้ OAuth user context ของผู้ใช้คนนั้นเอง และต้องมี scope เช่น `bookmark.read`, `tweet.read`, `users.read` จึงไม่ควรตอบผู้ใช้ว่า “ทำกิจกรรมแล้ว” จากยอดรวมของโพสต์เพียงอย่างเดียว

ดูเอกสารอ้างอิงปัจจุบันได้ที่ [X API overview](https://docs.x.com/x-api/getting-started/about-x-api), [metrics](https://docs.x.com/x-api/fundamentals/metrics), [filtered stream](https://docs.x.com/x-api/posts/filtered-stream/introduction) และ [bookmarks lookup](https://docs.x.com/x-api/posts/bookmarks/quickstart/bookmarks-lookup)
