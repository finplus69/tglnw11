# เชื่อม `tele.py` กับ Chrome Extension แบบเรียลไทม์

สถาปัตยกรรมใช้ **local-only SSE bridge**:

```text
tele.py command -> POST 127.0.0.1:8765/emit -> service-worker.js -> chrome.notifications
```

ไม่มีข้อมูลส่งออกอินเทอร์เน็ต และ bridge bind เฉพาะ `127.0.0.1`

## ตั้งค่า

```bash
python tele.py setup
python tele.py notify-token
python tele.py notifications
```

นำ token ที่ได้จาก `notify-token` ไปใส่ในช่อง **Notification token** ของ popup แล้วกด **บันทึก** จากนั้นให้เปิด `notifications` ค้างไว้ใน terminal

## เรียกใช้งาน

เปิด terminal ใหม่แล้วใช้คำสั่งเดิม:

```bash
python tele.py check
python tele.py groups
python tele.py export-members --group @your_group --limit 1000
```

แต่ละคำสั่งจะ emit event `task_started`, `task_completed` หรือ `error` ไปยัง service worker ซึ่งจะแสดง desktop notification

## ปรับแต่งเพิ่ม

- เปลี่ยน port ด้วย `TELE_NOTIFY_PORT=9000` แต่ต้องแก้ `BRIDGE` และ `host_permissions` ใน extension ให้ตรงกัน
- เพิ่ม event ใหม่ด้วย `emit_event("ชื่อ_event", "ข้อความ", key=value)` ใน `tele.py`
- ปรับชื่อ/priority/icon แจ้งเตือนได้ใน `service-worker.js`
- หากไม่เปิด bridge งาน Telegram ยังทำงานต่อได้ เพราะ event delivery เป็น best-effort

## ข้อควรระวัง

- ห้ามแชร์ notification token
- ห้าม bind bridge เป็น `0.0.0.0`
- token อยู่ใน `~/.tele-workspace/notify.token` และควรมี permission `600`
- ใช้เฉพาะบัญชีและกลุ่มที่ได้รับอนุญาต
