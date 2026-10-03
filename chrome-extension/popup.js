const groupInput = document.querySelector('#group');
const limitInput = document.querySelector('#limit');
const tokenInput = document.querySelector('#token');
const status = document.querySelector('#status');

function show(message) {
  status.textContent = message;
  window.setTimeout(() => { status.textContent = ''; }, 3500);
}

function command() {
  const group = groupInput.value.trim() || '@your_group';
  const limit = Math.max(1, Math.min(10000, Number(limitInput.value) || 1000));
  return `python tele.py export-members --group ${group} --output members-export.csv --limit ${limit}`;
}

chrome.storage.sync.get({ group: '', limit: 1000 }, (settings) => {
  groupInput.value = settings.group;
  limitInput.value = settings.limit;
});
chrome.storage.local.get({ notifyToken: '' }, (settings) => { tokenInput.value = settings.notifyToken; });

document.querySelector('#save').addEventListener('click', async () => {
  const group = groupInput.value.trim();
  const limit = Math.max(1, Math.min(10000, Number(limitInput.value) || 1000));
  await chrome.storage.sync.set({ group, limit });
  await chrome.storage.local.set({ notifyToken: tokenInput.value.trim() });
  try {
    const response = await fetch('http://127.0.0.1:8765/health', { cache: 'no-store' });
    show(response.ok ? 'บันทึกแล้ว • bridge พร้อมใช้งาน' : 'บันทึกแล้ว แต่ bridge ยังไม่พร้อม');
  } catch (_) {
    show('บันทึกแล้ว • เปิดคำสั่ง notifications เพื่อรับแจ้งเตือน');
  }
});

document.querySelector('#open').addEventListener('click', () => {
  chrome.tabs.create({ url: 'https://web.telegram.org/' });
});

document.querySelector('#copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(command());
    show('คัดลอกคำสั่งแล้ว');
  } catch (_) {
    show('คัดลอกไม่ได้ กรุณาใช้ HTTPS หรือคัดลอกจากช่องคำสั่ง');
  }
});
