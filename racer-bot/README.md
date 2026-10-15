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
