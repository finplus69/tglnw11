# Tele Workspace Companion (Chrome Extension)

ส่วนขยาย Manifest V3 สำหรับ Chrome ที่ทำงานเป็น companion บน Telegram Web:

- เปิด Telegram Web ได้จาก popup
- บันทึกชื่อกลุ่มและจำนวน export ใน `chrome.storage.sync`
- คัดลอกคำสั่งสำหรับ `tele.py` ได้
- แสดง Safe mode panel บน `web.telegram.org`

ส่วนขยายนี้ **ไม่อ่าน Telegram session/API credential**, ไม่ส่งข้อความอัตโนมัติ และไม่เพิ่มสมาชิกจำนวนมาก

## ติดตั้งแบบไฟล์ ZIP

1. ดาวน์โหลด `tele-workspace-companion-v1.0.0.zip`
2. แตก ZIP เป็นโฟลเดอร์ เช่น `tele-workspace-companion`
3. เปิด Chrome ไปที่ `chrome://extensions`
4. เปิด **Developer mode** มุมขวาบน
5. กด **Load unpacked**
6. เลือกโฟลเดอร์ที่มีไฟล์ `manifest.json`
7. เปิด [Telegram Web](https://web.telegram.org/) แล้วกดไอคอนส่วนขยายเพื่อบันทึกกลุ่ม

## ใช้กับ CLI หลัก

คำสั่งที่คัดลอกจากส่วนขยายต้องรันในโฟลเดอร์โปรเจกต์หลัก:

```bash
python tele.py setup
python tele.py export-members --group @your_group --output members-export.csv --limit 1000
```
