# Tele Workspace

เครื่องมือ CLI สำหรับจัดการบัญชี Telegram และส่งออกไดเรกทอรีสมาชิกของกลุ่มที่คุณมีสิทธิ์ดูแล โดยเน้นความปลอดภัยและการลดข้อมูลส่วนบุคคล

> **ขอบเขตสำคัญ:** โปรเจกต์นี้ไม่รองรับการส่งข้อความจำนวนมาก การเพิ่มสมาชิกจำนวนมาก การหมุนหลายบัญชี หรือการหลบเลี่ยง flood limit ของ Telegram ใช้เฉพาะกับบัญชี/กลุ่มที่คุณควบคุมหรือได้รับอนุญาต และปฏิบัติตาม [Telegram Terms of Service](https://telegram.org/tos) เสมอ

## ติดตั้ง

```bash
python3 -m venv .venv
. .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
```

## ตั้งค่าและล็อกอิน

สร้าง API ID และ API hash ได้จาก [my.telegram.org](https://my.telegram.org):

```bash
python tele.py setup
python tele.py check
```

ค่า config และ session จะถูกเก็บใน `~/.tele-workspace` และไม่ถูก commit เข้า Git หากต้องการเปลี่ยนที่เก็บข้อมูล ให้ตั้ง `TELE_HOME` ก่อนรัน

## คำสั่ง

```bash
python tele.py check
python tele.py groups
python tele.py export-members --group @your_group --output members-export.csv --limit 1000
```

ไฟล์ export จะเก็บเฉพาะ `username`, `display_name`, และ `group` เป็นค่าเริ่มต้น โดยไม่เก็บ user ID หรือ access hash เพื่อจำกัดการรั่วไหลของข้อมูล

## Chrome Extension

มีไฟล์ติดตั้ง `tele-workspace-companion-v1.1.0.zip` สำหรับ Chrome เป็นส่วนเสริม companion ของ Telegram Web:

1. แตกไฟล์ ZIP
2. เปิด `chrome://extensions`
3. เปิด **Developer mode**
4. กด **Load unpacked** แล้วเลือกโฟลเดอร์ที่มี `manifest.json`

ส่วนขยายช่วยบันทึกชื่อกลุ่ม, คัดลอกคำสั่งให้ `tele.py` และแสดง desktop notification จากงาน CLI แบบเรียลไทม์ ไม่อ่าน session/API hash และไม่ส่งข้อความหรือเพิ่มสมาชิกอัตโนมัติ อ่านรายละเอียดได้ที่ [`chrome-extension/README.md`](chrome-extension/README.md) และ [`chrome-extension/INTEGRATION.md`](chrome-extension/INTEGRATION.md)

เปิด realtime bridge ก่อนใช้งาน:

```bash
python tele.py notify-token
python tele.py notifications
```

นำ token ไปใส่ใน popup ของส่วนขยาย แล้วใช้ `check`, `groups` หรือ `export-members` ใน terminal

แพ็กเกจรวมที่มี `manifest.json` อยู่ที่โฟลเดอร์รากสำหรับ **Load unpacked**: `tele-workspace-v1.1.0-full.zip`

## ความปลอดภัย

- ห้าม commit `config.env`, session, API hash, เบอร์โทร หรือ CSV ที่มีข้อมูลสมาชิกจริง
- หาก session เดิมเคยถูกอัปโหลดแล้ว ให้ลบออกจาก Git และยกเลิก session นั้นจาก Telegram: **Settings → Devices → Terminate session**
- ห้ามนำข้อมูล export ไปใช้ส่งสแปม เพิ่มสมาชิกโดยไม่ได้รับความยินยอม หรือทำให้บัญชีอื่นเดือดร้อน

## ทดสอบ

```bash
python -m compileall -q tele.py
python tele.py --help
```

## License

MIT License ตามไฟล์ `LICENSE`
