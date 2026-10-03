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
